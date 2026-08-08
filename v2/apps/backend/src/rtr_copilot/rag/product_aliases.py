"""Backward-compatible product view over the governed enterprise ontology.

New query intelligence reads ``enterprise_ontology.json`` directly and works
across arbitrary entity types and domains.  This module only preserves the
legacy ``PRODUCT_ALIASES`` API for callers and tests that have not migrated.
The JSON registry remains the sole authoritative data source.
"""

from rtr_copilot.rag.ontology import load_ontology

CURATED = True

# Legacy callers keep this API, but the JSON ontology is now authoritative.
PRODUCT_ALIASES: dict[str, list[str]] = load_ontology().legacy_aliases(
    entity_type="product",
)
