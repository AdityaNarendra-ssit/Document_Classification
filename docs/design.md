# Design: Automated Document Classification with Claude Opus (Graph RAG)

> Companion to the Excalidraw workflow diagram. Read this alongside the diagram — each section
> maps to a labeled box/arrow.

## 1. Overview & Goals

A system that automatically parses company documents and assigns a **sensitivity classification**
— **Restricted / Confidential / Internal / Public** — based on company policies, partner
relationships, NDAs, and business context. Claude Opus is the classification LLM.

Two requirements drive the architecture:

1. **Multiple policy files** govern classification (a classification taxonomy, an NDA registry,
   a partner-relationship matrix, data-handling rules, regulatory rules). They vary in size and
   change over time, so they cannot all be dumped into the context window. They must be stored,
   versioned, and **selectively surfaced** per document.
2. **Automatic re-evaluation**: when a policy is added/updated/retired, an NDA expires or is
   signed, or a partner relationship changes, the system must re-classify the **affected**
   documents — not the whole corpus.

The chosen context strategy is **Graph RAG**: policies, partners, NDAs, data categories, and
classification labels are modeled as a knowledge graph; retrieval traverses the graph from
entities found in the document to pull the relevant subgraph (rules + relationships) plus linked
policy text into Claude's prompt.

---

## 2. Components

### 2.1 Document Sources & Ingestion  *(diagram: blue lane, left)*
- **Sources**: SharePoint, Google Drive, S3, file shares.
- **Ingestion worker**: detects new + modified documents via webhooks/events or polling.
- **Preprocessing**: text extraction (PDF/DOCX/email), structure preservation (headings,
  tables), section chunking for large documents, metadata capture (author, date, source system,
  intended-audience markers). Entities detected in text (partner names, project codes, data
  categories) are tagged so they can be linked into the graph during context assembly.

### 2.2 Policy Knowledge Base  *(diagram: purple "Knowledge Layer")*
- **Versioned policy store**: each policy file is stored with
  `{ id, type, version, effective_date, scope, raw_text, structured_rules }`.
  Git-backed or a versioned object store so every change is auditable and diffable.
- **Policy types**: Classification Taxonomy, NDA Registry, Partner Relationship Matrix,
  Data-Handling Rules, Regulatory/Compliance Rules.
- On ingest or update, each policy is **parsed into structured entities + rules** and upserted
  into the knowledge graph (§2.3).

### 2.3 Knowledge Graph  *(diagram: central purple node)*
The "Graph" in Graph RAG.

**Nodes**
- `Policy` (versioned), `PolicyRule`, `DataCategory`, `Partner`, `NDAContract`,
  `ClassificationLabel`, `Document`

**Edges**
- `Policy` —*governs*→ `DataCategory`
- `PolicyRule` —*mapsTo*→ `ClassificationLabel`
- `NDAContract` —*covers*→ `Partner` —*forData*→ `DataCategory`
- `Partner` —*relationshipTier*→ tier
- `Document` —*mentions*→ `Partner` / `DataCategory`
- `Document` —*classifiedAs (versioned)*→ `ClassificationLabel`

**Store**: a labeled property graph (Neo4j in production; `networkx` in memory for a prototype).
Embeddings are attached to `PolicyRule` nodes to enable **hybrid retrieval** — graph traversal
plus vector similarity on rule text.

### 2.4 Context Assembly (Graph RAG → Claude's context window)  *(diagram: green "Context Assembler")*
For each document, the assembler builds the prompt in four steps:

1. **Entity extraction** from the document → seed nodes (partner names, data categories,
   project codes detected in the text). A cheap model (Haiku) can do this fast.
2. **Graph traversal** from the seed nodes: pull the subgraph of governing policies, matching
   NDA contracts, the partner's relationship tier, and applicable data-handling rules.
3. **Hybrid retrieval**: vector-search `PolicyRule` nodes semantically similar to the document,
   union with the graph-traversed rules; dedupe and rank.
4. **Assemble the prompt**:
   - *System block* — classification taxonomy, output schema, reasoning instructions. Stable
     across all documents → **prompt-cached** (Anthropic prompt caching) to cut cost and latency.
   - *Context block* — retrieved policy rules (each with its **id + version**), NDA coverage for
     mentioned partners, partner tiers, applicable data categories. Structured, not prose.
   - *Document block* — full text if it fits the window; otherwise section-level chunks with a
     hierarchical roll-up (classify sections, then aggregate to a document label).

**Token-budget management**: rank retrieved rules by a graph-relevance score; if over budget,
drop or summarize the lowest-ranked first. Taxonomy definitions and directly-cited NDAs are
never dropped.

### 2.5 Claude Opus Classification Engine  *(diagram: green "Claude Opus")*
- Model: **Claude Opus** (main LLM). Optional Haiku for triage/entity-extraction pre-pass.
- Input: the assembled prompt.
- Output: **structured JSON** (forced via tool/typed schema):
  ```json
  {
    "classification": "Restricted | Confidential | Internal | Public",
    "confidence": 0.0–1.0,
    "rationale": "...",
    "citedPolicyRefs": [{"id": "P-007", "version": "v3"}],
    "citedNDARefs": ["NDA-ACME-2024"],
    "entitiesDetected": {"partners": ["Acme"], "dataCategories": ["customerPII"]},
    "assumptions": ["..."],
    "needsHumanReview": false
  }
  ```
- The **`citedPolicyRefs` with versions** are the linchpin of re-evaluation: they let the system
  later find every document whose label depended on a given policy version.

