"""Curator-owned RtR product alias table — TIP-014 Phase 1.

Discipline (same as kernel ``entities.yaml``):
  * ``CURATED`` gates the table — flip to ``False`` while drafting new entries.
  * The canonical keys and their variants are the ONLY strings the resolver in
    ``query_understanding`` can ever emit. It cannot invent an entity outside
    this table (e.g. it can never turn "hr" into "human resources"); "hr"
    resolves to HERA *only* because a curator placed it here.
  * No auto-merge. A human (Lâm) adds/edits variants here on purpose.

Every canonical below is a real RtR product name taken from the kernel
``capabilities.yaml`` (HERA, VEGA, HeraSight, HeraSight LR / "61T", DualSight,
OmniSight, SkyWatch 360, HeraHub / formerly "heralink", VegaHub, VegaSight,
AeroTunnel, LS1, S1). Variants are spellings, joined forms, and abbreviations
observed in real questions — nothing fabricated.
"""

CURATED = True

# canonical product name -> variant spellings / abbreviations.
# Matching is case- and diacritic-insensitive (see ``normalize_query``); list
# variants in any casing.
PRODUCT_ALIASES: dict[str, list[str]] = {
    "HERA": ["hira", "heara", "hr"],
    "VEGA": ["vga", "vaga"],
    "HeraSight": ["herasight", "hera sight", "hera-sight"],
    "HeraSight LR": ["herasight lr", "hera sight lr", "61t"],
    "DualSight": ["dualsight", "dual sight"],
    "OmniSight": ["omnisight", "omni sight"],
    "SkyWatch 360": ["skywatch", "sky watch", "skywatch 360"],
    "HeraHub": ["herahub", "hera hub", "heralink"],
    "VegaHub": ["vegahub", "vega hub"],
    "VegaSight": ["vegasight", "vega sight"],
    "AeroTunnel": ["aerotunnel", "aero tunnel"],
    "LS1": ["ls1", "ls-1"],
    "S1": ["s1"],
}
