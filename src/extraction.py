"""Extract structured semantic context from policy markdown using Claude."""

import json
import os
from typing import Any

from anthropic import Anthropic
from pydantic import BaseModel, Field

PROMPT = """You are a policy extraction engine. Read the markdown policy below and return a single JSON object.

Required JSON schema:
{
  "title": "policy title",
  "policy_type": "Classification Taxonomy | NDA Registry | Partner Relationship Matrix | Data-Handling Rules | Regulatory Rules",
  "effective_date": "YYYY-MM-DD or empty string",
  "rules": [
    {
      "rule_id": "short unique id",
      "text": "verbatim or summarized rule text",
      "governs_data_categories": ["category_name"],
      "maps_to_label": "Restricted | Confidential | Internal | Public | null"
    }
  ],
  "data_categories": ["category_name"],
  "partners": ["Partner Name"],
  "nda_contracts": [
    {"contract_id": "NDA-...", "partner": "Partner Name", "data_categories": ["..."]}
  ],
  "relationships": [
    {"subject": "...", "predicate": "covers|forData|relationshipTier|governs|mapsTo", "object": "..."}
  ]
}

Return only valid JSON. No markdown, no commentary.

MARKDOWN:
{markdown}
"""


class Rule(BaseModel):
    rule_id: str = ""
    text: str = ""
    governs_data_categories: list[str] = Field(default_factory=list)
    maps_to_label: str | None = None


class NDAContract(BaseModel):
    contract_id: str = ""
    partner: str = ""
    data_categories: list[str] = Field(default_factory=list)


class Relationship(BaseModel):
    subject: str
    predicate: str
    object: str


class SemanticContext(BaseModel):
    title: str = ""
    policy_type: str = ""
    effective_date: str = ""
    rules: list[Rule] = Field(default_factory=list)
    data_categories: list[str] = Field(default_factory=list)
    partners: list[str] = Field(default_factory=list)
    nda_contracts: list[NDAContract] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)


def _client() -> Anthropic:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is required for semantic extraction")
    return Anthropic(api_key=key)


def extract_semantic_context(markdown: str, model: str = "claude-sonnet-4-5-20251001") -> SemanticContext:
    """Call Claude to extract structured entities and rules from policy markdown."""
    client = _client()
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        temperature=0,
        messages=[
            {"role": "user", "content": PROMPT.format(markdown=markdown[:120_000])},
        ],
    )
    text = ""
    for block in response.content:
        if block.type == "text":
            text = block.text
            break

    text = text.strip()
    if text.startswith("```"):
        text = text.split("```json", 1)[-1].split("```", 1)[0].strip()

    data: dict[str, Any] = json.loads(text)
    return SemanticContext.model_validate(data)


if __name__ == "__main__":
    sample = """# ACME Data Handling Policy
Version 1.2, effective 2025-01-01.

## Rules
1. Customer PII must be classified Confidential.
2. Partner Acme Corp is under an NDA for customer PII.
"""
    ctx = extract_semantic_context(sample)
    assert ctx.title
    print(ctx.model_dump_json(indent=2))
