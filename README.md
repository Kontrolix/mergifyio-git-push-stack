# Mergify-cli - Stacked Pull Request Automation

## Introduction

Mergify-cli is a tool that automates the creation and management of stacked pull requests on GitHub. Stacked pull requests are a way to organize and review changes that are based on a single feature branch. This tool simplifies the process of creating multiple pull requests for each commit in the feature branch, similar to how Gerrit handles code reviews.

## What are Stacked Pull Requests?

Imagine you have a branch called `feature` with three commits: `A`, `B`, and `C`, based on the `main` branch. To create stacked pull requests with this feature branch, you would traditionally have to perform the following steps:

1. Create a branch `feature-A` with only commit `A` based on `main` and create a pull request.
2. Create a branch `feature-B` with only commit `B` based on `feature-A` and create a pull request.
3. Create a branch `feature-C` with only commit `C` based on `feature-B` and create a pull request.

However, GitHub's native stacked pull request feature has some limitations. If you need to make changes to commit `A`, you would have to manually update all the branches and pull requests, which can be time-consuming and error-prone. You cannot update only the `feature-A` branch without making other branches outdated.

## The Solution: Mergify-cli

Mergify-cli solves the problem of managing stacked pull requests by automating the entire process. It utilizes a technique similar to other code review tools like Gerrit to inject a unique identifier into the commit message. This identifier is added automatically via a git commit-msg hook. Here's an example of the injected ID:

```
Mergify-cli stack change-Id: I7074fdf5e24e2d4de721936260e4b962532c9735
```

These IDs allow Mergify-cli to track and manage the changes on your `feature` branch effectively. It assumes that your commit messages are well-written and uses them in the title and body of the pull requests.

Mergify-cli leverages the GitHub API to perform various tasks, keeping your local git repository clean. However, unlike Gerrit, Mergify-cli requires the branches to be in the `heads` namespace to open pull requests. Custom namespaces for hiding the git reference on the remote repository are not supported.

## Installation

You can install Mergify-cli using pip:

```bash
pip install mergify_cli
```

## Configuration

To use Mergify-cli for creating stacked pull requests in your repository, follow these steps:

1. Install the commit-msg hook by running the following command:

```bash
mrgfy --setup
```

2. Define your trunk branch, which serves as the base branch for your stacked pull requests. You can set it using the following command:

```bash
git config --add mergify-cli.stack-trunk origin/branch-name
```

Alternatively, you can set the trunk branch on the fly using the `--trunk` parameter.

3. Set up a GitHub OAuth token for Mergify-cli to access the GitHub API. It is recommended to use the `gh` ([gh client](https://cli.github.com/)) installed and authenticated. In this case, Mergify-cli will automatically retrieve the token using `gh auth token`. Alternatively, you can create a [personnal access token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens) with the necessary permissions to create branches and pull requests. Set the token as an environment variable `GITHUB_TOKEN` or provide it on the fly using the `--token` parameter.

## Usage

To create a stack of pull requests, follow these steps:

1. Create a branch and make your desired changes on that branch.
2. After making changes on your branch, including any necessary commit message modifications using `git rebase -i`, you can proceed to create your stack of pull requests.

3. To create the stack, simply run the following command:

```bash
mrgfy
```

Mergify-cli will automatically handle the creation of individual pull requests for each commit in your feature branch. This allows for a streamlined and efficient process of managing the changes and reviews associated with the stacked pull requests.

By using Mergify-cli, you no longer need to manually update branches and pull requests when making changes to earlier commits. The tool intelligently tracks and manages the commit index or SHA, ensuring that your stacked pull requests remain up-to-date and synchronized.

Remember that one pull request will be created for each commit in your feature branch, facilitating an organized and incremental review process.

Feel free to explore additional options and parameters available with the `mrgfy` command to customize the behavior of Mergify-cli based on your specific needs.

That's it! With Mergify-cli, you can automate the creation and management of stacked pull requests, saving time and reducing the chances of errors during the process.

If you have any questions or need further assistance, please refer to the documentation or reach out to the Mergify-cli community for support.

Thank you for using Mergify-cli to streamline your pull request workflow!