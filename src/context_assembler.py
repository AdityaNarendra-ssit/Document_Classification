"""
Context Assembler (design.md, section 2.4).

Turns a raw document into the three-block prompt that classifier.py will send
to Claude Opus:
  - system block   : taxonomy + output schema (static -> cacheable later)
  - context block   : the traversed subgraph from knowledge_graph.py
  - document block  : the raw document text

Entity extraction is stubbed as keyword matching for now (design.md says this
should eventually be a cheap Haiku call — swapping that in later shouldn't
require changing anything else in this file).
"""

from knowledge_graph import build_graph, find_seed_nodes, traverse

# Known names to match against document text. In the real system this list
# would come from the graph itself (all Partner / DataCategory node names),
# not be hardcoded — fine for this slice since the graph is tiny.
KNOWN_PARTNERS = ["Acme"]
KNOWN_DATA_CATEGORIES = ["customerPII", "internalOps"]

SYSTEM_BLOCK = """You are a document sensitivity classifier.
Classify the document into exactly one of: Restricted, Confidential, Internal, Public.
Base your decision only on the policy rules, NDA coverage, and partner tiers provided
in the context block. Cite the specific rule and NDA ids that drove your decision.
Respond with structured JSON matching the required schema."""


def extract_entities(document_text: str) -> dict:
    """Stub entity extraction via keyword matching.

    Design.md's real version (§2.4 step 1) uses a cheap model (Haiku) for
    this. Swapping that in later means replacing the body of this function —
    the return shape ({"partners": [...], "dataCategories": [...]}) stays
    the same, so nothing downstream needs to change.
    """
    found_partners = [p for p in KNOWN_PARTNERS if p.lower() in document_text.lower()]
    found_categories = [c for c in KNOWN_DATA_CATEGORIES if c.lower() in document_text.lower()]
    return {"partners": found_partners, "dataCategories": found_categories}


def assemble_prompt(document_text: str) -> dict:
    """Build the full three-block prompt for a given document.

    Returns a dict of blocks rather than a single string, so classifier.py
    can decide how to lay them out in the actual API call (and so we can
    prompt-cache the system block independently later).
    """
    graph = build_graph()
    entities = extract_entities(document_text)
    seed_nodes = find_seed_nodes(graph, entities)
    context = traverse(graph, seed_nodes)

    return {
        "system_block": SYSTEM_BLOCK,
        "context_block": context,
        "document_block": document_text,
        "entities_detected": entities,  # kept for debugging + later audit logging
    }


if __name__ == "__main__":
    sample_doc = (
        "Quarterly data-sharing summary for Acme covering customerPII "
        "exports used in the joint analytics project."
    )
    prompt = assemble_prompt(sample_doc)

    print("entities_detected:", prompt["entities_detected"])
    print("\ncontext_block:")
    for key, items in prompt["context_block"].items():
        print(f"  {key}: {items}")
    print("\ndocument_block:", prompt["document_block"])