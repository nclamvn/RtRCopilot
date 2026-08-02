"""TIP-013B · Homeowner curation-decision OVERLAY (DRY-RUN ONLY).

This module encodes the FOUR curation decisions the Homeowner approved on
02/08/2026 as an explicit, auditable *overlay* the migration adapter reads at
convert time.  The read-only kernel snapshot under ``kernel-real/`` is NEVER
modified: the unit fix, the promotions, the strategic tier and the exclusion are
transforms applied to the *emitted V2 packages* only.  Nothing here activates,
applies, writes a production database, or writes back to the kernel.

The four decisions
------------------
1. **Promote to ready** the 5 Group-1 ``kernel_ref`` facts that resolve to
   ``verified_primary`` (they inherit their source record's verified provenance)
   -> overlay injects ``provenance_level = verified_primary`` so the adapter emits
   them as ``soft``-ready (no formal span/locator on a kernel_ref) with the
   honest ``needs_double_check`` marker and a source note naming the kernel
   record they inherit from.  AND fix the 3 HERA unit-drift facts (``lb`` -> ``kg``,
   evidence being each fact's own ``raw_text`` + ``notes``) -> the drift clears and
   they become ``strict`` (verified span + row locator), NO caveat.
2. **Promote the 79 l3-claim facts that already carry an ``evidence_span``** to
   ``soft``-ready grounded on that real span, WITH ``needs_double_check = true``
   (curator promote-with-caveat).  Selected by RULE, not a hand list, so the set
   is exactly the 79 that qualify.  Every *other* claim stays ``claim``.
3. **The 6 strategic-doc ``kernel_ref`` facts** -> a new ``strategic`` tier,
   grounded on the staged strategic docs named in each fact's ``kernel_ref``, WITH
   the double-check caveat.  Ready-with-caveat.
4. **Exclude ``L3R.K.005``** (its ``kernel_ref`` is the toolkit
   ``rtr-van-phong-nha-nuoc`` -- a process reference, not a fact) from the SOT
   fact set entirely: it is emitted in no tier and no package.

Honesty
-------
Every promoted/soft/strategic record still references a REAL source: the real
``evidence_span`` text (decision 2), the real source record / kernel_ref
(decision 1a), or the real staged strategic doc named in ``kernel_ref``
(decision 3).  Nothing is fabricated.  A promoted claim maps to
``approved_internal`` (an internal curator-approval state, NOT a masquerading
verified state) so the publish gate's ``claim_masquerades_as_approved`` guard
stays meaningful; the double-check caveat and the real span ride with it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# --------------------------------------------------------------------------- #
# Decision 1a -- 5 kernel_ref facts that resolve to verified_primary.  Each
# inherits its source record's verified provenance (resolution table in
# vibecode_v2/TIP-013B_KERNEL_REF_RESOLUTION.md).  Value = the kernel record the
# fact's ``kernel_ref`` names (recorded in the source note for audit).
# --------------------------------------------------------------------------- #
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

# Decision 4 -- excluded entirely from the SOT fact set.
EXCLUDE: frozenset[str] = frozenset({"L3R.K.005"})

# V2 provenance a promoted kernel-claim / strategic doctrine maps to: an internal
# curator-approval state (NOT a verified-without-evidence masquerade).
_APPROVED_INTERNAL = "approved_internal"
_VERIFIED_PRIMARY = "verified_primary"

# Tier label for decision 3.  Kept as a string so the overlay does not import the
# adapter (one-way dependency: the adapter imports the overlay, never the reverse).
TIER_STRATEGIC = "strategic"


@dataclass(frozen=True)
class OverlayDecision:
    """The overlay's verdict for a single fact (empty when no decision applies).

    ``apply_to_fact`` returns a *copy* of the fact with the unit fix and/or
    provenance injection applied; the original kernel-loaded dict is never mutated.
    ``tier_label`` (when ``strategic``) relabels an otherwise-``soft`` ready record.
    ``note_suffix`` is appended to the honest source note for audit (which kernel
    record / strategic doc the promotion inherits from).  ``decision_ref`` names the
    Homeowner decision for the readiness report.
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
    """Applies the 4 Homeowner decisions as convert-time transforms.

    Deterministic and pure: ``decide`` is a function of ``(file_key, fact_id,
    fact)`` only.  Default-constructed instances carry the exact approved decision
    set; the maps are exposed as constructor args solely so tests can build a tiny
    synthetic overlay.
    """

    def __init__(
        self,
        *,
        promote_verified_primary: frozenset[str] = PROMOTE_VERIFIED_PRIMARY,
        unit_fix: dict[str, tuple[str, str]] | None = None,
        strategic_doc: frozenset[str] = STRATEGIC_DOC,
        exclude: frozenset[str] = EXCLUDE,
    ) -> None:
        self.promote_verified_primary = promote_verified_primary
        self.unit_fix = dict(UNIT_FIX if unit_fix is None else unit_fix)
        self.strategic_doc = strategic_doc
        self.exclude = exclude

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

    def decide(
        self,
        file_key: str,
        fact_id: str,
        fact: dict[str, Any],
    ) -> OverlayDecision:
        # Decision 4 -- exclusion wins over everything.
        if fact_id in self.exclude:
            return OverlayDecision(exclude=True, decision_ref="D4-exclude")

        # Decision 1b -- unit-drift fix (may co-apply with nothing else here).
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
