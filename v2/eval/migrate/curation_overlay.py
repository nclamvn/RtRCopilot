"""TIP-013B · Homeowner curation-decision OVERLAY (DRY-RUN ONLY).

This module encodes the Homeowner's curation decisions as an explicit, auditable
*overlay* the migration adapter reads at convert time.  The read-only kernel
snapshot under ``kernel-real/`` is NEVER modified: every transform here is applied
to the *emitted V2 packages* only.  Nothing here activates, applies, writes a
production database, or writes back to the kernel.

Two waves of decisions
----------------------
**Wave 1 (approved 02/08/2026, produced 131 ready) — unchanged:**

1a. **Promote the 5 Group-1 ``kernel_ref`` facts that resolve to
   ``verified_primary``** (they inherit their source record's verified provenance)
   -> ``verified_primary`` soft-ready with the ``needs_double_check`` marker and a
   source note naming the inherited kernel record.  AND fix the 3 HERA unit-drift
   facts (``lb`` -> ``kg``) -> the drift clears and they become ``strict``.
2. **Promote the 79 l3-claim facts that already carry an ``evidence_span``** to
   ``soft`` grounded on that real span, WITH ``needs_double_check``.  Selected by
   RULE.  Every *other* claim stays ``claim``.
3. **The 6 strategic-doc ``kernel_ref`` facts** -> the ``strategic`` tier, grounded
   on the staged strategic docs, WITH the double-check caveat.
4/5. **Exclude ``L3R.K.005``** (a toolkit/process reference, not a fact).

**Wave 2 (FINAL decision 02/08/2026 — "finalize per the recommendation, resolve
everything, leave nothing out"; lifts 131 -> 219 ready):**

1B. **Promote the 67 ``capabilities`` claim facts -> ``soft`` + caveat.**  RULE:
   a capabilities record with kernel provenance ``claim`` AND a non-empty
   ``evidence`` field (a real documentary source reference: brochure / KB sheet /
   DCMA / patent) maps to ``approved_internal`` soft, with the source note built
   from that real ``evidence`` reference + ``needs_double_check``.  No fabrication.
2B. **Cascade:** a ``l3_facts`` ``kernel_ref`` that currently lands in ``curate``
   (``provenance_missing``) whose ``kernel_ref`` names a *now-promoted capability*
   inherits ``soft`` + caveat (``approved_internal``, note citing the cap it
   inherits from).  RULE, resolved against the promoted-capability id set the
   adapter computes from the same registry — so it is a genuine dependency cascade,
   not a hand list.  (All 20 remaining curate kernel_refs resolve to a promoted
   cap; verified by :func:`CurationOverlay.promoted_capability_ids`.)
3B. **Interim-spec exception:** an interim ``specs`` claim (status INT, no
   ``raw_text``) that DUPLICATES an already-VERIFIED spec is promoted to
   ``approved_internal`` soft + caveat, its note naming the verified spec it
   duplicates.  Only ``SPEC.HERA.MTOW.HC001`` (duplicates the fixed
   ``SPEC.HERA.MTOW``) qualifies; the other 7 interim specs stay ``claim``.

**Explicit final dispositions (NO transform — the default already produces them;
recorded here so nothing is in limbo).**  See :func:`final_disposition`:

* **Held as ``claim`` (Decision 3):** the 22 ``boms`` restricted buy-price/supplier
  facts + the 1 ``prices`` claim (FX rate) — cost/price sensitivity + fast drift,
  leader-zone, promote only after per-item currency confirmation; and the 7 interim
  ``specs`` claims — not primary-sourced.
* **Held as ``derived`` (Decision 4):** the 3 ``derived_costs`` claim facts + the 3
  ``DERIVED.*`` in ``curate`` — calculations, not primary facts; a computed layer,
  never frozen as a SOT fact.
* **Irreducible gaps (Decision 6):** the ~6 facts genuinely lacking a source /
  resolvable provenance (:data:`IRREDUCIBLE_GAP`) — held with the exact missing
  field named, never fabricated.

Honesty
-------
Every promoted/soft/strategic record still references a REAL source: the real
``evidence_span`` text (D2), the real ``evidence`` reference (D1B), the resolved
source record / kernel_ref (D1a, D2B), the verified spec it duplicates (D3B), or
the staged strategic doc (D3).  A promoted claim maps to ``approved_internal`` (an
internal curator-approval state, NOT a masquerading verified state) so the publish
gate's ``claim_masquerades_as_approved`` guard stays meaningful; the double-check
caveat and the real source pointer ride with it.  Nothing is fabricated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# --------------------------------------------------------------------------- #
# Wave-1 decision sets (unchanged)
# --------------------------------------------------------------------------- #
# Decision 1a -- 5 kernel_ref facts that resolve to verified_primary.  Each
# inherits its source record's verified provenance (resolution table in
# vibecode_v2/TIP-013B_KERNEL_REF_RESOLUTION.md).  Value = the kernel record the
# fact's ``kernel_ref`` names (recorded in the source note for audit).
PROMOTE_VERIFIED_PRIMARY: frozenset[str] = frozenset(
    {"L3R.2.005", "L3R.2.013", "L3R.2.027", "L3R.3.030", "L3R.K.006"},
)

# Decision 1b -- 3 HERA unit-drift facts.  (from_unit, to_unit); applied only when
# the fact's current unit actually equals ``from_unit`` (never a blind overwrite).
UNIT_FIX: dict[str, tuple[str, str]] = {
    "SPEC.HERA.WEIGHT.EMPTY": ("lb", "kg"),
    "SPEC.HERA.WEIGHT.TAKEOFF": ("lb", "kg"),
    "SPEC.HERA.MTOW": ("lb", "kg"),
}

# Decision 3 -- 6 strategic-doc kernel_ref facts -> ``strategic`` tier.
STRATEGIC_DOC: frozenset[str] = frozenset(
    {"L3R.2.023", "L3R.2.024", "L3R.2.025", "L3R.2.026", "L3R.2.032", "L3R.K.004"},
)

# Decision 4/5 -- excluded entirely from the SOT fact set.
EXCLUDE: frozenset[str] = frozenset({"L3R.K.005"})

# --------------------------------------------------------------------------- #
# Wave-2 decision sets (FINAL completion)
# --------------------------------------------------------------------------- #
# Decision 3B -- interim spec(s) that duplicate an already-VERIFIED spec.  Maps
# ``fact_id -> the verified spec it duplicates`` (recorded in the source note).
# Only the MTOW HC-001 matrix figure qualifies (duplicates the fixed SPEC.HERA.MTOW).
PROMOTE_INTERIM_SPEC_DUP: dict[str, str] = {"SPEC.HERA.MTOW.HC001": "SPEC.HERA.MTOW"}

# Decision 6 -- irreducible gaps: ``fact_id -> the exact missing field``, named
# honestly for the disposition ledger.  These stay ``curate`` (never fabricated).
IRREDUCIBLE_GAP: dict[str, str] = {
    "SPEC.HERA.PAYLOAD.BAYS": "verified_value (3-vs-4 payload-bay CONFLICT; provenance flagged)",
    "PRICE.VEGA.MSRP.VN": "value (placeholder; VEGA-VN price still verify_pending)",
    "PRICE.RMUS.LEGACY.HERA": "supersession (legacy HERA 1.0 listing; retire or supersede)",
    "DERIVED.HERA.PREMIUM_VS_VN": "source (derivation source pointer)",
    "DERIVED.HERA.BUNDLE_GAP_US": "source (+ resolve the $580 bundle-vs-list gap flag)",
    "DERIVED.HERA.BUNDLE_GAP_VN": "source (+ resolve the $5,580 VN markup gap flag)",
}

# V2 provenance a promoted kernel-claim / capability / strategic doctrine maps to:
# an internal curator-approval state (NOT a verified-without-evidence masquerade).
_APPROVED_INTERNAL = "approved_internal"
_VERIFIED_PRIMARY = "verified_primary"

# Kernel provenance levels that already carry an honest verified/approved V2 state
# (kept local so the overlay never imports the adapter -- one-way dependency).
_VERIFIED_LEVELS: frozenset[str] = frozenset(
    {"verified_primary", "verified_secondary", "approved_internal", "derived_from_verified"},
)

# Tier label for decision 3.  Kept as a string so the overlay does not import the
# adapter (one-way dependency: the adapter imports the overlay, never the reverse).
TIER_STRATEGIC = "strategic"

# Max length of the evidence reference echoed into a D1B source note (deterministic).
_EVIDENCE_NOTE_LIMIT = 160


@dataclass(frozen=True)
class OverlayDecision:
    """The overlay's verdict for a single fact (empty when no decision applies).

    ``apply_to_fact`` returns a *copy* of the fact with the unit fix and/or
    provenance injection applied; the original kernel-loaded dict is never mutated.
    ``tier_label`` (when ``strategic``) relabels an otherwise-``soft`` ready record.
    ``note_suffix`` is appended to the honest source note for audit (which kernel
    record / evidence reference / strategic doc the promotion inherits from).
    ``decision_ref`` names the Homeowner decision for the readiness report.
    """

    exclude: bool = False
    fix_unit: tuple[str, str] | None = None
    set_provenance: str | None = None
    tier_label: str | None = None
    note_suffix: str | None = None
    decision_ref: str | None = None

    @property
    def is_noop(self) -> bool:
        return not (
            self.exclude
            or self.fix_unit is not None
            or self.set_provenance is not None
            or self.tier_label is not None
        )

    def apply_to_fact(self, fact: dict[str, Any]) -> dict[str, Any]:
        """Return a shallow copy of ``fact`` with the overlay transforms applied."""
        if self.is_noop or self.exclude:
            return fact
        updated = dict(fact)
        if self.fix_unit is not None:
            from_unit, to_unit = self.fix_unit
            current = updated.get("unit")
            # Only rewrite when the recorded unit is exactly the drifted token.
            if isinstance(current, str) and current.strip().lower() == from_unit:
                updated["unit"] = to_unit
        if self.set_provenance is not None:
            updated["provenance_level"] = self.set_provenance
        return updated


class CurationOverlay:
    """Applies the Homeowner decisions as convert-time transforms.

    ``decide`` is a pure function of ``(file_key, fact_id, fact)`` plus the
    ``promoted_source_ids`` the adapter computes once from the same registry (the
    set that makes the D2B cascade a genuine dependency, not a hand list).  The
    default-constructed instance carries the exact approved decision set; the maps
    are exposed as constructor args solely so tests can build a tiny synthetic
    overlay.
    """

    def __init__(
        self,
        *,
        promote_verified_primary: frozenset[str] = PROMOTE_VERIFIED_PRIMARY,
        unit_fix: dict[str, tuple[str, str]] | None = None,
        strategic_doc: frozenset[str] = STRATEGIC_DOC,
        exclude: frozenset[str] = EXCLUDE,
        promote_interim_spec_dup: dict[str, str] | None = None,
    ) -> None:
        self.promote_verified_primary = promote_verified_primary
        self.unit_fix = dict(UNIT_FIX if unit_fix is None else unit_fix)
        self.strategic_doc = strategic_doc
        self.exclude = exclude
        self.promote_interim_spec_dup = dict(
            PROMOTE_INTERIM_SPEC_DUP
            if promote_interim_spec_dup is None
            else promote_interim_spec_dup,
        )

    # ----------------------------------------------------------------------- #
    # Promoted-capability resolution (drives the D2B cascade)
    # ----------------------------------------------------------------------- #
    @staticmethod
    def capability_is_promoted(fact: dict[str, Any]) -> bool:
        """True when a ``capabilities`` record is promoted/ready under the decisions.

        A capability is promoted when it is either already verified/approved, or a
        ``claim`` carrying a real (non-empty) ``evidence`` reference (Decision 1B).
        """
        prov = fact.get("provenance_level")
        if prov == "claim":
            evidence = fact.get("evidence")
            return isinstance(evidence, str) and bool(evidence.strip())
        return isinstance(prov, str) and prov in _VERIFIED_LEVELS

    def promoted_capability_ids(self, capabilities: list[dict[str, Any]]) -> frozenset[str]:
        """The set of capability ids the decisions promote (used to resolve D2B)."""
        return frozenset(
            str(cap["id"])
            for cap in capabilities
            if isinstance(cap, dict) and cap.get("id") and self.capability_is_promoted(cap)
        )

    # ----------------------------------------------------------------------- #
    # Decision RULE predicates
    # ----------------------------------------------------------------------- #
    @staticmethod
    def _promotable_l3_claim(file_key: str, fact: dict[str, Any]) -> bool:
        """Decision 2 RULE: an l3_facts *fact* (not a kernel_ref) with kernel
        ``claim`` provenance that already carries a real ``evidence_span``."""
        if file_key != "l3_facts" or "kernel_ref" in fact:
            return False
        if fact.get("provenance_level") != "claim":
            return False
        span = fact.get("evidence_span")
        return isinstance(span, str) and bool(span.strip())

    @staticmethod
    def _promotable_capability_claim(file_key: str, fact: dict[str, Any]) -> bool:
        """Decision 1B RULE: a capabilities record with ``claim`` provenance and a
        non-empty ``evidence`` reference."""
        if file_key != "capabilities":
            return False
        if fact.get("provenance_level") != "claim":
            return False
        evidence = fact.get("evidence")
        return isinstance(evidence, str) and bool(evidence.strip())

    @staticmethod
    def _kernel_ref_names_promoted_cap(
        fact: dict[str, Any],
        promoted_source_ids: frozenset[str],
    ) -> bool:
        """Decision 2B RULE support: does this kernel_ref's ``kernel_ref`` field name
        at least one promoted capability id?  Tokenized on the separators the kernel
        uses (whitespace / ``+`` / ``·``)."""
        if not promoted_source_ids:
            return False
        ref = fact.get("kernel_ref")
        if not isinstance(ref, str) or not ref.strip():
            return False
        tokens = ref.replace("·", " ").replace("+", " ").split()
        return any(token.strip() in promoted_source_ids for token in tokens)

    # ----------------------------------------------------------------------- #
    # Decision engine
    # ----------------------------------------------------------------------- #
    def decide(
        self,
        file_key: str,
        fact_id: str,
        fact: dict[str, Any],
        *,
        promoted_source_ids: frozenset[str] = frozenset(),
    ) -> OverlayDecision:
        # Decision 4/5 -- exclusion wins over everything.
        if fact_id in self.exclude:
            return OverlayDecision(exclude=True, decision_ref="D4-exclude")

        # Decision 1b -- unit-drift fix.
        if fact_id in self.unit_fix:
            return OverlayDecision(
                fix_unit=self.unit_fix[fact_id],
                decision_ref="D1b-unit-fix-lb-to-kg",
            )

        # Decision 1a -- inherit verified_primary from the resolved source record.
        if fact_id in self.promote_verified_primary:
            return OverlayDecision(
                set_provenance=_VERIFIED_PRIMARY,
                note_suffix=self._kernel_ref_suffix(fact, "inherits"),
                decision_ref="D1a-verified-primary-inherit",
            )

        # Decision 3 -- strategic doctrine grounded on a staged strategic doc.
        if fact_id in self.strategic_doc:
            return OverlayDecision(
                set_provenance=_APPROVED_INTERNAL,
                tier_label=TIER_STRATEGIC,
                note_suffix=self._kernel_ref_suffix(fact, "strategic-doc"),
                decision_ref="D3-strategic-doc",
            )

        # Decision 3B -- interim spec that duplicates an already-VERIFIED spec.
        if fact_id in self.promote_interim_spec_dup:
            return OverlayDecision(
                set_provenance=_APPROVED_INTERNAL,
                note_suffix=f"duplicates verified spec: {self.promote_interim_spec_dup[fact_id]}",
                decision_ref="D3B-interim-spec-duplicate-of-verified",
            )

        # Decision 1B -- capability claim with a real evidence reference (RULE).
        if self._promotable_capability_claim(file_key, fact):
            return OverlayDecision(
                set_provenance=_APPROVED_INTERNAL,
                note_suffix=self._evidence_suffix(fact),
                decision_ref="D1B-capability-claim-promoted",
            )

        # Decision 2B -- cascade: a curate kernel_ref whose resolved source record is
        # a now-promoted capability inherits soft + caveat (RULE, resolved against the
        # promoted-capability id set the adapter computed from the same registry).
        if (
            file_key == "l3_facts"
            and "kernel_ref" in fact
            and not fact.get("provenance_level")
            and self._kernel_ref_names_promoted_cap(fact, promoted_source_ids)
        ):
            return OverlayDecision(
                set_provenance=_APPROVED_INTERNAL,
                note_suffix=self._kernel_ref_suffix(fact, "cascade-from promoted capability"),
                decision_ref="D2B-cascade-from-promoted-cap",
            )

        # Decision 2 -- promote a claim-with-span (rule-selected).
        if self._promotable_l3_claim(file_key, fact):
            return OverlayDecision(
                set_provenance=_APPROVED_INTERNAL,
                note_suffix=(
                    "curator-promoted claim "
                    "(kernel claim -> approved_internal · double-check)"
                ),
                decision_ref="D2-claim-with-span-promoted",
            )

        return OverlayDecision()

    @staticmethod
    def _kernel_ref_suffix(fact: dict[str, Any], verb: str) -> str | None:
        ref = fact.get("kernel_ref")
        if isinstance(ref, str) and ref.strip():
            return f"{verb}: {ref.strip()}"
        return None

    @staticmethod
    def _evidence_suffix(fact: dict[str, Any]) -> str | None:
        """A deterministic note suffix built from the capability's real ``evidence``
        documentary reference (brochure / KB sheet / DCMA / patent).  Never invented:
        returns ``None`` when the record carries no evidence reference."""
        evidence = fact.get("evidence")
        if not isinstance(evidence, str) or not evidence.strip():
            return None
        collapsed = " ".join(evidence.split())
        if len(collapsed) > _EVIDENCE_NOTE_LIMIT:
            collapsed = collapsed[:_EVIDENCE_NOTE_LIMIT].rstrip() + "…"
        return f"evidence: {collapsed}"


# --------------------------------------------------------------------------- #
# Final disposition classifier (proves nothing is in limbo)
# --------------------------------------------------------------------------- #
# Each final disposition is (bucket, decision_ref, one-line reason).  ``bucket`` is
# one of the ledger's terminal states: every one of the 259 facts lands in exactly
# one -- ready (strict/soft/strategic), held (claim/derived), irreducible-gap, or
# excluded.  Ready facts are further attributed to the decision that produced them.

# Ready buckets
READY_STRICT = "ready-strict"
READY_SOFT = "ready-soft"
READY_STRATEGIC = "ready-strategic"
# Held / terminal buckets
HELD_CLAIM = "claim-held"
HELD_DERIVED = "derived-held"
IRREDUCIBLE = "irreducible-gap"
EXCLUDED = "excluded"


def final_disposition(
    *,
    file_key: str,
    fact_id: str,
    confidence_tier: str,
    kernel_provenance: str,
    primary_gap: str | None,
) -> tuple[str, str, str]:
    """Assign a fact's converted outcome to its FINAL disposition + one-line reason.

    Pure and total: returns a ``(bucket, decision_ref, reason)`` triple for EVERY
    possible outcome so the disposition ledger can prove no fact is left in limbo.
    """
    if confidence_tier == EXCLUDED:
        return (
            EXCLUDED,
            "D5",
            "toolkit/process reference (rtr-van-phong-nha-nuoc), not a SOT fact",
        )

    if confidence_tier == "strict":
        return (
            READY_STRICT,
            "D1b/native",
            "verified primary + verbatim source span + row locator (no caveat)",
        )

    if confidence_tier == "strategic":
        return (
            READY_STRATEGIC,
            "D3-strategic-doc",
            "grounded on a staged strategic doctrine doc + double-check caveat",
        )

    if confidence_tier == "soft":
        if fact_id in PROMOTE_INTERIM_SPEC_DUP:
            return (
                READY_SOFT,
                "D3B-interim-spec-duplicate",
                f"interim spec duplicates verified {PROMOTE_INTERIM_SPEC_DUP[fact_id]} "
                "-> approved_internal + caveat",
            )
        if file_key == "capabilities":
            return (
                READY_SOFT,
                "D1B-capability-claim-promoted",
                "capability claim carrying a real evidence reference -> approved_internal + caveat",
            )
        if file_key == "l3_facts":
            return (
                READY_SOFT,
                "D1a/D2/D2B",
                "l3 fact promoted (claim-with-span / verified-primary inherit / "
                "cascade from a promoted capability) + double-check caveat",
            )
        return (
            READY_SOFT,
            "native-soft",
            "verified/approved provenance + source, no formal span/locator -> soft + caveat",
        )

    if confidence_tier == "claim":
        if file_key in {"boms", "prices"}:
            return (
                HELD_CLAIM,
                "D3-hold-price-cost",
                "cost/price sensitive + fast drift; leader-zone; promote only after "
                "per-item currency confirmation",
            )
        if file_key == "specs":
            return (
                HELD_CLAIM,
                "D3-hold-interim-spec",
                "interim spec (status INT, no raw_text) — not primary-sourced; verify then promote",
            )
        if file_key == "derived_costs":
            return (
                HELD_DERIVED,
                "D4-keep-derived",
                "calculation, not a primary fact — computed layer, never frozen as a SOT fact",
            )
        return (HELD_CLAIM, "D3-hold", "kernel claim held for a curator promotion decision")

    # curate tier -> irreducible gap (or a derived calc that also lacks a source)
    named = IRREDUCIBLE_GAP.get(fact_id, f"unresolved: {primary_gap or 'gap'}")
    if file_key == "derived_costs":
        return (
            HELD_DERIVED,
            "D4+D6-derived-irreducible",
            f"calculation held as derived; irreducible gap — missing {named}",
        )
    return (IRREDUCIBLE, "D6-irreducible-gap", f"held; named missing field — {named}")
