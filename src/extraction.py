"""Extract structured semantic context from policy markdown using Claude.

This module sends policy markdown to the Anthropic API and asks for a
structured JSON representation: rules, data categories, partners, NDA
contracts, and relationships. The response is validated into Pydantic models.
"""

import json
import os
from typing import Any

from anthropic import Anthropic
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import os
from anthropic import Anthropic

from loguru import logger

load_dotenv()

PROMPT = """You are a policy extraction engine. Read the markdown policy below and return a single JSON object.

Required JSON schema:
{{
  "title": "policy title",
  "policy_type": "Classification Taxonomy | NDA Registry | Partner Relationship Matrix | Data-Handling Rules | Regulatory Rules",
  "effective_date": "YYYY-MM-DD or empty string",
  "rules": [
    {{
      "rule_id": "short unique id",
      "text": "verbatim or summarized rule text",
      "governs_data_categories": ["category_name"],
      "maps_to_label": "Restricted | Confidential | Internal | Public | null"
    }}
  ],
  "data_categories": ["category_name"],
  "partners": ["Partner Name"],
  "nda_contracts": [
    {{"contract_id": "NDA-...", "partner": "Partner Name", "data_categories": ["..."]}}
  ],
  "relationships": [
    {{"subject": "...", "predicate": "covers|forData|relationshipTier|governs|mapsTo", "object": "..."}}
  ]
}}

Return only valid JSON. No markdown, no commentary.

MARKDOWN:
{markdown}
"""


class Rule(BaseModel):
    """A single rule extracted from a policy document.

    Attributes:
        rule_id: Short unique identifier for the rule.
        text: Verbatim or summarized rule text.
        governs_data_categories: Data categories this rule applies to.
        maps_to_label: Sensitivity label the rule maps to, if any.
    """

    rule_id: str = ""
    text: str = ""
    governs_data_categories: list[str] = Field(default_factory=list)
    maps_to_label: str | None = None


class NDAContract(BaseModel):
    """An NDA contract referenced by a policy.

    Attributes:
        contract_id: Unique contract identifier.
        partner: Name of the partner covered by the contract.
        data_categories: Data categories protected by the contract.
    """

    contract_id: str = ""
    partner: str = ""
    data_categories: list[str] = Field(default_factory=list)


class Relationship(BaseModel):
    """A typed relationship between two entities in the policy graph.

    Attributes:
        subject: Source entity.
        predicate: Relationship type (covers, forData, relationshipTier, governs, mapsTo).
        object: Target entity.
    """

    subject: str
    predicate: str
    object: str


class SemanticContext(BaseModel):
    """Structured semantic content extracted from a policy document.

    This is the top-level model returned by :func:`extract_semantic_context`.

    Attributes:
        title: Human-readable policy title.
        policy_type: Category of policy document.
        effective_date: ISO-8601 effective date or empty string.
        rules: List of extracted rules.
        data_categories: Data categories mentioned in the policy.
        partners: Partners mentioned in the policy.
        nda_contracts: NDA contracts mentioned in the policy.
        relationships: Extra entity relationships not covered by the above fields.
    """

    title: str = ""
    policy_type: str = ""
    effective_date: str = ""
    rules: list[Rule] = Field(default_factory=list)
    data_categories: list[str] = Field(default_factory=list)
    partners: list[str] = Field(default_factory=list)
    nda_contracts: list[NDAContract] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)


def _client() -> Anthropic:
    """Build an Anthropic client using the API key from the environment.

    The key is read from ``ANTHROPIC_API_KEY``. ``.env`` files are loaded at
    module import time via ``load_dotenv``.

    Returns:
        An authenticated ``Anthropic`` client instance.

    Raises:
        RuntimeError: If ``ANTHROPIC_API_KEY`` is missing or empty.
    """
    logger.debug("Building Anthropic client")
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        logger.error("ANTHROPIC_API_KEY is not set")
        raise RuntimeError("ANTHROPIC_API_KEY is required for semantic extraction")
    logger.info("Anthropic client configured (key present)")
    return Anthropic(api_key=key)


def extract_semantic_context(markdown: str, model: str = "claude-sonnet-4-6") -> SemanticContext:
    """Call Claude to extract structured entities and rules from policy markdown.

    The markdown is truncated to 120,000 characters to fit within the model's
    context window. The response is sanitized (code fences removed) and parsed
    as JSON, then validated into a :class:`SemanticContext` object.

    Args:
        markdown: Policy content as markdown text.
        model: Anthropic model identifier to use for extraction.

    Returns:
        A validated :class:`SemanticContext` containing the extracted policy graph data.

    Raises:
        RuntimeError: If the API response contains no JSON object or if JSON parsing fails.
    """
    logger.info("Extracting semantic context using model '{}' (markdown length: {})", model, len(markdown))

    client = _client()
    truncated = markdown[:120_000]
    logger.debug("Truncated markdown to {} characters for API call", len(truncated))

    logger.debug("Sending extraction request to Anthropic API")
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        temperature=0,
        system="You are a data extractor. Always respond with raw JSON only. No markdown, no code fences, no explanation.",
        messages=[
            {"role": "user", "content": PROMPT.format(markdown=truncated)},
        ],
    )
    logger.info("Received extraction response with {} content block(s)", len(response.content))

    text = ""
    for block in response.content:
        if block.type == "text":
            text = block.text
            break

    text = text.strip()
    logger.debug("Raw text response length: {}", len(text))

    # Remove code fences if present.
    if "```json" in text:
        logger.debug("Stripping ```json code fence from response")
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        logger.debug("Stripping generic code fence from response")
        text = text.split("```", 1)[1].split("```", 1)[0].strip()

    # Find the JSON object boundaries.
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        logger.error("No JSON object found in model response")
        raise RuntimeError(f"No JSON object found in response: {repr(text[:200])}")
    text = text[start:end]
    logger.debug("Extracted JSON object ({} characters)", len(text))

    try:
        data: dict[str, Any] = json.loads(text)
        logger.info("JSON parsed successfully")
    except json.JSONDecodeError as e:
        logger.exception("Failed to parse model response as JSON")
        raise RuntimeError(
            f"JSON parse error at line {e.lineno} col {e.colno}: "
            f"{repr(text[max(0, e.pos - 50):e.pos + 50])}"
        ) from e

    context = SemanticContext.model_validate(data)
    logger.info(
        "Semantic context validated: {} rules, {} categories, {} partners, {} NDAs, {} relationships",
        len(context.rules),
        len(context.data_categories),
        len(context.partners),
        len(context.nda_contracts),
        len(context.relationships),
    )
    return context


if __name__ == "__main__":
    sample = """# ACME Data Handling Policy
Version 1.2, effective 2025-01-01.

## Rules
1. Customer PII must be classified Confidential.
2. Partner Acme Corp is under an NDA for customer PII.
"""
    ctx = extract_semantic_context(sample)
    logger.info("Self-test title: {}", ctx.title)
    assert ctx.title
