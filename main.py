"""Entry point: launch the policy knowledge graph MCP server, or run a one-shot build."""

import argparse

from src.extraction import extract_semantic_context
from src.graph_store import KnowledgeGraph
from src.ingestion import to_markdown
from src.mcp_server import server


def build_one_shot(source: str, policy_id: str, version: str) -> None:
    markdown = to_markdown(source)
    context = extract_semantic_context(markdown)
    graph = KnowledgeGraph()
    uri = graph.upsert_policy(context, policy_id, version)
    print(f"Upserted {policy_id}@{version} -> {uri}")
    print(f"Graph: {len(graph.g.nodes)} nodes, {len(graph.g.edges)} edges")


def main():
    parser = argparse.ArgumentParser(description="Policy knowledge graph")
    parser.add_argument("command", nargs="?", default="serve", choices=["serve", "build"])
    parser.add_argument("--file", help="Document source for one-shot build")
    parser.add_argument("--id", help="Policy ID for one-shot build")
    parser.add_argument("--version", default="v1", help="Policy version for one-shot build")
    args = parser.parse_args()

    if args.command == "build":
        if not args.file or not args.id:
            parser.error("build requires --file and --id")
        build_one_shot(args.file, args.id, args.version)
        return

    # default: run the MCP server
    server.run()


if __name__ == "__main__":
    main()
