"""
KYC Onboarding Recommendation Engine.
Decision logic based on risk level and investigation findings.
"""

from constants import FAILED_SENTINEL_KEY
from models import (
    AdverseMediaLevel,
    DispositionStatus,
    InvestigationResults,
    OnboardingDecision,
    PEPLevel,
    RiskAssessment,
    RiskLevel,
)


def recommend_decision(
    risk_assessment: RiskAssessment,
    investigation: InvestigationResults = None,
) -> tuple[OnboardingDecision, str, list[str]]:
    """
    Determine onboarding recommendation based on risk and findings.

    Returns:
        Tuple of (decision, reasoning, conditions)
    """
    conditions = []
    flags = []

    # Check for hard blocks
    if investigation:
        # Confirmed sanctions match = automatic decline
        for sanctions_result in [investigation.individual_sanctions, investigation.entity_sanctions]:
            if sanctions_result and sanctions_result.disposition == DispositionStatus.CONFIRMED_MATCH:
                return (
                    OnboardingDecision.DECLINE,
                    "Confirmed sanctions match — onboarding prohibited",
                    [],
                )

        # Potential sanctions match = escalate
        for sanctions_result in [investigation.individual_sanctions, investigation.entity_sanctions]:
            if sanctions_result and sanctions_result.disposition == DispositionStatus.POTENTIAL_MATCH:
                flags.append("Potential sanctions match requires resolution")

        # UBO sanctions — confirmed match on any beneficial owner is a hard block
        # Note: ubo_screening values are model_dump(mode="json") dicts, so
        # disposition is always a string (not a DispositionStatus enum).
        if investigation.ubo_screening:
            for ubo_name, ubo_data in investigation.ubo_screening.items():
                sanctions = ubo_data.get("sanctions", {}) if isinstance(ubo_data, dict) else {}
                if not sanctions.get(FAILED_SENTINEL_KEY):
                    disp = str(sanctions.get("disposition", "")).upper()
                    if disp == "CONFIRMED_MATCH":
                        return (OnboardingDecision.DECLINE, f"UBO {ubo_name} — confirmed sanctions match", [])
                    if disp == "POTENTIAL_MATCH":
                        flags.append(f"UBO {ubo_name} — potential sanctions match")

        # FATF grey/black list — auto-escalate
        if investigation.jurisdiction_risk:
            jr = investigation.jurisdiction_risk
            if jr.fatf_black_list:
                flags.append(f"FATF black list: {', '.join(jr.fatf_black_list)}")
            elif jr.fatf_grey_list:
                flags.append(f"FATF grey list: {', '.join(jr.fatf_grey_list)}")

        # PEP detected = conditions
        if investigation.pep_classification:
            pep = investigation.pep_classification
            if pep.detected_level != PEPLevel.NOT_PEP:
                flags.append(f"PEP detected: {pep.detected_level.value}")
                conditions.append("Enhanced due diligence measures applied")
                conditions.append("Senior management approval required")

        # Material adverse media = escalate
        for adverse in [investigation.individual_adverse_media, investigation.business_adverse_media]:
            if adverse and adverse.overall_level in (AdverseMediaLevel.MATERIAL_CONCERN, AdverseMediaLevel.HIGH_RISK):
                flags.append(f"Adverse media: {adverse.overall_level.value}")

        # EDD required
        if investigation.edd_requirements:
            edd = investigation.edd_requirements
            if isinstance(edd, dict) and edd.get("edd_required"):
                conditions.append("Enhanced due diligence documentation required")

    # Decision based on risk level + flags
    if risk_assessment.risk_level == RiskLevel.CRITICAL:
        if flags:
            return (
                OnboardingDecision.DECLINE,
                f"Critical risk with {len(flags)} additional flag(s): {'; '.join(flags)}",
                [],
            )
        return (
            OnboardingDecision.ESCALATE,
            "Critical risk level requires senior management review",
            conditions,
        )

    elif risk_assessment.risk_level == RiskLevel.HIGH:
        if any("sanctions" in f.lower() for f in flags):
            return (
                OnboardingDecision.ESCALATE,
                f"High risk with sanctions concern: {'; '.join(flags)}",
                conditions,
            )
        return (
            OnboardingDecision.CONDITIONAL,
            f"High risk — conditional approval with {len(conditions)} condition(s)",
            conditions or ["Enhanced monitoring required", "Source of wealth documentation"],
        )

    elif risk_assessment.risk_level == RiskLevel.MEDIUM:
        if flags:
            return (
                OnboardingDecision.CONDITIONAL,
                f"Medium risk with {len(flags)} flag(s) requiring conditions",
                conditions or ["Standard enhanced monitoring"],
            )
        return (
            OnboardingDecision.APPROVE,
            "Medium risk with no significant flags — standard onboarding",
            conditions,
        )

    else:  # LOW
        if flags:
            return (
                OnboardingDecision.CONDITIONAL,
                f"Low risk but {len(flags)} flag(s) identified",
                conditions,
            )
        return (
            OnboardingDecision.APPROVE,
            "Low risk, all screenings clear — standard onboarding approved",
            [],
        )
