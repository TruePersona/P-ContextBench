# Contributing to PERSONA-Bench

Thank you for your interest in contributing to PERSONA-Bench! This document provides guidelines and instructions for contributing.

## How to Contribute

### Reporting Issues

- Use [GitHub Issues](https://github.com/zhadyz/PERSONA-Bench/issues) to report bugs or request features.
- Check existing issues before opening a new one to avoid duplicates.
- Use the provided issue templates (bug report, feature request).

### Submitting Pull Requests

1. Fork the repository and create a new branch from `main`.
2. Make your changes, ensuring they follow the project's code style.
3. Write clear, descriptive commit messages.
4. Open a pull request against `main` using the PR template.
5. Respond to review feedback promptly.

## Code Style

We use [Ruff](https://docs.astral.sh/ruff/) for linting and formatting Python code.

```bash
# Install ruff
pip install ruff

# Check for linting issues
ruff check .

# Auto-fix linting issues
ruff check --fix .

# Format code
ruff format .
```

The project's Ruff configuration is in `pyproject.toml`. Please ensure your code passes all checks before submitting a PR.

## Developer Certificate of Origin (DCO)

This project requires all contributors to sign off on their commits in accordance with the [Developer Certificate of Origin (DCO)](DCO). The DCO is a lightweight mechanism to certify that you wrote or have the right to submit the code you are contributing.

### How to Sign Off

Add a `Signed-off-by` line to every commit message:

```
Signed-off-by: Your Name <your.email@example.com>
```

The easiest way to do this is to use the `-s` flag when committing:

```bash
git commit -s -m "Your commit message"
```

### Configuring VS Code for Automatic Sign-Off

If you use VS Code, you can enable automatic sign-off for all commits:

1. Open VS Code Settings (`Ctrl+,` or `Cmd+,`).
2. Search for `git.alwaysSignOff`.
3. Check the box to enable it.

Or add this to your `settings.json`:

```json
{
  "git.alwaysSignOff": true
}
```

### What the DCO Means

By signing off on a commit, you certify that:

- The contribution was created in whole or in part by you, and you have the right to submit it under the project's open-source license; **or**
- The contribution is based upon previous work that, to the best of your knowledge, is covered under an appropriate open-source license and you have the right to submit that work with modifications; **or**
- The contribution was provided directly to you by some other person who certified (a) or (b), and you have not modified it.

See the full [DCO text](DCO) for details.

## License

By contributing to PERSONA-Bench, you agree that your contributions will be licensed under the [Apache 2.0 License](LICENSE).
