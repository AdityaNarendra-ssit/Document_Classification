"""MCP server exposing the policy knowledge graph tools.

This module creates a FastMCP server named ``policy-knowledge-graph`` and
registers tools for document ingestion, semantic extraction, policy upsert,
and the four Graph RAG operations (read, reduce, eliminate, augment).
"""

from pathlib import Path

from loguru import logger
from mcp.server.fastmcp import FastMCP

from src.extraction import SemanticContext, extract_semantic_context
from src.graph_store import KnowledgeGraph
from src.ingestion import to_markdown

server = FastMCP("policy-knowledge-graph")
# One global graph store in memory, persisted to disk.
_graph = KnowledgeGraph()


@server.tool()
def convert_to_markdown(source: str) -> str:
    """Read a file path or raw text and return markdown.

    Args:
        source: A filesystem path or raw text/markdown string.

    Returns:
        Markdown representation of the source content.
    """
    logger.info("MCP tool convert_to_markdown called (source length: {})", len(source))
    result = to_markdown(source)
    logger.info("convert_to_markdown complete (result length: {})", len(result))
    return result


@server.tool()
def extract_semantic_context_tool(markdown: str) -> dict:
    """Extract structured semantic context from policy markdown.

    Args:
        markdown: Policy content as markdown text.

    Returns:
        A JSON-serializable dict representing the extracted semantic context.
    """
    logger.info("MCP tool extract_semantic_context_tool called (markdown length: {})", len(markdown))
    context = extract_semantic_context(markdown)
    logger.info("extract_semantic_context_tool complete")
    return context.model_dump(mode="json")


@server.tool()
def upsert_policy_graph(context: dict, policy_id: str, version: str) -> dict:
    """Upsert a policy into the knowledge graph from semantic context.

    Args:
        context: JSON-serializable semantic context dict matching the
            :class:`SemanticContext` schema.
        policy_id: Unique policy identifier.
        version: Policy version string.

    Returns:
        Dict with ``policy_uri``, ``nodes``, and ``edges`` counts.
    """
    logger.info("MCP tool upsert_policy_graph called for {}@{}", policy_id, version)
    ctx = SemanticContext.model_validate(context)
    uri = _graph.upsert_policy(ctx, policy_id, version)
    result = {"policy_uri": uri, "nodes": len(_graph.g.nodes), "edges": len(_graph.g.edges)}
    logger.info("upsert_policy_graph complete: {}", result)
    return result


@server.tool()
def read_graph(seed_entities: list[str], depth: int = 2) -> dict:
    """F1: Traverse the graph from seed entities within ``depth`` hops.

    Args:
        seed_entities: List of entity names/labels to start from.
        depth: Maximum number of hops to expand.

    Returns:
        JSON-serializable dict with ``nodes`` and ``edges``.
    """
    logger.info("MCP tool read_graph called with {} seed(s), depth {}", len(seed_entities), depth)
    sub = _graph.read_graph(seed_entities, depth)
    result = _subgraph_to_dict(sub)
    logger.info("read_graph complete: {} nodes, {} edges", len(result["nodes"]), len(result["edges"]))
    return result


@server.tool()
def reduce_edges(subgraph: dict, keep_edges: list[str]) -> dict:
    """F2: Filter a subgraph to only keep specified edge types.

    Args:
        subgraph: JSON-serializable subgraph dict with ``nodes`` and ``edges``.
        keep_edges: List of edge predicate names to retain.

    Returns:
        Filtered JSON-serializable subgraph dict.
    """
    logger.info("MCP tool reduce_edges called; keeping {}", keep_edges)
    sub = _dict_to_subgraph(subgraph)
    reduced = _graph.reduce_edges(sub, keep_edges)
    result = _subgraph_to_dict(reduced)
    logger.info("reduce_edges complete: {} nodes, {} edges", len(result["nodes"]), len(result["edges"]))
    return result


@server.tool()
def eliminate_nodes(subgraph: dict, min_degree: int = 1) -> dict:
    """F3: Drop nodes with total degree below ``min_degree``.

    Args:
        subgraph: JSON-serializable subgraph dict with ``nodes`` and ``edges``.
        min_degree: Minimum total degree required for a node to survive.

    Returns:
        Cleaned JSON-serializable subgraph dict.
    """
    logger.info("MCP tool eliminate_nodes called with min_degree {}", min_degree)
    sub = _dict_to_subgraph(subgraph)
    cleaned = _graph.eliminate_nodes(sub, min_degree)
    result = _subgraph_to_dict(cleaned)
    logger.info("eliminate_nodes complete: {} nodes, {} edges", len(result["nodes"]), len(result["edges"]))
    return result


@server.tool()
def augment_graph(subgraph: dict, seed_entities: list[str], scoring: str = "hop_distance") -> dict:
    """F4: Add relevance metadata (hop distance) to nodes.

    Args:
        subgraph: JSON-serializable subgraph dict with ``nodes`` and ``edges``.
        seed_entities: List of seed entity names/labels.
        scoring: Scoring mode; currently only ``hop_distance`` is supported.

    Returns:
        Augmented JSON-serializable subgraph dict.
    """
    logger.info(
        "MCP tool augment_graph called with {} seed(s), scoring='{}'",
        len(seed_entities),
        scoring,
    )
    sub = _dict_to_subgraph(subgraph)
    augmented = _graph.augment_graph(sub, seed_entities, scoring)
    result = _subgraph_to_dict(augmented)
    logger.info("augment_graph complete: {} nodes, {} edges", len(result["nodes"]), len(result["edges"]))
    return result


def _subgraph_to_dict(g) -> dict:
    """Convert a ``networkx.DiGraph`` into a JSON-serializable dict.

    Args:
        g: A networkx graph.

    Returns:
        Dict with ``nodes`` and ``edges`` lists. Node URIs are stored under
        the ``uri`` key, edge source/target under ``source``/``target``.
    """
    logger.debug("Converting subgraph to dict ({} nodes, {} edges)", len(g.nodes), len(g.edges))
    return {
        "nodes": [
            {"uri": n, **data} for n, data in g.nodes(data=True)
        ],
        "edges": [
            {"source": u, "target": v, **data} for u, v, data in g.edges(data=True)
        ],
    }


def _dict_to_subgraph(d: dict) -> "nx.DiGraph":
    """Convert a JSON-serializable subgraph dict back into a ``networkx.DiGraph``.

    Args:
        d: Subgraph dict with ``nodes`` and ``edges``.

    Returns:
        A reconstructed ``networkx.DiGraph``.
    """
    logger.debug("Converting dict to subgraph ({} nodes, {} edges)", len(d.get("nodes", [])), len(d.get("edges", [])))
    import networkx as nx
    sub = nx.DiGraph()
    for node in d.get("nodes", []):
        uri = node.pop("uri")
        sub.add_node(uri, **node)
    for edge in d.get("edges", []):
        src = edge.pop("source")
        tgt = edge.pop("target")
        sub.add_edge(src, tgt, **edge)
    logger.debug("Subgraph reconstruction complete")
    return sub


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    logger.info("Starting MCP server from __main__")
    server.run()
