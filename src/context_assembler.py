"""Stub for the Graph RAG context assembler.

This module is reserved for building the LLM prompt from a graph subgraph.
In the full implementation it will:

    1. Extract seed entities from the target document.
    2. Traverse the knowledge graph from those seeds.
    3. Optionally hybridize with vector similarity on ``PolicyRule`` nodes.
    4. Assemble a system block, a structured context block (rules, NDAs,
       partner tiers, data categories), and the document block.
    5. Manage token budgets and prompt caching.

See ``docs/design.md`` section 2.4 for the target behavior.
"""
"""
Context Assembler.

Takes a document's markdown text, finds which known graph entities (partners,
data categories) it mentions, retrieves the relevant subgraph via
graph_store.py's four operations (read_graph -> reduce_edges -> eliminate_nodes
-> augment_graph), and assembles the three-block prompt classifier.py sends
to Claude: system block, context block, document block.
"""

from src.graph_store import KnowledgeGraph

SYSTEM_PROMPT = """You are a document sensitivity classifier.
Classify the document into exactly one of: Restricted, Confidential, Internal, Public.
Base your decision only on the policies, rules, NDAs, and partner relationships
provided in the context block below — do not assume policy content that isn't
present there. Cite the specific policy and NDA ids that drove your decision."""

# Relationship types worth keeping when narrowing a subgraph for classification —
# these are the ones that actually carry classification-relevant meaning.
# (design.md / graph_store.py's F2 "reduce_edges" step)
RELEVANT_EDGE_TYPES = ["governs", "hasRule", "appliesTo", "mapsTo", "covers", "forData"]


def find_seed_entities(kg: KnowledgeGraph, document_text: str) -> list[str]:
    """Match known graph entities (Partner, DataCategory nodes) against the
    document's text. Simple substring matching for now — a cheap Haiku call
    could replace this later without changing what this function returns.
    """
    text_lower = document_text.lower()
    seeds = []
    for node_id, data in kg.g.nodes(data=True):
        label = data.get("label", "")
        node_type = data.get("type", "")
        if node_type in {"Partner", "DataCategory"} and label and label.lower() in text_lower:
            seeds.append(label)
    return seeds


def _subgraph_to_context_block(subgraph) -> dict:
    """Shape a networkx subgraph into the grouped, structured dict the prompt
    needs — policies / rules / labels / ndas / partners, each with its data —
    rather than handing Claude a raw node/edge dump.
    """
    grouped = {"policies": [], "rules": [], "labels": [], "ndas": [], "partners": []}
    type_to_key = {
        "Policy": "policies",
        "PolicyRule": "rules",
        "ClassificationLabel": "labels",
        "NDAContract": "ndas",
        "Partner": "partners",
    }
    for node_id, data in subgraph.nodes(data=True):
        key = type_to_key.get(data.get("type"))
        if key is not None:
            grouped[key].append({"id": data.get("label", node_id), **{
                k: v for k, v in data.items() if k not in {"type", "label"}
            }})
    return grouped


def assemble_prompt(kg: KnowledgeGraph, document_text: str, depth: int = 2) -> dict:
    """Build the full three-block prompt for a given document.

    Returns {"system_block", "context_block", "document_block", "seed_entities"} —
    the last one kept for debugging/audit logging, mirroring what design.md's
    audit record expects to capture (entities detected).
    """
    seeds = find_seed_entities(kg, document_text)

    if not seeds:
        # No known partners/categories mentioned — hand back an empty context
        # rather than traversing from nothing; classifier.py should treat this
        # as "insufficient context, flag for human review" rather than guess.
        return {
            "system_block": SYSTEM_PROMPT,
            "context_block": {"policies": [], "rules": [], "labels": [], "ndas": [], "partners": []},
            "document_block": document_text,
            "seed_entities": [],
        }

    subgraph = kg.read_graph(seeds, depth=depth)
    subgraph = kg.reduce_edges(subgraph, RELEVANT_EDGE_TYPES)
    subgraph = kg.eliminate_nodes(subgraph, min_degree=1)
    subgraph = kg.augment_graph(subgraph, seeds, scoring="hop_distance")

    context_block = _subgraph_to_context_block(subgraph)

    return {
        "system_block": SYSTEM_PROMPT,
        "context_block": context_block,
        "document_block": document_text,
        "seed_entities": seeds,
    }


if __name__ == "__main__":
    from src.extraction import SemanticContext

    kg = KnowledgeGraph("data/demo_context_assembler.ttl")
    ctx = SemanticContext(
        title="Demo Policy",
        rules=[{
            "rule_id": "rule-pii",
            "text": "Customer PII is Restricted unless covered by an active NDA.",
            "governs_data_categories": ["customerPII"],
            "maps_to_label": "Restricted",
        }],
        data_categories=["customerPII"],
        partners=["Acme"],
        nda_contracts=[{"contract_id": "NDA-ACME-2024", "partner": "Acme", "data_categories": ["customerPII"]}],
    )
    kg.upsert_policy(ctx, "POL-DEMO", "v1")

    sample_doc = (
        "Quarterly data-sharing summary for Acme covering customerPII "
        "exports used in the joint analytics project."
    )
    prompt = assemble_prompt(kg, sample_doc)
    print("seed_entities:", prompt["seed_entities"])
    for key, items in prompt["context_block"].items():
        print(f"{key}: {items}")