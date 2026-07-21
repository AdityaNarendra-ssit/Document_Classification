"""MCP server exposing the policy knowledge graph tools."""

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from src.extraction import SemanticContext, extract_semantic_context
from src.graph_store import KnowledgeGraph
from src.ingestion import to_markdown

server = FastMCP("policy-knowledge-graph")
# ponytail: one global graph store in memory, persisted to disk
_graph = KnowledgeGraph()


@server.tool()
def convert_to_markdown(source: str) -> str:
    """Read a file path or raw text and return markdown."""
    return to_markdown(source)


@server.tool()
def extract_semantic_context_tool(markdown: str) -> dict:
    """Extract structured semantic context from policy markdown."""
    context = extract_semantic_context(markdown)
    return context.model_dump(mode="json")


@server.tool()
def upsert_policy_graph(context: dict, policy_id: str, version: str) -> dict:
    """Upsert a policy into the knowledge graph from semantic context."""
    ctx = SemanticContext.model_validate(context)
    uri = _graph.upsert_policy(ctx, policy_id, version)
    return {"policy_uri": uri, "nodes": len(_graph.g.nodes), "edges": len(_graph.g.edges)}


@server.tool()
def read_graph(seed_entities: list[str], depth: int = 2) -> dict:
    """F1: Traverse the graph from seed entities within `depth` hops."""
    sub = _graph.read_graph(seed_entities, depth)
    return _subgraph_to_dict(sub)


@server.tool()
def reduce_edges(subgraph: dict, keep_edges: list[str]) -> dict:
    """F2: Filter a subgraph to only keep specified edge types."""
    sub = _dict_to_subgraph(subgraph)
    reduced = _graph.reduce_edges(sub, keep_edges)
    return _subgraph_to_dict(reduced)


@server.tool()
def eliminate_nodes(subgraph: dict, min_degree: int = 1) -> dict:
    """F3: Drop nodes with total degree below min_degree."""
    sub = _dict_to_subgraph(subgraph)
    cleaned = _graph.eliminate_nodes(sub, min_degree)
    return _subgraph_to_dict(cleaned)


@server.tool()
def augment_graph(subgraph: dict, seed_entities: list[str], scoring: str = "hop_distance") -> dict:
    """F4: Add relevance metadata (hop distance) to nodes."""
    sub = _dict_to_subgraph(subgraph)
    augmented = _graph.augment_graph(sub, seed_entities, scoring)
    return _subgraph_to_dict(augmented)


def _subgraph_to_dict(g) -> dict:
    return {
        "nodes": [
            {"uri": n, **data} for n, data in g.nodes(data=True)
        ],
        "edges": [
            {"source": u, "target": v, **data} for u, v, data in g.edges(data=True)
        ],
    }


def _dict_to_subgraph(d: dict) -> KnowledgeGraph:
    import networkx as nx
    sub = nx.DiGraph()
    for node in d.get("nodes", []):
        uri = node.pop("uri")
        sub.add_node(uri, **node)
    for edge in d.get("edges", []):
        src = edge.pop("source")
        tgt = edge.pop("target")
        sub.add_edge(src, tgt, **edge)
    return sub


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    server.run()
