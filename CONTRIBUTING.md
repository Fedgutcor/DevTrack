# Contributing to DevTrack

Thanks for your interest in contributing. DevTrack is a local-first tool — we keep it simple and dependency-light.

## Local setup

**Requirements:** Python 3.11+, [uv](https://docs.astral.sh/uv/)

```bash
git clone https://github.com/Fedgutcor/DevTrack
cd devtrack
uv sync --extra dev
```

## Running the server

```bash
uv run devtrack-server
# Dashboard at http://localhost:17321
```

## Running tests

```bash
uv run pytest
```

## Linting

```bash
uv run ruff check .
```

## How to contribute

1. Fork the repo
2. Create a branch: `git checkout -b feat/my-feature`
3. Make your changes and add tests if applicable
4. Run `ruff check .` and `pytest` — both must pass
5. Open a Pull Request with a clear description

## Reporting bugs

Open an issue at https://github.com/Fedgutcor/DevTrack/issues with:
- Your OS and Python version
- Steps to reproduce
- Expected vs actual behavior

## Design philosophy

- **local-first**: no cloud, no telemetry, data stays on your machine
- **privacy-first**: no accounts, no API keys required
- **simple install**: `pip install devtrack` must work on a fresh Python 3.11+ env
- **no overengineering**: solve the problem, don't abstract for hypothetical future needs
