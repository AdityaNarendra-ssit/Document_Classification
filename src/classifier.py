"""
Classification Engine.

Takes the assembled prompt from context_assembler.py and calls Claude,
forcing structured JSON output via tool use (a single required tool,
tool_choice pinned to it) so the response always matches the schema —
no free-form prose to parse.
"""

import json
import os

from anthropic import Anthropic

MODEL = "claude-sonnet-5"

CLASSIFY_TOOL = {
    "name": "submit_classification",
    "description": "Submit the sensitivity classification decision for the document.",
    "input_schema": {
        "type": "object",
        "properties": {
            "classification": {
                "type": "string",
                "enum": ["Restricted", "Confidential", "Internal", "Public"],
            },
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "rationale": {"type": "string"},
            "citedPolicyRefs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "version": {"type": "string"},
                    },
                    "required": ["id"],
                },
            },
            "citedNDARefs": {"type": "array", "items": {"type": "string"}},
            "assumptions": {"type": "array", "items": {"type": "string"}},
            "needsHumanReview": {"type": "boolean"},
        },
        "required": [
            "classification",
            "confidence",
            "rationale",
            "citedPolicyRefs",
            "citedNDARefs",
            "needsHumanReview",
        ],
    },
}


def _client() -> Anthropic:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is required for classification")
    return Anthropic(api_key=key)


def classify(prompt: dict) -> dict:
    """Call Claude with the assembled prompt, return the structured
    classification result as a plain dict.

    `prompt` is the dict returned by context_assembler.assemble_prompt():
    {"system_block", "context_block", "document_block", "seed_entities"}
    """
    if not prompt.get("seed_entities"):
        # No known partners/data categories were found in the document —
        # there's nothing to classify against. Flag for human review rather
        # than let Claude guess with an empty context block.
        return {
            "classification": "Internal",
            "confidence": 0.0,
            "rationale": "No known partners or data categories were detected in the "
                         "document, so no policy context could be retrieved.",
            "citedPolicyRefs": [],
            "citedNDARefs": [],
            "assumptions": ["Defaulted due to missing entity matches"],
            "needsHumanReview": True,
        }

    client = _client()

    user_content = (
        f"Context (policies, rules, NDAs, partners relevant to this document):\n"
        f"{json.dumps(prompt['context_block'], indent=2)}\n\n"
        f"Document:\n{prompt['document_block']}"
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=prompt["system_block"],
        messages=[{"role": "user", "content": user_content}],
        tools=[CLASSIFY_TOOL],
        tool_choice={"type": "tool", "name": "submit_classification"},
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_classification":
            return block.input

    raise RuntimeError("Model did not return the expected submit_classification tool call")


if __name__ == "__main__":
    from src.context_assembler import assemble_prompt
    from src.extraction import SemanticContext
    from src.graph_store import KnowledgeGraph

    kg = KnowledgeGraph("data/demo_classifier.ttl")
    ctx = SemanticContext(
        title="Demo Policy",
        rules=[{
            "rule_id": "rule-pii",
            "text": "Customer PII is Restricted unless covered by an active NDA.",
            "governs_data_categories": ["customerPII"],
            "maps_to_label": "Restricted",
        }],
        data_categories=["customerPII"],
        partners=["Acme"],
        nda_contracts=[{"contract_id": "NDA-ACME-2024", "partner": "Acme", "data_categories": ["customerPII"]}],
    )
    kg.upsert_policy(ctx, "POL-DEMO", "v1")

    sample_doc = (
        "Quarterly data-sharing summary for Acme covering customerPII "
        "exports used in the joint analytics project."
    )
    prompt = assemble_prompt(kg, sample_doc)
    result = classify(prompt)
    print(json.dumps(result, indent=2))