"""In-memory knowledge graph backed by networkx and RDF via rdflib.

The :class:`KnowledgeGraph` class stores policies, rules, data categories,
partners, NDA contracts, and classification labels as a directed property
graph. It supports graph traversal, filtering, augmentation with relevance
scores, and persistence as RDF/Turtle.
"""

from pathlib import Path
from typing import Any

import networkx as nx
from loguru import logger
from rdflib import Graph, Literal, Namespace, RDF, URIRef

EX = Namespace("http://example.org/kg/")
DEFAULT_GRAPH_PATH = Path("data/graph.ttl")


class KnowledgeGraph:
    """Labeled property graph that can be exported/imported as RDF Turtle.

    The graph is held in memory as a ``networkx.DiGraph`` and persisted to
    disk as RDF/Turtle. On initialization, if a file exists at ``path`` it is
    loaded automatically.

    Attributes:
        path: Filesystem path used for RDF persistence.
        g: The underlying ``networkx.DiGraph``.
    """

    def __init__(self, path: Path | str = DEFAULT_GRAPH_PATH) -> None:
        """Initialize the knowledge graph, loading any existing RDF file.

        Args:
            path: Path to the Turtle file used for persistence. Defaults to
                ``data/graph.ttl``.
        """
        self.path = Path(path)
        self.g: nx.DiGraph = nx.DiGraph()
        logger.info("KnowledgeGraph initialized with path {}", self.path)

        if self.path.exists():
            logger.info("Found existing graph file; attempting to load")
            try:
                self.load()
                logger.info(
                    "Loaded existing graph: {} nodes, {} edges",
                    len(self.g.nodes),
                    len(self.g.edges),
                )
            except Exception:
                logger.exception("Failed to load existing graph from {}; starting empty", self.path)
        else:
            logger.info("No existing graph file found; starting with empty graph")

    # --- F1: read graph from seed nodes ---
    def read_graph(self, seed_entities: list[str], depth: int = 2) -> nx.DiGraph:
        """Return a subgraph reachable from seed entities within ``depth`` hops.

        Traversal follows both outgoing and incoming edges, so neighbors and
        predecessors of each frontier node are included.

        Args:
            seed_entities: List of entity names/labels to start traversal from.
            depth: Maximum number of hops to expand from each seed.

        Returns:
            A copy of the induced subgraph containing all reached nodes.
        """
        logger.info("read_graph called with {} seed(s) and depth {}", len(seed_entities), depth)
        seed_nodes = {self._node_uri(name) for name in seed_entities}
        reachable: set[str] = set()
        frontier = set(seed_nodes)

        for hop in range(depth):
            logger.debug("Hop {}: frontier size {}", hop + 1, len(frontier))
            next_frontier: set[str] = set()
            for node in frontier:
                reachable.add(node)
                next_frontier.update(self.g.neighbors(node))
                next_frontier.update(self.g.predecessors(node))
            frontier = next_frontier - reachable

        reachable.update(frontier)
        subgraph = self.g.subgraph(reachable).copy()
        logger.info(
            "read_graph complete: reached {} nodes, {} edges",
            len(subgraph.nodes),
            len(subgraph.edges),
        )
        return subgraph

    # --- F2: reduce edges ---
    @staticmethod
    def reduce_edges(subgraph: nx.DiGraph, keep_edges: list[str]) -> nx.DiGraph:
        """Return a copy of the subgraph keeping only the specified edge types.

        Edges whose ``predicate`` attribute is not in ``keep_edges`` are removed.
        Isolated nodes remain in the returned copy.

        Args:
            subgraph: Input directed graph.
            keep_edges: List of edge predicate names to retain.

        Returns:
            A filtered copy of the subgraph.
        """
        logger.info("reduce_edges called; keeping predicates: {}", keep_edges)
        keep = set(keep_edges)
        reduced = subgraph.copy()
        removed = 0
        for u, v, data in list(subgraph.edges(data=True)):
            if data.get("predicate", "") not in keep:
                reduced.remove_edge(u, v)
                removed += 1
        logger.info("reduce_edges removed {} edge(s); {} edge(s) remain", removed, len(reduced.edges))
        return reduced

    # --- F3: eliminate nodes ---
    @staticmethod
    def eliminate_nodes(subgraph: nx.DiGraph, min_degree: int = 1) -> nx.DiGraph:
        """Drop nodes with total degree below ``min_degree``.

        In a directed graph, total degree counts both incoming and outgoing
        edges.

        Args:
            subgraph: Input directed graph.
            min_degree: Minimum total degree a node must have to survive.

        Returns:
            A cleaned copy of the subgraph.
        """
        logger.info("eliminate_nodes called with min_degree {}", min_degree)
        cleaned = subgraph.copy()
        removed = 0
        for node in list(cleaned.nodes):
            if cleaned.degree(node) < min_degree:
                cleaned.remove_node(node)
                removed += 1
        logger.info(
            "eliminate_nodes removed {} node(s); {} node(s) remain",
            removed,
            len(cleaned.nodes),
        )
        return cleaned

    # --- F4: augment / calculate ---
    @staticmethod
    def augment_graph(subgraph: nx.DiGraph, seeds: list[str], scoring: str = "hop_distance") -> nx.DiGraph:
        """Add relevance metadata to nodes: hop distance from seeds.

        For each node, computes the shortest directed path length from the
        nearest seed and stores it as ``hop_distance``. ``relevance_score`` is
        defined as ``1 / (1 + hop_distance)``.

        Args:
            subgraph: Input directed graph.
            seeds: List of seed entity names/labels.
            scoring: Scoring mode. Currently only ``hop_distance`` is supported.

        Returns:
            A copy of the subgraph with ``hop_distance`` and ``relevance_score``
            attributes on every node.
        """
        logger.info("augment_graph called with {} seed(s), scoring='{}'", len(seeds), scoring)
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
        logger.info("augment_graph complete; annotated {} node(s)", len(out.nodes))
        return out

    # --- upsert ---
    def upsert_policy(
        self,
        context: Any,
        policy_id: str,
        version: str,
    ) -> str:
        """Upsert policy nodes, rules, entities and relations from semantic context.

        Expects ``context`` to follow the structure produced by
        :func:`src.extraction.extract_semantic_context` (a ``SemanticContext``
        object or compatible dict).

        Args:
            context: Extracted semantic context for the policy.
            policy_id: Unique policy identifier.
            version: Policy version string.

        Returns:
            The URI of the upserted ``Policy`` node.
        """
        logger.info("upsert_policy called for {}@{}", policy_id, version)
        policy_uri = self._node_uri(policy_id)
        self.g.add_node(policy_uri, label=policy_id, type="Policy", version=version)
        logger.debug("Added Policy node: {}", policy_uri)

        for cat in context.data_categories:
            uri = self._node_uri(cat)
            self.g.add_node(uri, label=cat, type="DataCategory")
            self.g.add_edge(policy_uri, uri, predicate="governs")
            logger.debug("Linked Policy -> DataCategory: {}", cat)

        for rule in context.rules:
            rule_id = rule.rule_id or f"{policy_id}-rule-{id(rule)}"
            rule_uri = self._node_uri(rule_id)
            self.g.add_node(rule_uri, label=rule_id, type="PolicyRule", text=rule.text, version=version)
            self.g.add_edge(policy_uri, rule_uri, predicate="hasRule")
            logger.debug("Added PolicyRule node: {}", rule_uri)
            for cat in rule.governs_data_categories:
                self.g.add_edge(rule_uri, self._node_uri(cat), predicate="governs")
                logger.debug("Linked Rule -> DataCategory: {}", cat)
            if rule.maps_to_label:
                label_uri = self._node_uri(rule.maps_to_label)
                self.g.add_node(label_uri, label=rule.maps_to_label, type="ClassificationLabel")
                self.g.add_edge(rule_uri, label_uri, predicate="mapsTo")
                logger.debug("Linked Rule -> ClassificationLabel: {}", rule.maps_to_label)

        for partner in context.partners:
            uri = self._node_uri(partner)
            self.g.add_node(uri, label=partner, type="Partner")
            logger.debug("Added Partner node: {}", partner)

        for nda in context.nda_contracts:
            nda_uri = self._node_uri(nda.contract_id)
            partner_uri = self._node_uri(nda.partner)
            self.g.add_node(nda_uri, label=nda.contract_id, type="NDAContract")
            self.g.add_node(partner_uri, label=nda.partner, type="Partner")
            self.g.add_edge(nda_uri, partner_uri, predicate="covers")
            logger.debug("Added NDAContract node: {} -> Partner: {}", nda.contract_id, nda.partner)
            for cat in nda.data_categories:
                self.g.add_edge(nda_uri, self._node_uri(cat), predicate="forData")
                logger.debug("Linked NDA -> DataCategory: {}", cat)

        for rel in context.relationships:
            sub = self._node_uri(rel.subject)
            obj = self._node_uri(rel.object)
            self.g.add_node(sub, label=rel.subject)
            self.g.add_node(obj, label=rel.object)
            self.g.add_edge(sub, obj, predicate=rel.predicate)
            logger.debug("Added relationship: {} -{}-> {}", rel.subject, rel.predicate, rel.object)

        self.save()
        logger.info(
            "upsert_policy complete for {}@{}: {} nodes, {} edges total",
            policy_id,
            version,
            len(self.g.nodes),
            len(self.g.edges),
        )
        return policy_uri

    # --- RDF persistence ---
    def to_rdf(self) -> Graph:
        """Serialize the in-memory graph as an rdflib ``Graph``.

        Node attributes become RDF literals on the node URI. Edges become
        predicate URIs in the ``ex:`` namespace.

        Returns:
            An ``rdflib.Graph`` containing the full knowledge graph.
        """
        logger.debug("Converting networkx graph to RDF ({} nodes, {} edges)", len(self.g.nodes), len(self.g.edges))
        rdf = Graph()
        rdf.bind("ex", EX)
        for node, data in self.g.nodes(data=True):
            uri = URIRef(node)
            rdf.add((uri, RDF.type, EX[data.get("type", "Node")]))
            for key, value in data.items():
                if key in {"type"}:
                    continue
                rdf.add((uri, EX[key], Literal(str(value))))
        for u, v, data in self.g.edges(data=True):
            pred = data.get("predicate", "relatedTo")
            rdf.add((URIRef(u), EX[pred], URIRef(v)))
        logger.debug("RDF conversion complete: {} triples", len(rdf))
        return rdf

    def save(self) -> None:
        """Persist the current graph to ``self.path`` as RDF/Turtle.

        The parent directory is created if it does not exist.

        Returns:
            None
        """
        logger.debug("Saving graph to {}", self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.to_rdf().serialize(destination=str(self.path), format="turtle")
        logger.info("Graph saved to {} ({} nodes, {} edges)", self.path, len(self.g.nodes), len(self.g.edges))

    def load(self) -> None:
        """Load a graph from ``self.path`` as RDF/Turtle.

        Replaces the current in-memory graph. Triples are interpreted as either
        node attributes (``label``, ``version``, ``text``, etc.) or edges.

        Returns:
            None

        Raises:
            Exception: Propagated by ``rdflib`` if the file cannot be parsed.
        """
        logger.info("Loading graph from {}", self.path)
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
        logger.info("Graph loaded: {} triples, {} nodes, {} edges", len(rdf), len(self.g.nodes), len(self.g.edges))

    @staticmethod
    def _node_uri(name: str) -> str:
        """Convert a human-readable name into a safe URI in the ``ex:`` namespace.

        Replaces spaces and slashes with underscores and strips any characters
        that are not allowed in a URI local name.

        Args:
            name: Entity name or label.

        Returns:
            A URI string in the ``http://example.org/kg/`` namespace.
        """
        import re
        safe = name.replace(" ", "_").replace("/", "_")
        safe = re.sub(r'[^A-Za-z0-9_\-.]', '', safe)
        safe = safe.strip("_.-") or "unknown"
        return str(EX[safe])


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
    logger.info("Demo subgraph nodes: {}", list(sub.nodes))
    assert len(sub.nodes) >= 2
    print("demo ok:", list(sub.nodes))
