# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Minimal Python project scaffold managed with [uv](https://docs.astral.sh/uv/). Entry point is `main.py` (`python main.py` prints a greeting). No dependencies, no tests, no build step yet.

## Commands

Run from the project root with `uv` (the environment is pinned to Python 3.14 via `.python-version`):

- `uv run python main.py` — run the app (uv syncs/creates the `.venv` automatically)
- `uv sync` — install/sync dependencies from `pyproject.toml`
- `uv add <package>` — add a runtime dependency (updates `pyproject.toml` and lockfile)
- `uv add --dev <package>` — add a dev dependency (e.g. `pytest`, `ruff`)

There is no test or lint configuration currently. If adding tests/linting, prefer `pytest` and `ruff` and record the invocation here (e.g. `uv run pytest`, `uv run ruff check`).

## Architecture

Single-file program. New code should grow from `main.py` (or a package imported by it) and declare any external libraries in `pyproject.toml` via `uv add` rather than importing ad hoc.