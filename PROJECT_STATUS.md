# Project Status: Policy Knowledge Graph (Graph RAG Classification)

**Generated:** 2026-07-24  
**Repository branch:** `master`  
**Python version:** 3.14 (pinned via `.python-version`)  
**Package manager:** `uv`

---

## 1. Project Goal

Build an automated document-sensitivity classifier using a **Graph RAG** architecture. The system reads company policies (classification taxonomy, NDAs, partner matrices, data-handling rules), parses them into a knowledge graph, and uses Claude to classify documents as **Restricted / Confidential / Internal / Public** based on graph-retrieved context.

The long-term target is an event-driven re-evaluation pipeline: when a policy or NDA changes, only affected documents are re-classified.

---

## 2. High-Level Architecture

| Layer | Implemented In | Status |
|-------|----------------|--------|
| Document ingestion (PDF/DOCX/HTML/TXT → Markdown) | `src/ingestion.py` | ✅ Working |
| Semantic extraction (Markdown → structured policy entities) | `src/extraction.py` | ✅ Working |
| Knowledge graph store (in-memory `networkx` + RDF persistence) | `src/graph_store.py` | ✅ Working |
| MCP server exposing graph tools | `src/mcp_server.py` | ✅ Working |
| Streamlit frontend / pipeline UI | `frontend/app.py` | ✅ Working |
| Context assembler (Graph → LLM prompt) | `src/context_assembler.py` | ⚠️ Empty stub |
| Classifier (LLM call with structured output) | `src/classifier.py` | ⚠️ Empty stub |
| Standalone knowledge graph module | `src/knowledge_graph.py` | ⚠️ Empty stub |
| Audit log / re-evaluation engine | Not created | ❌ Not implemented |
| Versioned policy store | Not created | ❌ Not implemented |

---

## 3. File Inventory

### Implemented Python modules

- **`main.py`** (39 lines) — CLI entry point. Supports two commands:
  - `serve` (default) — runs the MCP server.
  - `build` — one-shot pipeline: `file → markdown → semantic context → graph upsert`.

- **`src/ingestion.py`** (52 lines) — Converts documents to markdown.
  - Handles `.pdf` (via `pypdf`), `.docx` (via `python-docx`), `.html`/`.htm` (via `markdownify`), and plain text.
  - Falls back to treating input as raw text/markdown if the path does not exist.

- **`src/extraction.py`** (135 lines) — Calls the Anthropic API to extract structured policy context.
  - Uses `claude-sonnet-4-6` by default.
  - Prompt asks for: title, policy type, effective date, rules, data categories, partners, NDA contracts, and relationships.
  - Returns a Pydantic `SemanticContext` model.
  - **Known issue:** duplicate imports for `os`, `Anthropic`, and `dotenv` (lines 3–11).

- **`src/graph_store.py`** (195 lines) — `KnowledgeGraph` class backed by `networkx.DiGraph` and persisted as RDF/Turtle (`data/graph.ttl`).
  - Implements the four Graph RAG helper functions:
    - `F1 read_graph` — breadth-first traversal from seed entities.
    - `F2 reduce_edges` — keep only selected edge predicates.
    - `F3 eliminate_nodes` — drop low-degree nodes.
    - `F4 augment_graph` — annotate nodes with hop-distance relevance scores.
  - `upsert_policy` — adds `Policy`, `PolicyRule`, `DataCategory`, `Partner`, `NDAContract`, and `ClassificationLabel` nodes plus edges.
  - Loads existing graph automatically on init.

- **`src/mcp_server.py`** (96 lines) — FastMCP server named `policy-knowledge-graph`.
  - Exposes tools: `convert_to_markdown`, `extract_semantic_context_tool`, `upsert_policy_graph`, `read_graph`, `reduce_edges`, `eliminate_nodes`, `augment_graph`.

- **`frontend/app.py`** (226 lines) — Streamlit multi-page UI.
  - Upload or paste a policy, extract semantic context, add to a session-scoped knowledge graph.
  - Lists all loaded policies.
  - Visualizes the combined graph with `matplotlib` + `networkx`.
  - Provides interactive controls for F1–F4 graph operations.

### Empty / stub files

