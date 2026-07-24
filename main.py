"""Entry point: launch the policy knowledge graph MCP server, or run a one-shot build.

This module is the CLI front-end for the policy knowledge graph system. It can
start the FastMCP server (the default) or run a single ingestion/extraction
pipeline against a document file.
"""

import argparse

from loguru import logger

from src.extraction import extract_semantic_context
from src.graph_store import KnowledgeGraph
from src.ingestion import to_markdown
from src.mcp_server import server


def build_one_shot(source: str, policy_id: str, version: str) -> None:
    """Run the full one-shot pipeline for a single policy document.

    Steps:
        1. Convert the source document to markdown.
        2. Extract structured semantic context via the Anthropic API.
        3. Upsert the resulting entities and rules into the knowledge graph.

    Args:
        source: Path to a policy document (PDF, DOCX, HTML, TXT) or raw text.
        policy_id: Unique identifier for the policy (e.g. ``POL-001``).
        version: Policy version string (e.g. ``v1``).

    Returns:
        None
    """
    logger.info("Starting one-shot build for policy {}@{} from source {}", policy_id, version, source)

    logger.debug("Converting source to markdown")
    markdown = to_markdown(source)
    logger.info("Converted source to markdown ({} characters)", len(markdown))

    logger.debug("Extracting semantic context")
    context = extract_semantic_context(markdown)
    logger.info(
        "Extracted semantic context: {} rules, {} data categories, {} partners, {} NDA contracts",
        len(context.rules),
        len(context.data_categories),
        len(context.partners),
        len(context.nda_contracts),
    )

    logger.debug("Upserting policy into knowledge graph")
    graph = KnowledgeGraph()
    uri = graph.upsert_policy(context, policy_id, version)
    logger.info(
        "Upserted {}@{} -> {} ({} nodes, {} edges)",
        policy_id,
        version,
        uri,
        len(graph.g.nodes),
        len(graph.g.edges),
    )


def main() -> None:
    """Parse CLI arguments and dispatch to the requested command.

    Supported commands:
        - ``serve`` (default): run the FastMCP server.
        - ``build``: run the one-shot build pipeline; requires ``--file`` and ``--id``.

    Returns:
        None
    """
    parser = argparse.ArgumentParser(description="Policy knowledge graph")
    parser.add_argument("command", nargs="?", default="serve", choices=["serve", "build"])
    parser.add_argument("--file", help="Document source for one-shot build")
    parser.add_argument("--id", help="Policy ID for one-shot build")
    parser.add_argument("--version", default="v1", help="Policy version for one-shot build")
    args = parser.parse_args()

    logger.info("CLI command received: {}", args.command)

    if args.command == "build":
        if not args.file or not args.id:
            logger.error("build command requires both --file and --id")
            parser.error("build requires --file and --id")
        build_one_shot(args.file, args.id, args.version)
        return

    # default: run the MCP server
    logger.info("Starting MCP server")
    server.run()


if __name__ == "__main__":
    main()