### 2.6 Classification Store & Audit Log  *(diagram: teal, right)*
Each result is stored with:
`docId, classification, prevClassification, rationale, citedPolicyRefs + versions,
citedNDARefs, modelVersion, timestamp, triggerChangeId`.

This gives **traceability** (which policy version drove this label, when, by which model) and
is the index that drives impact analysis (§2.7).

### 2.7 Re-Evaluation Engine  *(diagram: amber "Re-Evaluation Loop", bottom)*
**Triggers** (event-driven + periodic):
- Policy file added / updated / retired.
- NDA expiry / renewal / new NDA signed.
- Partner relationship tier change.
- Periodic scheduled re-review.

**Flow on a trigger**:
1. **Change diff** — compute which `Policy` / `PolicyRule` / `NDAContract` / `Partner` nodes
   changed in the graph.
2. **Impact analysis** — query the audit log for every document whose `citedPolicyRefs` /
   `citedNDARefs` touch a changed node → the **affected set**. This is surgical: only these
   documents are re-run, not the whole corpus.
3. **Re-classify** the affected set through the same pipeline (§2.4–2.5) with the updated
   graph/context.
4. **Delta detection** — compare new vs. old classification.
5. **Disposition**:
   - Unchanged → update the audit record (re-validated against the new policy version).
   - Changed → flag for human review, record before/after, notify the data owner.
6. Every re-evaluation is logged with the triggering `changeId` for compliance.

### 2.8 Policy / KB Update Flow  *(diagram: dashed amber arrow, Knowledge Graph → Change Event)*
When a new or updated policy file arrives:
1. Version bump in the policy store; diff against the prior version.
2. Parse into structured rules; **upsert** graph nodes/edges, preserving version history.
3. Re-embed the changed `PolicyRule` nodes (hybrid index).
4. Emit a change event → the Re-Evaluation Engine (§2.7).

---

## 3. Why Graph RAG (not plain vector RAG)

The core question a classification ask is relational: *"which rules apply to **this partner** for
**this data category** under **these NDAs**?"* Plain vector RAG retrieves semantically similar
policy text, which often returns rules that look alike but apply to different partners/data
categories — plausible but contextually wrong.

A knowledge graph makes the relationships first-class:
- `NDAContract —covers→ Partner —forData→ DataCategory` is traversed directly.
- `Policy —governs→ DataCategory —mapsTo→ Label` gives the applicable label without ambiguity.
- Hybrid retrieval (graph traversal ∪ vector similarity) catches both explicit relationship
  matches and semantically related rules the graph didn't encode.

Net: higher precision on the context block, fewer false classifications, and citations that are
traceable to specific graph nodes — which is exactly what makes impact analysis possible.

---

## 4. How Claude "understands" a document

- **Extraction + structure**: text extraction preserves headings, tables, and sections so
  Claude sees structure, not a flat blob.
- **Entity tagging**: partner names, project codes, and data categories detected during
  preprocessing become seed nodes for graph traversal — Claude's context is anchored to what
  the document actually references.
- **Chunking for large docs**: section-level classification with a hierarchical roll-up to a
  single document label; the most restrictive section wins by default (overridable by policy).
- **Structured output**: forces a label, a rationale, and citations — no free-form prose to
  parse, and citations feed the audit log.

---

## 5. Data Model Sketch

**Graph nodes/edges** — see §2.3.

**Audit record**
```
{
  docId, classification, prevClassification, rationale,
  citedPolicyRefs: [{id, version}], citedNDARefs: [id],
  modelVersion, timestamp, triggerChangeId
}
```

**Change event**
```
{ changeId, type: "policy|nda|partner", nodeId, fromVersion, toVersion, timestamp }
```

---

## 6. Security & Compliance Notes

- **Auditability**: every classification records the exact policy versions and model version
  used; re-evaluations record the triggering change. Full chain of custody.
- **Human-in-the-loop on upgrades**: a re-evaluation that *changes* a label is never auto-applied
  silently — it is flagged for human review and the data owner is notified.
- **Least-privilege**: the ingestion worker and Claude call run with scoped credentials; policy
  files and the graph store are read-only to the classification service.
- **No sensitive content leaves the trust boundary**: documents and policies are processed in the
  customer's environment; only the assembled prompt is sent to Claude (and prompt caching keeps
  the stable prefix on Anthropic's side without re-sending raw policies each call).

---

## 7. Future Implementation Notes

Per `CLAUDE.md`, new code grows from `main.py` (or a package it imports), and external libraries
are declared via `uv add`. A future prototype would split into modules:

- `main.py` — orchestration entry point
- `ingestion.py` — document source connectors + preprocessing
- `policy_store.py` — versioned policy storage + parser
- `knowledge_graph.py` — graph upsert + traversal (start with `networkx`, move to Neo4j)
- `context_assembler.py` — Graph RAG assembly + prompt caching + token budgeting
- `classifier.py` — Claude Opus call with forced structured output (Anthropic SDK)
- `audit_log.py` — classification/audit storage
- `reevaluator.py` — change diff, impact analysis, re-classify, delta detection

Likely `uv add` dependencies: `anthropic`, `networkx`, an embedding lib, document parsers
(`pypdf`/`python-docx`), and a graph store client when moving beyond the in-memory prototype.


---

How will knowledge graph be accessed - tool or skill?

Knowledge graph - networkx

function to navigate graph and give prompt to the LLM
This function is Classify tool

Classify tool should be part of MCP

F1 - read graph
F2- reduce edges
F3- eliminate elements we dont want to pull
F4- Augment/calculation


MCP + LLM

Breakdown to Semantic context -> convert to Markdown -> RDF -> RDF knowledge graph -> Graphical search -> Connect to MCP server + tool
