"""Extract structured semantic context from policy markdown using Claude."""

import json
import os
from typing import Any

from anthropic import Anthropic
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from .prompts import EXTRACTION_SYSTEM_PROMPT, EXTRACTION_USER_PROMPT

load_dotenv()

CHUNK_SIZE = 80_000   # characters per chunk (safe margin under Claude's context)
OVERLAP     = 2_000   # overlap between chunks to avoid cutting mid-sentence


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

    def merge(self, other: "SemanticContext") -> "SemanticContext":
        """Merge another SemanticContext into this one, deduplicating lists."""
        # Keep first non-empty value for scalar fields
        return SemanticContext(
            title=self.title or other.title,
            policy_type=self.policy_type or other.policy_type,
            effective_date=self.effective_date or other.effective_date,
            # Deduplicate rules by rule_id
            rules=_dedup(self.rules + other.rules, key=lambda r: r.rule_id or r.text),
            # Deduplicate plain string lists
            data_categories=_dedup_str(self.data_categories + other.data_categories),
            partners=_dedup_str(self.partners + other.partners),
            # Deduplicate NDA contracts by contract_id
            nda_contracts=_dedup(self.nda_contracts + other.nda_contracts, key=lambda n: n.contract_id or n.partner),
            # Deduplicate relationships by subject+predicate+object
            relationships=_dedup(self.relationships + other.relationships, key=lambda r: f"{r.subject}|{r.predicate}|{r.object}"),
        )


def _dedup(items: list, key) -> list:
    """Deduplicate a list of objects by a key function, preserving order."""
    seen: set = set()
    result = []
    for item in items:
        k = key(item)
        if k and k not in seen:
            seen.add(k)
            result.append(item)
    return result


def _dedup_str(items: list[str]) -> list[str]:
    """Deduplicate a list of strings, preserving order."""
    seen: set = set()
    return [x for x in items if x and not (x in seen or seen.add(x))]


def _chunk_markdown(markdown: str, chunk_size: int = CHUNK_SIZE, overlap: int = OVERLAP) -> list[str]:
    """Split markdown into overlapping chunks, breaking at newlines where possible."""
    if len(markdown) <= chunk_size:
        return [markdown]

    chunks = []
    start = 0
    while start < len(markdown):
        end = start + chunk_size
        if end < len(markdown):
            # Try to break at a newline near the end of the chunk
            newline_pos = markdown.rfind("\n", start, end)
            if newline_pos > start:
                end = newline_pos
        chunks.append(markdown[start:end])
        start = end - overlap  # step back by overlap for context continuity

    return chunks


def _parse_response(text: str) -> dict[str, Any]:
    """Parse Claude's response into a dict, stripping any markdown fences."""
    text = text.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()

    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise RuntimeError(f"No JSON object found in response: {repr(text[:200])}")
    text = text[start:end]

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"JSON parse error at line {e.lineno} col {e.colno}: "
            f"{repr(text[max(0, e.pos - 50):e.pos + 50])}"
        ) from e


def _client() -> Anthropic:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is required for semantic extraction")
    return Anthropic(api_key=key)


def _extract_chunk(client: Anthropic, chunk: str, model: str) -> SemanticContext:
    """Call Claude on a single chunk and return a SemanticContext."""
    response = client.messages.create(
        model=model,
        max_tokens=8192,
        temperature=0,
        system=EXTRACTION_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": EXTRACTION_USER_PROMPT.format(markdown=chunk)},
        ],
    )

    if response.stop_reason == "max_tokens":
        raise RuntimeError("Claude response was truncated (hit max_tokens limit). Try increasing max_tokens.")

    text = ""
    for block in response.content:
        if block.type == "text":
            text = block.text
            break

    data = _parse_response(text)
    return SemanticContext.model_validate(data)


def extract_semantic_context(markdown: str, model: str = "claude-sonnet-4-6") -> SemanticContext:
    """Extract structured entities and rules from policy markdown.
    
    Handles documents of any size by splitting into overlapping chunks,
    extracting from each chunk, then merging and deduplicating results.
    """
    client = _client()
    chunks = _chunk_markdown(markdown)

    if len(chunks) == 1:
        # Fast path — no chunking needed
        return _extract_chunk(client, chunks[0], model)

    # Process each chunk and merge results
    merged: SemanticContext | None = None
    for i, chunk in enumerate(chunks):
        print(f"Processing chunk {i + 1}/{len(chunks)} ({len(chunk)} chars)...")
        ctx = _extract_chunk(client, chunk, model)
        merged = ctx if merged is None else merged.merge(ctx)

    return merged  # type: ignore[return-value]


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