"""
Knowledge graph for document classification (design.md, section 2.3).

This is a deliberately minimal, in-memory prototype:
- Nodes/edges are hand-seeded (no policy parser yet — that's policy_store.py, later).
- One traversal function: given entities mentioned in a document, return the
  relevant subgraph (policies, NDA coverage, partner tier, rules).

Node types: Policy, PolicyRule, DataCategory, Partner, NDAContract, ClassificationLabel
Edge types: governs, mapsTo, covers, forData, relationshipTier
"""

import networkx as nx


def build_graph() -> nx.DiGraph:
    """Build the seed knowledge graph.

    Small, hand-written dataset just big enough to exercise traversal:
    - 1 policy with 2 rules
    - 1 partner with an NDA
    - 2 data categories
    """
    g = nx.DiGraph()

    # --- Policy & rules -----------------------------------------------
    g.add_node("policy:data-handling-v1", type="Policy", version="v1")
    g.add_node("rule:pii-restricted", type="PolicyRule", text="Customer PII is Restricted unless covered by an active NDA.")
    g.add_node("rule:internal-default", type="PolicyRule", text="Internal business data defaults to Internal classification.")

    g.add_edge("policy:data-handling-v1", "rule:pii-restricted", relation="hasRule")
    g.add_edge("policy:data-handling-v1", "rule:internal-default", relation="hasRule")

    # --- Data categories -------------------------------------------------
    g.add_node("data:customerPII", type="DataCategory")
    g.add_node("data:internalOps", type="DataCategory")

    g.add_edge("policy:data-handling-v1", "data:customerPII", relation="governs")
    g.add_edge("policy:data-handling-v1", "data:internalOps", relation="governs")
    g.add_edge("rule:pii-restricted", "data:customerPII", relation="appliesTo")
    g.add_edge("rule:internal-default", "data:internalOps", relation="appliesTo")

    # --- Classification labels -------------------------------------------
    g.add_node("label:Restricted", type="ClassificationLabel")
    g.add_node("label:Internal", type="ClassificationLabel")

    g.add_edge("rule:pii-restricted", "label:Restricted", relation="mapsTo")
    g.add_edge("rule:internal-default", "label:Internal", relation="mapsTo")

    # --- Partner & NDA -----------------------------------------------------
    g.add_node("partner:Acme", type="Partner", tier="strategic")
    g.add_node("nda:NDA-ACME-2024", type="NDAContract", status="active")

    g.add_edge("nda:NDA-ACME-2024", "partner:Acme", relation="covers")
    g.add_edge("partner:Acme", "data:customerPII", relation="forData")

    return g


def find_seed_nodes(graph: nx.DiGraph, entities: dict) -> list[str]:
    """Match extracted entities (from a document) to node ids in the graph.

    `entities` looks like: {"partners": ["Acme"], "dataCategories": ["customerPII"]}
    This is a stand-in for the entity-extraction step in context_assembler.py —
    here we just do direct name matching against seeded nodes.
    """
    seeds = []
    for partner in entities.get("partners", []):
        node_id = f"partner:{partner}"
        if graph.has_node(node_id):
            seeds.append(node_id)
    for category in entities.get("dataCategories", []):
        node_id = f"data:{category}"
        if graph.has_node(node_id):
            seeds.append(node_id)
    return seeds


def traverse(graph: nx.DiGraph, seed_nodes: list[str]) -> dict:
    """Given seed nodes, walk outward (in both directions) to collect the
    relevant subgraph: governing policies/rules, NDA coverage, partner tier.

    Returns a plain dict (not a graph object) so it's easy to drop straight
    into a prompt later in context_assembler.py.
    """
    policies, rules, labels, ndas, partners = set(), set(), set(), set(), set()

    for seed in seed_nodes:
        if not graph.has_node(seed):
            continue

        # Look both directions — e.g. a DataCategory has policies/rules
        # pointing *into* it, and a Partner has NDAs pointing *into* it too.
        neighbors = set(graph.predecessors(seed)) | set(graph.successors(seed))

        for node_id in neighbors | {seed}:
            node_type = graph.nodes[node_id].get("type")
            if node_type == "Policy":
                policies.add(node_id)
            elif node_type == "PolicyRule":
                rules.add(node_id)
                # a rule's mapped label is one hop further
                for label_id in graph.successors(node_id):
                    if graph.nodes[label_id].get("type") == "ClassificationLabel":
                        labels.add(label_id)
            elif node_type == "NDAContract":
                ndas.add(node_id)
            elif node_type == "Partner":
                partners.add(node_id)

    return {
        "policies": [{"id": p, **graph.nodes[p]} for p in policies],
        "rules": [{"id": r, **graph.nodes[r]} for r in rules],
        "labels": [{"id": l, **graph.nodes[l]} for l in labels],
        "ndas": [{"id": n, **graph.nodes[n]} for n in ndas],
        "partners": [{"id": p, **graph.nodes[p]} for p in partners],
    }


if __name__ == "__main__":
    # Quick manual check: a doc that mentions Acme + customerPII should pull
    # in the PII rule, the Restricted label, and Acme's active NDA.
    graph = build_graph()
    entities = {"partners": ["Acme"], "dataCategories": ["customerPII"]}
    seeds = find_seed_nodes(graph, entities)
    print("seed nodes:", seeds)
    context = traverse(graph, seeds)
    for key, items in context.items():
        print(f"\n{key}:")
        for item in items:
            print(" ", item)