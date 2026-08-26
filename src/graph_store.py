"""In-memory knowledge graph backed by networkx and RDF via rdflib."""

from pathlib import Path
from typing import Any

import networkx as nx
from rdflib import Graph, Literal, Namespace, RDF, URIRef

EX = Namespace("http://example.org/kg/")
DEFAULT_GRAPH_PATH = Path("data/graph.ttl")


class KnowledgeGraph:
    """Labeled property graph that can be exported/imported as RDF Turtle."""

    def __init__(self, path: Path | str = DEFAULT_GRAPH_PATH) -> None:
        self.path = Path(path)
        self.g = nx.DiGraph()
        # ponytail: load existing graph if present; start empty otherwise
        if self.path.exists():
            try:
                self.load()
            except Exception:
                pass

    # --- F1: read graph from seed nodes ---
    def read_graph(self, seed_entities: list[str], depth: int = 2) -> nx.DiGraph:
        """Return a subgraph reachable from seed entities within `depth` hops."""
        seed_nodes = {self._node_uri(name) for name in seed_entities}
        reachable: set[str] = set()
        frontier = set(seed_nodes)
        for _ in range(depth):
            next_frontier: set[str] = set()
            for node in frontier:
                reachable.add(node)
                next_frontier.update(self.g.neighbors(node))
                next_frontier.update(self.g.predecessors(node))
            frontier = next_frontier - reachable
        reachable.update(frontier)
        return self.g.subgraph(reachable).copy()

    # --- F2: reduce edges ---
    @staticmethod
    def reduce_edges(subgraph: nx.DiGraph, keep_edges: list[str]) -> nx.DiGraph:
        """Return a copy of the subgraph keeping only the specified edge types."""
        keep = set(keep_edges)
        reduced = subgraph.copy()
        for u, v, data in list(subgraph.edges(data=True)):
            if data.get("predicate", "") not in keep:
                reduced.remove_edge(u, v)
        return reduced

    # --- F3: eliminate nodes ---
    @staticmethod
    def eliminate_nodes(subgraph: nx.DiGraph, min_degree: int = 1) -> nx.DiGraph:
        """Drop nodes with total degree below min_degree."""
        cleaned = subgraph.copy()
        for node in list(cleaned.nodes):
            if cleaned.degree(node) < min_degree:
                cleaned.remove_node(node)
        return cleaned

    # --- F4: augment / calculate ---
    @staticmethod
    def augment_graph(subgraph: nx.DiGraph, seeds: list[str], scoring: str = "hop_distance") -> nx.DiGraph:
        """Add relevance metadata to nodes: hop distance from seeds."""
        out = subgraph.copy()
        seed_uris = {KnowledgeGraph._node_uri(name) for name in seeds}
        for node in out.nodes:
            try:
                dist = min(
                    nx.shortest_path_length(out, seed, node)
                    for seed in seed_uris if seed in out and nx.has_path(out, seed, node)
                )
            except ValueError:
                dist = -1
            out.nodes[node]["hop_distance"] = dist
            out.nodes[node]["relevance_score"] = 1.0 / (1.0 + max(dist, 0))
        return out

    # --- upsert ---
    def upsert_policy(
        self,
        context: Any,
        policy_id: str,
        version: str,
    ) -> str:
        """Upsert policy nodes, rules, entities and relations from semantic context."""
        # ponytail: assume context follows extraction.SemanticContext structure
        policy_uri = self._node_uri(policy_id)
        self.g.add_node(policy_uri, label=policy_id, type="Policy", version=version)

        for cat in context.data_categories:
            uri = self._node_uri(cat)
            self.g.add_node(uri, label=cat, type="DataCategory")
            self.g.add_edge(policy_uri, uri, predicate="governs")

        for rule in context.rules:
            rule_id = rule.rule_id or f"{policy_id}-rule-{id(rule)}"
            rule_uri = self._node_uri(rule_id)
            self.g.add_node(rule_uri, label=rule_id, type="PolicyRule", text=rule.text, version=version)
            self.g.add_edge(policy_uri, rule_uri, predicate="hasRule")
            for cat in rule.governs_data_categories:
                self.g.add_edge(rule_uri, self._node_uri(cat), predicate="governs")
            if rule.maps_to_label:
                label_uri = self._node_uri(rule.maps_to_label)
                self.g.add_node(label_uri, label=rule.maps_to_label, type="ClassificationLabel")
                self.g.add_edge(rule_uri, label_uri, predicate="mapsTo")

        for partner in context.partners:
            uri = self._node_uri(partner)
            self.g.add_node(uri, label=partner, type="Partner")

        for nda in context.nda_contracts:
            nda_uri = self._node_uri(nda.contract_id)
            partner_uri = self._node_uri(nda.partner)
            self.g.add_node(nda_uri, label=nda.contract_id, type="NDAContract")
            self.g.add_node(partner_uri, label=nda.partner, type="Partner")
            self.g.add_edge(nda_uri, partner_uri, predicate="covers")
            for cat in nda.data_categories:
                self.g.add_edge(nda_uri, self._node_uri(cat), predicate="forData")

        for rel in context.relationships:
            sub = self._node_uri(rel.subject)
            obj = self._node_uri(rel.object)
            self.g.add_node(sub, label=rel.subject)
            self.g.add_node(obj, label=rel.object)
            self.g.add_edge(sub, obj, predicate=rel.predicate)

        self.save()
        return policy_uri

    # --- RDF persistence ---
    def to_rdf(self) -> Graph:
        rdf = Graph()
        rdf.bind("ex", EX)
        for node, data in self.g.nodes(data=True):
            uri = URIRef(node)
            rdf.add((uri, RDF.type, EX[data.get("type", "Node")]))
            for key, value in data.items():
                if key in {"type"}:
                    continue
                rdf.add((uri, EX[self._safe_uri_component(key)], Literal(str(value))))
        for u, v, data in self.g.edges(data=True):
            pred = data.get("predicate", "relatedTo")
            rdf.add((URIRef(u), EX[self._safe_uri_component(pred)], URIRef(v)))
        return rdf

    @staticmethod
    def _safe_uri_component(value: str, max_len: int = 40) -> str:
        """Guard against a predicate/key that isn't a valid URI component
        (e.g. a relationship predicate coming back as a full sentence instead
        of a short relation name) crashing Turtle serialization.
        """
        if " " in value or len(value) > max_len or not value.replace("_", "").isalnum():
            from urllib.parse import quote
            return quote(value.strip()[:max_len].replace(" ", "_"), safe="_")
        return value
    
    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.to_rdf().serialize(destination=str(self.path), format="turtle")

    def load(self) -> None:
        rdf = Graph()
        rdf.parse(str(self.path), format="turtle")
        self.g = nx.DiGraph()
        for s, p, o in rdf:
            s_uri, o_uri = str(s), str(o)
            pred = p.removeprefix(str(EX)) if str(p).startswith(str(EX)) else str(p)
            if str(p) == str(RDF.type):
                self.g.add_node(s_uri, type=o.split("/")[-1] if isinstance(o, URIRef) else str(o))
                continue
            self.g.add_node(s_uri)
            self.g.add_node(o_uri)
            if pred in {"label", "version", "text", "hop_distance", "relevance_score"}:
                # node attribute triple: s -> pred -> o_literal
                self.g.nodes[s_uri][pred] = str(o)
                continue
            self.g.add_edge(s_uri, o_uri, predicate=pred)

    @staticmethod
    def _node_uri(name: str) -> str:
        """Turn any entity name into a valid RDF node URI.

        Extraction is supposed to produce short identifiers (category names,
        partner names, rule ids) but on real-world documents Claude can
        occasionally return a full descriptive sentence instead (seen with
        both a relationship predicate and, now, a node identifier — e.g. an
        NDA-scope data category coming back as a whole clause). Node names
        containing commas/colons/periods/quotes broke Turtle serialization
        even after spaces/#// were stripped, because those characters are
        still invalid in a QName-safe local part. urlencode + truncate here
        guarantees a valid URI regardless of what string comes in, so
        upsert_policy() can never crash on this again, no matter which field
        the bad text arrives through.
        """
        from urllib.parse import quote

        cleaned = name.strip().replace(" ", "_")
        if len(cleaned) > 60 or not cleaned.replace("_", "").isalnum():
            cleaned = quote(cleaned[:60], safe="_")
        return str(EX[cleaned])


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    kg = KnowledgeGraph(Path("data/demo_graph.ttl"))
    from src.extraction import SemanticContext
    ctx = SemanticContext(
        title="Demo",
        rules=[],
        data_categories=["customerPII"],
        partners=["Acme"],
        relationships=[{"subject": "Acme", "predicate": "relationshipTier", "object": "tier1"}],
    )
    kg.upsert_policy(ctx, "POL-DEMO", "v1")
    sub = kg.read_graph(["Acme"], depth=2)
    assert len(sub.nodes) >= 2
    print("demo ok:", list(sub.nodes))