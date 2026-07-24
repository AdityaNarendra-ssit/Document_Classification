# 1. This file is for tracking the To-do, improvements and features we need to add, and who is assigned to it.

*Last updated: 2026-07-24*

| Sl. No | Task | Description | Category | Assigned to | Status |
|--------|------|-------------|----------|-------------|--|
| 1 | Add docstrings and logging | Add detailed Google-style docstrings to every function/method and integrate `loguru` logging (console + rotating file, `LOG_LEVEL` env var). | Code quality / Observability | Claude |
| 2 | Create `PROJECT_STATUS.md` | Analyze the current codebase and document architecture, implemented modules, gaps, and next steps. | Documentation | Claude |
| 3 | Implement classifier module | Build `src/classifier.py` to call Claude Opus with an assembled prompt and return structured JSON: classification, confidence, rationale, citedPolicyRefs, citedNDARefs, entitiesDetected, assumptions, needsHumanReview. | Core feature | TBD |
| 4 | Implement context assembler | Build `src/context_assembler.py` to convert graph subgraphs into LLM prompts with system/context/document blocks, token budgeting, and prompt caching. | Core feature | TBD |
| 5 | Fix import/dependency hygiene | Remove duplicate imports in `src/extraction.py` and add `python-dotenv` to `pyproject.toml` explicitly. | Code quality | TBD |
| 6 | Versioned policy store | Store raw policy markdown, versions, and effective dates; diff policies on update to emit change events. | Core feature | TBD |
| 7 | Audit log and re-evaluation engine | Record every classification with cited policy versions and model version; on policy/NDA/partner changes, compute affected documents and re-classify. | Core feature | TBD |
| 8 | Add tests and linting | Add `pytest` and `ruff` as dev dependencies; write unit tests for ingestion, graph store, and MCP tools. | Engineering hygiene | TBD |
| 9 | Populate `README.md` | Document project purpose, setup (`uv`), usage (`main.py`, Streamlit, MCP), and architecture overview. | Documentation | TBD |
| 10 | Capture the structure in original document | Currently in document text extraction, the document's heading, subheadings etc are not captured properly. THis is a lossy process. Improve the text extraction where the structure of the document is respected in the markdown format as well. | Document extraction | Aditya|
| 11 | Fix lossy truncation | The truncation in the extract_semantic_context function is lossy. If the source markdown is larger than 120000 tokens, then the rest are discarded. Fix this such that the full document is processed. | Semantic extraction | Priya |
| 12 | Max token as env variable | Create a .env file and populate it with the configuration for the Anthropic client, such as the model, the max token count, and temperature. | Code quality | Aditya |
| 13 | Separate prompt.py file | Create a separate prompt.py file where all the prompts used in the project are kept. | Code quality | Priya |
