"""Decide whether a provider listing is the same product variant as a canonical product.

Order of evidence:
1. Deterministic identifiers (GTIN / manufacturer model number) – match or hard mismatch.
2. Hard attribute conflicts (storage, RAM, tier, condition, generation, screen size, colour, brand) – never merge.
3. Token containment of the remaining name tokens + count of agreeing attributes → confidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.matching.attributes import Attributes


@dataclass
class MatchResult:
    confidence: float
    conflicts: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)

    @property
    def is_conflict(self) -> bool:
        return bool(self.conflicts)


def _containment(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# Sub-brands sold as the same product line (a "Xiaomi Redmi 13" is a "Redmi 13").
BRAND_FAMILIES = {"redmi": "xiaomi", "poco": "xiaomi", "mi": "xiaomi"}


def brand_family(b: str | None) -> str | None:
    return BRAND_FAMILIES.get(b, b) if b else b


def compare(
    a: Attributes,
    b: Attributes,
    ids_a: dict[str, str] | None = None,
    ids_b: dict[str, str] | None = None,
) -> MatchResult:
    ids_a = ids_a or {}
    ids_b = ids_b or {}
    evidence: dict = {}
    conflicts: list[str] = []

    for kind in ("gtin", "model_number"):
        if ids_a.get(kind) and ids_b.get(kind):
            if ids_a[kind].strip().lower() == ids_b[kind].strip().lower():
                # Identifier match still must not cross condition (refurb vs new share GTINs).
                if a.condition != b.condition:
                    return MatchResult(0.0, ["condition"], {kind: "equal", "condition": "differs"})
                return MatchResult(1.0, [], {kind: "equal"})
            return MatchResult(0.0, [kind], {kind: "differs"})

    def check(name: str, va, vb) -> None:  # noqa: ANN001
        if va is not None and vb is not None:
            if va != vb:
                conflicts.append(name)
                evidence[name] = f"{va} != {vb}"
            else:
                evidence[name] = "equal"

    check("brand", brand_family(a.brand), brand_family(b.brand))
    check("storage_gb", a.storage_gb, b.storage_gb)
    check("ram_gb", a.ram_gb, b.ram_gb)
    check("colour", a.colour, b.colour)
    if a.screen_inches is not None and b.screen_inches is not None and abs(a.screen_inches - b.screen_inches) > 0.25:
        conflicts.append("screen_inches")
    if a.condition != b.condition:
        conflicts.append("condition")
    if a.region != b.region:
        conflicts.append("region")
        evidence["region"] = f"{a.region} != {b.region}"
    if a.kind != b.kind:
        conflicts.append("kind")
        evidence["kind"] = f"{a.kind} != {b.kind}"
    if a.tier != b.tier:
        conflicts.append("tier")
        evidence["tier"] = f"{sorted(a.tier)} != {sorted(b.tier)}"
    # Model/generation tokens: one side may carry extra marketing tokens (e.g. chip name),
    # but they must not contradict (iPhone 15 vs 16).
    if a.model_tokens and b.model_tokens:
        if not (a.model_tokens <= b.model_tokens or b.model_tokens <= a.model_tokens):
            conflicts.append("model_tokens")
            evidence["model_tokens"] = f"{sorted(a.model_tokens)} != {sorted(b.model_tokens)}"
    elif a.model_tokens or b.model_tokens:
        evidence["model_tokens"] = "missing_on_one_side"

    if conflicts:
        return MatchResult(0.0, conflicts, evidence)

    # Containment alone lets a short title ("iPhone 16") match any long title that mentions it,
    # so it is blended with Jaccard similarity, which penalises the extra unmatched words.
    contain = _containment(a.core_tokens, b.core_tokens)
    jac = _jaccard(a.core_tokens, b.core_tokens)
    name_sim = 0.5 * contain + 0.5 * jac
    evidence["name_containment"] = round(contain, 3)
    evidence["name_jaccard"] = round(jac, 3)
    agreeing = sum(1 for k in ("brand", "storage_gb", "ram_gb", "colour") if evidence.get(k) == "equal")
    if a.model_tokens and a.model_tokens == b.model_tokens:
        agreeing += 1
    evidence["agreeing_attributes"] = agreeing

    confidence = 0.65 * name_sim + 0.08 * agreeing
    if a.brand is None or b.brand is None:
        confidence -= 0.1
    if not (a.model_tokens and b.model_tokens):
        confidence -= 0.1
    # Storage known on one side only ("iPhone 17 Pro" vs "iPhone 17 Pro 256GB"): it may be a different variant,
    # so such a match is never verified on name similarity alone.
    if (a.storage_gb is None) != (b.storage_gb is None):
        confidence = min(confidence, 0.75)
        evidence["storage"] = "known_on_one_side_only"
    confidence = max(0.0, min(0.99, confidence))
    return MatchResult(round(confidence, 3), [], evidence)
