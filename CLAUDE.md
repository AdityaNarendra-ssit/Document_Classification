# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A Python prototype for an automated document-sensitivity classifier using a **Graph RAG** architecture. The system ingests company policies (classification taxonomy, NDAs, partner matrices, data-handling rules), extracts structured entities with Claude, stores them in an in-memory `networkx` knowledge graph persisted as RDF, and exposes the graph via an MCP server and a Streamlit UI.

The long-term target is event-driven re-evaluation: when a policy or NDA changes, only the documents that cited it are re-classified. See `docs/design.md` for the full architecture.

## Commands

Run from the project root with `uv` (Python 3.14 is pinned via `.python-version`):

- `uv sync` — install/sync dependencies from `pyproject.toml`
- `uv run python main.py` — run the MCP server
- `uv run python main.py build --file <path> --id <policy-id> --version <version>` — run the one-shot ingestion/extraction/upsert pipeline
- `uv run streamlit run frontend/app.py` — start the Streamlit UI
- `uv run python -m py_compile main.py src/*.py frontend/app.py` — quick syntax check across the codebase

Use `uv add <package>` for runtime dependencies and `uv add --dev <package>` for dev dependencies. There are no tests or lint configuration yet; prefer `pytest` and `ruff` when adding them.

## Environment

- `ANTHROPIC_API_KEY` is required at runtime for `src/extraction.py` to call the Anthropic API.
- `LOG_LEVEL` (default `INFO`) controls `loguru` output. Logs go to stderr and to a rotating file at `logs/app.log` (5 MB rotation, 7 day retention), configured in `src/__init__.py`.

## Architecture

The codebase is organized as a pipeline plus interfaces:

- `src/ingestion.py` — converts PDF, DOCX, HTML, or plain text into markdown.
- `src/extraction.py` — calls Claude to parse policy markdown into structured entities (`SemanticContext`) using Pydantic models.
- `src/graph_store.py` — `KnowledgeGraph` class backed by `networkx.DiGraph` and persisted as RDF/Turtle (`data/graph.ttl`). Implements the four Graph RAG operations: `read_graph`, `reduce_edges`, `eliminate_nodes`, and `augment_graph`.
- `src/mcp_server.py` — FastMCP server that exposes ingestion, extraction, upsert, and the four graph operations as tools.
- `frontend/app.py` — Streamlit UI for uploading policies, extracting context, building the combined graph, visualizing it, and applying the F1–F4 graph controls.
- `main.py` — CLI entry point: `serve` (default, runs MCP server) or `build` (one-shot pipeline).

`src/classifier.py`, `src/context_assembler.py`, and `src/knowledge_graph.py` are currently stubs reserved for the classification engine, Graph RAG prompt assembler, and future graph store refactor respectively.

## Development notes

- New code should grow from `main.py` or from the `src` package, and dependencies must be declared in `pyproject.toml` via `uv add` rather than imported ad hoc.
- `python-dotenv` is imported in `src/extraction.py` but is not declared in `pyproject.toml` (likely present transitively). Add it explicitly if it remains a direct import.
- `src/extraction.py` contains duplicate imports (`os`, `Anthropic`, `dotenv`) that need cleaning up.
- `README.md` and `Tasks.md` are currently the best places to track documentation and open work.
