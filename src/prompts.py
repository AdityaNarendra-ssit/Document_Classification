"""Central store for all prompts used in the project.

Add new prompts here as constants. Import them wherever needed.
"""

# ---------------------------------------------------------------------------
# extraction.py prompts
# ---------------------------------------------------------------------------

# System prompt sent to Claude for every extraction call.
EXTRACTION_SYSTEM_PROMPT = (
    "You are a data extractor. "
    "Always respond with raw JSON only. "
    "No markdown, no code fences, no explanation."
)

# User prompt template for extracting structured semantic context from a
# policy markdown document. Use EXTRACTION_USER_PROMPT.format(markdown=...)
# to fill in the document content.
EXTRACTION_USER_PROMPT = """You are a policy extraction engine. Read the markdown policy below and return a single JSON object.

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