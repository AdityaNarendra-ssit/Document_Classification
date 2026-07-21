"""
Classification Engine (design.md, section 2.5).

Takes the assembled prompt from context_assembler.py and calls Claude Opus,
forcing structured JSON output via tool use (a single required tool, no
other tools offered, tool_choice pinned to it) so the response is always
valid, parseable JSON matching the schema in design.md rather than free-form
prose we'd have to regex out.

Not executed in this environment (no API key here) — written to run as-is
once ANTHROPIC_API_KEY is set.
"""

import json
import os

import anthropic

MODEL = "claude-opus-4-8"  # per product-self-knowledge: current Opus model string

# Mirrors the JSON shape in design.md section 2.5 exactly, expressed as a
# tool schema so Opus is forced to fill every field.
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
                    "required": ["id", "version"],
                },
            },
            "citedNDARefs": {"type": "array", "items": {"type": "string"}},
            "entitiesDetected": {
                "type": "object",
                "properties": {
                    "partners": {"type": "array", "items": {"type": "string"}},
                    "dataCategories": {"type": "array", "items": {"type": "string"}},
                },
            },
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


def classify(prompt: dict) -> dict:
    """Call Claude Opus with the assembled prompt and return the structured
    classification result as a plain dict.

    `prompt` is the dict returned by context_assembler.assemble_prompt():
    {"system_block": str, "context_block": dict, "document_block": str, ...}
    """
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

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

    # Shouldn't happen given tool_choice is pinned, but fail loudly if it does
    # rather than silently returning nothing to audit_log.py later.
    raise RuntimeError("Opus did not return the expected submit_classification tool call")


if __name__ == "__main__":
    from context_assembler import assemble_prompt

    sample_doc = (
        "Quarterly data-sharing summary for Acme covering customerPII "
        "exports used in the joint analytics project."
    )
    result = classify(assemble_prompt(sample_doc))
    print(json.dumps(result, indent=2))