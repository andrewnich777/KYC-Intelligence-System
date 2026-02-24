"""
Evidence Classification System.

Classifies claims based on evidence quality using [V]/[S]/[I]/[U] badges:
- [V] Verified: URL + direct quote + Tier 0/1 source
- [S] Sourced: URL + excerpt + Tier 1/2 source
- [I] Inferred: Derived from signals, no direct evidence
- [U] Unknown: Explicitly searched but not found
- +C: Conflicted (optional flag when sources disagree)
"""

from typing import Any

from models import Confidence, EvidenceClass, SourceTier


def classify_claim(claim: Any) -> tuple[EvidenceClass, bool]:
    """
    Classify a claim based on evidence quality.

    Args:
        claim: A Claim object with evidence list, confidence, etc.

    Returns:
        Tuple of (EvidenceClass, has_conflict)
    """
    # Handle None or missing claim
    if claim is None:
        return EvidenceClass.UNKNOWN, False

    # Check for conflict flag (if exists on claim)
    has_conflict = getattr(claim, 'has_conflict', False)

    # Get evidence details
    evidence_list = getattr(claim, 'evidence', [])
    if not evidence_list:
        return EvidenceClass.UNKNOWN, has_conflict

    first_evidence = evidence_list[0]
    has_url = bool(getattr(first_evidence, 'url', None))
    quote = getattr(first_evidence, 'quote', '')
    has_quote = bool(quote and len(quote) > 20)
    source_tier = getattr(first_evidence, 'source_tier', SourceTier.TIER_2)

    # Tier 3 sources: cap at SOURCED (never VERIFIED); without URL = INFERRED
    if source_tier == SourceTier.TIER_3:
        if has_url:
            return EvidenceClass.SOURCED, has_conflict
        return EvidenceClass.INFERRED, has_conflict

    # [V] Verified: URL + substantial quote + Tier 0/1 source
    if has_url and has_quote and source_tier in [SourceTier.TIER_0, SourceTier.TIER_1]:
        return EvidenceClass.VERIFIED, has_conflict

    # [S] Sourced: URL + any content + Tier 1/2 source
    if has_url:
        return EvidenceClass.SOURCED, has_conflict

    # [I] Inferred: Has some signals but no direct URL evidence
    confidence = getattr(claim, 'confidence', Confidence.LOW)
    inferred_from = getattr(claim, 'inferred_from', [])
    if inferred_from or confidence in [Confidence.HIGH, Confidence.MEDIUM]:
        return EvidenceClass.INFERRED, has_conflict

    # [U] Unknown: No evidence found
    return EvidenceClass.UNKNOWN, has_conflict


def classify_integration(integration: Any) -> tuple[EvidenceClass, bool]:
    """
    Classify an Integration object.

    Integrations have slightly different structure than Claims.
    """
    if integration is None:
        return EvidenceClass.UNKNOWN, False

    evidence = getattr(integration, 'evidence', None)
    confidence = getattr(integration, 'confidence', Confidence.MEDIUM)

    if evidence:
        has_url = bool(getattr(evidence, 'url', None))
        quote = getattr(evidence, 'quote', '')
        has_quote = bool(quote and len(quote) > 20)
        source_tier = getattr(evidence, 'source_tier', SourceTier.TIER_2)

        if has_url and has_quote and source_tier in [SourceTier.TIER_0, SourceTier.TIER_1]:
            return EvidenceClass.VERIFIED, False
        if has_url:
            return EvidenceClass.SOURCED, False

    # Based on confidence level for inferred
    if confidence in [Confidence.HIGH, Confidence.MEDIUM]:
        return EvidenceClass.INFERRED, False

    return EvidenceClass.UNKNOWN, False


def classify_certification(cert: Any) -> tuple[EvidenceClass, bool]:
    """
    Classify a Certification object.
    """
    if cert is None:
        return EvidenceClass.UNKNOWN, False

    evidence = getattr(cert, 'evidence', None)
    status = getattr(cert, 'status', 'claimed')

    if evidence:
        has_url = bool(getattr(evidence, 'url', None))
        quote = getattr(evidence, 'quote', '')
        bool(quote and len(quote) > 10)  # Shorter threshold for certs
        source_tier = getattr(evidence, 'source_tier', SourceTier.TIER_2)

        if has_url and source_tier == SourceTier.TIER_0:
            return EvidenceClass.VERIFIED, False
        if has_url:
            return EvidenceClass.SOURCED, False

    # Status-based fallback
    if status in ['certified', 'verified']:
        return EvidenceClass.SOURCED, False
    if status in ['claimed', 'in_progress']:
        return EvidenceClass.INFERRED, False

    return EvidenceClass.UNKNOWN, False


def format_badge(evidence_class: EvidenceClass, has_conflict: bool = False) -> str:
    """
    Format the evidence classification badge.

    Examples:
        format_badge(EvidenceClass.VERIFIED, False) -> "[V]"
        format_badge(EvidenceClass.SOURCED, True) -> "[SC]"
    """
    badge = f"[{evidence_class.value}"
    if has_conflict:
        badge += "C"
    badge += "]"
    return badge


def get_evidence_legend() -> list[str]:
    """
    Return markdown lines for the evidence legend.
    """
    return [
        "",
        "*Evidence: [V] Verified | [S] Sourced | [I] Inferred | [U] Unknown | +C = Conflicted*",
    ]


def get_evidence_legend_full() -> list[str]:
    """
    Return full markdown legend with descriptions.
    """
    return [
        "",
        "---",
        "**Evidence Legend:**",
        "- **[V]** Verified: Direct quote from official source",
        "- **[S]** Sourced: URL evidence, indirect/secondary",
        "- **[I]** Inferred: Derived from multiple signals",
        "- **[U]** Unknown: Searched but not found",
        "- **+C** Conflicted: Credible sources disagree",
        ""
    ]
