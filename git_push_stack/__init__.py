# -*- encoding: utf-8 -*-
#
#  Copyright © 2021 Mergify SAS
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.


import argparse
import asyncio
import importlib.metadata
import os
import re
import sys
import typing
from urllib import parse

import httpx
import rich
import rich.console

from git_push_stack.commit_msg_hook import COMMIT_MSG_HOOK


try:
    VERSION = importlib.metadata.version("git-push-stack")
except ImportError:
    # https://pyoxidizer.readthedocs.io/en/stable/oxidized_importer_behavior_and_compliance.html#importlib-metadata-compatibility
    VERSION = "0.1"

CHANGEID_RE = re.compile(r"Change-Id: (I[0-9a-z]{40})")  # noqa
READY_FOR_REVIEW_TEMPLATE = "mutation { markPullRequestReadyForReview(input: { pullRequestId: %s }) {} }"  # noqa
console = rich.console.Console(log_path=False, log_time=False)


def check_for_status(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    elif response.status_code < 500:
        data = response.json()
        console.print(f"url: {response.request.url}", style="red")
        console.print(f"data: {response.request.content.decode()}", style="red")
        console.print(
            f"HTTPError {response.status_code}: {data['message']}", style="red"
        )
        if "errors" in data:
            console.print(
                "\n".join(f"* {e.get('message') or e}" for e in data["errors"]),
                style="red",
            )
        sys.exit(1)
    else:
        response.raise_for_status()


async def git(args: str) -> str:
    # console.print(f"* running: git {args}")
    proc = await asyncio.create_subprocess_shell(
        f"git {args}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        console.log(f"fail to run `git {args}`:", style="red")
        console.log(f"{stdout.decode()}", style="red")
        sys.exit(1)
    return stdout.decode().strip()


def get_slug(url: str) -> typing.Tuple[str, str]:
    parsed = parse.urlparse(url)
    if parsed.netloc == "":
        # Probably ssh
        _, _, path = parsed.path.partition(":")
    else:
        path = parsed.path[1:].rstrip("/")

    user, repo = path.split("/", 1)
    if repo.endswith(".git"):
        repo = repo[:-4]
    return user, repo


async def do_setup() -> None:
    os.chdir((await git("rev-parse --show-toplevel")).strip())
    hook_file = os.path.join(".git", "hooks", "commit-msg")
    if os.path.exists(hook_file):
        with open(hook_file, "f") as f:
            data = f.read()
        if data != COMMIT_MSG_HOOK:
            console.print(
                f"error: {hook_file} differ from git_push_stack hook", style="red"
            )
            sys.exit(1)

    else:

        console.log("Installation of git commit-msg hook")
        with open(hook_file, "w") as f:
            f.write(COMMIT_MSG_HOOK)
        os.chmod(hook_file, 0o755)


class GitRef(typing.TypedDict):
    ref: str


class HeadRef(typing.TypedDict):
    sha: str


class PullRequest(typing.TypedDict):
    html_url: str
    number: str
    title: str
    head: HeadRef
    state: str


ChangeId = typing.NewType("ChangeId", str)
KnownChangeIDs = typing.NewType(
    "KnownChangeIDs", typing.Dict[ChangeId, typing.Optional[PullRequest]]
)


async def get_changeid_and_pull(
    client: httpx.AsyncClient, user: str, stack_prefix: str, ref: GitRef
) -> typing.Tuple[ChangeId, typing.Optional[PullRequest]]:
    branch = ref["ref"][len("refs/heads/") :]
    changeid = ChangeId(branch[len(stack_prefix) :])
    r = await client.get("pulls", params={"head": f"{user}:{branch}", "state": "open"})
    check_for_status(r)
    pulls = [
        p
        for p in typing.cast(typing.List[PullRequest], r.json())
        if p["state"] == "open"
    ]
    if len(pulls) > 1:
        raise RuntimeError(f"More than 1 pull found with this head: {branch}")
    elif pulls:
        return changeid, pulls[0]
    else:
        return changeid, None


Change = typing.NewType("Change", typing.Tuple[ChangeId, str, str, str])


async def get_local_changes(
    commits: typing.List[str],
    known_changeids: KnownChangeIDs,
) -> typing.List[Change]:
    changes = []
    for commit in commits:
        message = await git(f"log -1 --format='%b' {commit}")
        title = await git(f"log -1 --format='%s' {commit}")
        changeids = CHANGEID_RE.findall(message)
        if not changeids:
            console.print(
                f"`Change-Id:` line is missing on commit {commit}", style="red"
            )
            sys.exit(1)
        changeid = ChangeId(changeids[-1])
        changes.append(Change((changeid, commit, title, message)))
        pull = known_changeids.get(changeid)
        if pull is None:
            action = "to create"
            url = ""
            commit_info = commit[-7:]
        elif commit == pull["head"]["sha"]:
            action = "nothing"
            url = pull["html_url"]
            commit_info = commit[-7:]
        else:
            action = "to update"
            url = pull["html_url"]
            commit_info = f"{pull['head']['sha'][-7:]} -> {commit[-7:]}"
        console.log(
            f"* [yellow]\\[{action}][/] '[red]{commit_info}[/] - [b]{title}[/] {url} - {changeid}"
        )

    return changes


async def get_changeids_to_delete(
    changes: typing.List[Change], known_changeids: KnownChangeIDs
) -> typing.Set[ChangeId]:
    changeids_to_delete = set(known_changeids.keys()) - {
        changeid for changeid, commit, title, message in changes
    }
    for changeid in changeids_to_delete:
        pull = known_changeids.get(changeid)
        if pull:
            console.log(
                f"* [red]\\[to delete][/] '[red]{pull['head']['sha'][-7:]}[/] - [b]{pull['title']}[/] {pull['html_url']} - {changeid}"
            )
        else:
            console.log(
                f"* [red]\\[to delete][/] '[red].......[/] - [b]<missing pull request>[/] - {changeid}"
            )
    return changeids_to_delete


async def create_or_update_comments(
    client: httpx.AsyncClient, pulls: typing.List[PullRequest]
) -> None:
    first_line = "This pull request is part of a stack:\n"
    body = first_line
    for pull in pulls:
        body += f"1. {pull['title']} ([#{pull['number']}]({pull['html_url']}))\n"

    for pull in pulls:
        r = await client.get(f"issues/{pull['number']}/comments")
        check_for_status(r)
        for comment in r.json():
            if comment["body"].startswith(first_line):
                if comment["body"] != body:
                    await client.patch(comment["url"], json={"body": body})
                break
        else:
            await client.post(f"issues/{pull['number']}/comments", json={"body": body})


async def create_or_update_stack(
    client: httpx.AsyncClient,
    stacked_base_branch: str,
    stacked_dest_branch: str,
    changeid: ChangeId,
    commit: str,
    title: str,
    message: str,
    draft: bool,
    known_changeids: KnownChangeIDs,
) -> PullRequest:

    if changeid in known_changeids:
        pull = known_changeids.get(changeid)
        with console.status(
            f"* updating stacked branch `{stacked_dest_branch}` ({commit[-7:]}) - {pull['html_url'] if pull else '<stack branch without associated pull>'})"
        ):
            r = await client.patch(
                f"git/refs/heads/{stacked_dest_branch}",
                json={"sha": commit, "force": True},
            )
    else:
        with console.status(
            f"* creating stacked branch `{stacked_dest_branch}` ({commit[-7:]})"
        ):
            r = await client.post(
                "git/refs",
                json={"ref": f"refs/heads/{stacked_dest_branch}", "sha": commit},
            )

    check_for_status(r)

    pull = known_changeids.get(changeid)
    if pull and pull["head"]["sha"] == commit:
        action = "nothing"
    elif pull:
        action = "updated"
        with console.status(
            f"* updating pull request `{title}` (#{pull['number']}) ({commit[-7:]})"
        ):
            r = await client.patch(
                f"pulls/{pull['number']}",
                json={
                    "title": title,
                    "body": message,
                    "head": stacked_dest_branch,
                    "base": stacked_base_branch,
                },
            )
            check_for_status(r)
            pull = typing.cast(PullRequest, r.json())
            if not draft:
                r = await client.post(
                    "/graghql",
                    headers={"Accept": "application/vnd.github.v4.idl"},
                    content=READY_FOR_REVIEW_TEMPLATE % pull["number"],
                )
                check_for_status(r)
    else:
        action = "created"
        with console.status(
            f"* creating stacked pull request `{title}` ({commit[-7:]})"
        ):
            r = await client.post(
                "pulls",
                json={
                    "title": title,
                    "body": message,
                    "draft": draft,
                    "head": stacked_dest_branch,
                    "base": stacked_base_branch,
                },
            )
            check_for_status(r)
            pull = typing.cast(PullRequest, r.json())
    console.log(
        f"* [blue]\\[{action}][/] '[red]{commit[-7:]}[/] - [b]{pull['title']}[/] {pull['html_url']} - {changeid}"
    )
    return pull


async def delete_stack(
    client: httpx.AsyncClient,
    stack_prefix: str,
    changeid: ChangeId,
    known_changeids: KnownChangeIDs,
) -> None:
    r = await client.delete(
        f"git/refs/heads/{stack_prefix}{changeid}",
    )
    check_for_status(r)
    pull = known_changeids[changeid]
    if pull:
        console.log(
            f"* [red]\\[deleted][/] '[red]{pull['head']['sha'][-7:]}[/] - [b]{pull['title']}[/] {pull['html_url']} - {changeid}"
        )
    else:
        console.log(
            f"* [red]\\[deleted][/] '[red].......[/] - [b]<branch {stack_prefix}{changeid}>[/] - {changeid}"
        )


async def main(token: str, dry_run: bool) -> None:
    os.chdir((await git("rev-parse --show-toplevel")).strip())
    dest_branch = await git("rev-parse --abbrev-ref HEAD")
    remote, _, base_branch = (
        await git(f"for-each-ref --format='%(upstream:short)' refs/heads/{dest_branch}")
    ).partition("/")
    user, repo = get_slug(await git(f"config --get remote.{remote}.url"))

    if not dry_run:
        with console.status(
            f"Rebasing branch `{dest_branch}` on `{remote}/{base_branch}`...",
        ):
            await git(f"pull --rebase {remote} {base_branch}")
        console.log(f"branch `{dest_branch}` rebased on `{remote}/{base_branch}`")

        with console.status(
            f"Pushing branch `{dest_branch}` to `{remote}/{dest_branch}`...",
        ):
            await git(f"push -f {remote} {dest_branch}")
        console.log(f"branch `{dest_branch}` pushed to `{remote}/{dest_branch}` ")

    stack_prefix = f"git_push_stack/{dest_branch}/"

    base_commit_sha = await git(f"merge-base --fork-point {remote}/{base_branch}")
    if not base_commit_sha:
        console.log(
            f"Common commit between `{remote}/{base_branch}` and `{dest_branch}` branches not found",
            style="red",
        )
        sys.exit(1)

    commits = (await git(f"log --format='%H' {base_commit_sha}..{dest_branch}")).split(
        "\n"
    )

    known_changeids = KnownChangeIDs({})

    async with httpx.AsyncClient(
        base_url=f"https://api.github.com/repos/{user}/{repo}/",
        headers={
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": f"git_push_stack/{VERSION}",
            "Authorization": f"token {token}",
        },
    ) as client:
        with console.status("Retrieving latest pushed stacks"):
            r = await client.get(f"git/matching-refs/heads/{stack_prefix}")
            check_for_status(r)
            refs = typing.cast(typing.List[GitRef], r.json())

            tasks = [
                get_changeid_and_pull(client, user, stack_prefix, ref) for ref in refs
            ]
            if tasks:
                done, _ = await asyncio.wait(tasks)
                for task in done:
                    known_changeids.update(dict([await task]))  # noqa

        with console.status("Preparing stacked branches..."):
            console.log("Stacked pull request plan:", style="green")
            changes = await get_local_changes(commits, known_changeids)
            changeids_to_delete = await get_changeids_to_delete(
                changes, known_changeids
            )

        if dry_run:
            console.log("[orange]Finished (dry-run mode) :tada:[/]")
            sys.exit(0)
        console.log("New stacked pull request:", style="green")
        stacked_base_branch = base_branch
        draft = False
        pulls: typing.List[PullRequest] = []
        for changeid, commit, title, message in reversed(changes):
            depends_on = ""
            if pulls:
                depends_on = f"\n\nDepends-On: #{pulls[-1]['number']}"
            stacked_dest_branch = f"{stack_prefix}{changeid}"
            pull = await create_or_update_stack(
                client,
                stacked_base_branch,
                stacked_dest_branch,
                changeid,
                commit,
                title,
                message + depends_on,
                draft,
                known_changeids,
            )
            pulls.append(pull)
            stacked_base_branch = stacked_dest_branch
            draft = True

        with console.status("Updating comments..."):
            await create_or_update_comments(client, pulls)
        console.log("[green]Comments updated")

        with console.status("Deleting unused branches..."):
            delete_tasks = [
                delete_stack(client, stack_prefix, changeid, known_changeids)
                for changeid in changeids_to_delete
            ]
            if delete_tasks:
                await asyncio.wait(delete_tasks)

        console.log("[green]Finished :tada:[/]")


def GitHubToken(v: str) -> str:
    if not v:
        raise ValueError
    return v


def cli() -> None:
    parser = argparse.ArgumentParser(description="git-push-stack")
    parser.add_argument("--setup", "-s", action="store_true")
    parser.add_argument("--dry-run", "-n", action="store_true")
    parser.add_argument(
        "--token",
        default=os.environ.get("GITHUB_TOKEN", ""),
        type=GitHubToken,
        help="GitHub personal access token",
    )
    args = parser.parse_args()
    if args.setup:
        asyncio.run(do_setup())
    else:
        asyncio.run(main(args.token, args.dry_run))