| File | Lines | Note |
|------|-------|------|
| `src/__init__.py` | 0 | Empty package init. |
| `src/classifier.py` | 0 | Stub for the Claude Opus classification engine. |
| `src/context_assembler.py` | 0 | Stub for Graph RAG prompt assembly. |
| `src/knowledge_graph.py` | 0 | Unused stub; graph logic lives in `graph_store.py`. |
| `README.md` | 1 | Empty. |

### Documentation & assets

- `CLAUDE.md` — Project instructions for Claude Code (uv commands, architecture notes).
- `docs/design.md` — Full design document describing the Graph RAG pipeline, re-evaluation engine, security/compliance considerations, and future module breakdown.
- `docs/Northwind_Data_Classification_Policy.pdf` — Sample policy document.
- `docs/Solstice_Partner_NDA_Policy.pdf` — Sample NDA document.
- `diagram/Workflow_diagram_v1.png` — Architecture diagram.
- `docs/claude_plans_vs_api_billing.png` — Reference image.

---

## 4. Dependencies

Declared in `pyproject.toml`:

```toml
dependencies = [
    "anthropic>=0.117.0",
    "markdownify>=1.2.3",
    "matplotlib>=3.11.1",
    "mcp>=1.28.1",
    "networkx>=3.6.1",
    "pydantic>=2.13.4",
    "pypdf>=6.14.2",
    "python-docx>=1.2.0",
    "rdflib>=7.6.0",
    "streamlit>=1.59.2",
]
```

**Note:** `python-dotenv` is imported in `src/extraction.py` but is **not declared** in `pyproject.toml`. It may be present as a transitive dependency, but it should be added explicitly with `uv add python-dotenv` for correctness.

---

## 5. How to Run

Run the MCP server:

```bash
uv run python main.py
```

Run a one-shot policy build:

```bash
uv run python main.py build --file docs/Northwind_Data_Classification_Policy.pdf --id POL-001 --version v1
```

Run the Streamlit frontend:

```bash
uv run streamlit run frontend/app.py
```

---

## 6. Current Strengths

- Clean separation between ingestion, extraction, graph store, and MCP/frontend layers.
- Graph store supports RDF persistence and F1–F4 Graph RAG operations.
- MCP server exposes the entire pipeline as tools.
- Streamlit UI makes the multi-policy pipeline interactive and visual.
- Pydantic models enforce structured extraction output.

---

## 7. Gaps & Next Steps

1. **Classifier implementation** (`src/classifier.py`)
   - Build the Claude Opus call that accepts an assembled prompt and returns structured JSON: `classification`, `confidence`, `rationale`, `citedPolicyRefs`, `citedNDARefs`, `entitiesDetected`, `assumptions`, `needsHumanReview`.

2. **Context assembler** (`src/context_assembler.py`)
   - Convert the graph subgraph into a Claude prompt (system block + context block + document block).
   - Add token-budget management and prompt-caching support.

3. **Fix import / dependency issues**
   - Remove duplicate imports in `src/extraction.py`.
   - Add `python-dotenv` to `pyproject.toml` or remove the import.

4. **Versioned policy store**
   - Store raw policy markdown, versions, and effective dates.
   - Diff policies on update to emit change events.

5. **Audit log & re-evaluation engine**
   - Record every classification with cited policy versions and model version.
   - On policy/NDA/partner changes, compute the affected document set and re-classify.

6. **Tests & linting**
   - No tests or lint configuration exist.
   - Recommended: add `pytest` and `ruff` as dev dependencies.

7. **README**
   - `README.md` is empty; should document the project, setup, and usage.

---

## 8. Quick Health Check

- All Python files compile without syntax errors.
- `uv run python main.py --help` works and shows the expected CLI.
- The graph store auto-loads from `data/graph.ttl` if present.
- Anthropic API key is required at runtime for semantic extraction (`ANTHROPIC_API_KEY`).

---

## 9. Summary

The project has a functioning **ingestion → extraction → graph store → MCP/frontend** pipeline for loading and visualizing multiple policies as a knowledge graph. The core Graph RAG graph operations are implemented, but the **classifier** and **context assembler** that actually use the graph to classify documents are still empty stubs. The next milestone is to implement those two modules and wire them into `main.py`/MCP/frontend.
