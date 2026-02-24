"""
Enhanced Due Diligence (EDD) Requirements.

Determines whether EDD is required based on client risk profile,
investigation findings, and regulatory triggers. Specifies the
specific EDD measures that must be applied.
Pure deterministic logic, no API calls.
"""

from datetime import UTC, datetime, timedelta

from constants import EDD_RISK_SCORE_THRESHOLD, FAILED_SENTINEL_KEY, UBO_COMPLEX_OWNERSHIP_THRESHOLD
from models import (
    AdverseMediaLevel,
    BusinessClient,
    DispositionStatus,
    IndividualClient,
    InvestigationResults,
    RiskAssessment,
    RiskLevel,
)
from utilities.reference_data import FATF_BLACK_LIST, FATF_GREY_LIST
from utilities.shared_checks import check_pep_edd_triggers


def assess_edd_requirements(
    client,
    risk_assessment: RiskAssessment,
    investigation: InvestigationResults = None,
) -> dict:
    """
    Determine if Enhanced Due Diligence (EDD) is required and what measures apply.

    Returns dict with:
        edd_required: bool — whether EDD is triggered
        triggers: list of str — reasons EDD is required
        measures: list of str — specific EDD measures to apply
        approval_required: str or None — level of approval needed
        monitoring_frequency: str — ongoing monitoring schedule
        evidence: list of EvidenceRecord-compatible dicts

    Triggers (any one = EDD required):
    - Foreign PEP (permanent EDD)
    - Domestic PEP or HIO (5-year EDD from leaving office)
    - Client from FATF grey/black list country
    - Potential or confirmed sanctions match
    - Material or high-risk adverse media
    - Risk score >= 36 (HIGH or CRITICAL)
    - Large or unusual transactions relative to profile
    - Business with complex ownership structure (>3 layers or >5 beneficial owners)
    """
    triggers = []
    measures = []
    evidence = []
    timestamp = datetime.now(UTC).isoformat()

    # Get entity name for evidence records
    if isinstance(client, IndividualClient):
        entity_name = client.full_name
        entity_context = "individual client"
    elif isinstance(client, BusinessClient):
        entity_name = client.legal_name
        entity_context = "business client"
    else:
        entity_name = "unknown"
        entity_context = "unknown client type"

    # =========================================================================
    # Trigger Assessment
    # =========================================================================

    # Trigger 1: PEP status
    _check_pep_triggers(client, investigation, triggers)

    # Trigger 2: FATF grey/black list countries
    _check_fatf_country_triggers(client, triggers)

    # Trigger 3: Sanctions matches
    _check_sanctions_triggers(investigation, triggers)

    # Trigger 4: Adverse media
    _check_adverse_media_triggers(investigation, triggers)

    # Trigger 5: Risk score threshold
    if risk_assessment.total_score >= EDD_RISK_SCORE_THRESHOLD:
        level = risk_assessment.risk_level.value
        triggers.append(
            f"Risk score {risk_assessment.total_score} ({level}) "
            "exceeds EDD threshold of 36"
        )

    # Trigger 6: Transaction anomalies
    _check_transaction_triggers(client, triggers)

    # Trigger 7: Complex ownership (business only)
    _check_ownership_complexity_triggers(client, triggers)

    # =========================================================================
    # EDD Measures
    # =========================================================================
    edd_required = len(triggers) > 0

    if edd_required:
        measures = _determine_edd_measures(
            client, risk_assessment, investigation, triggers
        )

    # =========================================================================
    # Approval Requirements
    # =========================================================================
    approval_required = _determine_approval_level(
        client, risk_assessment, investigation, triggers
    )

    # =========================================================================
    # Monitoring Frequency
    # =========================================================================
    monitoring_frequency = _determine_monitoring_frequency(risk_assessment, edd_required)

    # =========================================================================
    # Evidence Records
    # =========================================================================
    entity_key = entity_name.lower().replace(" ", "_")

    if edd_required:
        evidence.append({
            "evidence_id": f"edd_required_{entity_key}",
            "source_type": "utility",
            "source_name": "edd_requirements",
            "entity_screened": entity_name,
            "entity_context": entity_context,
            "claim": (
                f"EDD required: {len(triggers)} trigger(s) identified. "
                f"{len(measures)} measures prescribed. "
                f"Monitoring frequency: {monitoring_frequency}."
            ),
            "evidence_level": "S",
            "supporting_data": [
                {"triggers": triggers},
                {"measures": measures},
                {"approval_required": approval_required},
                {"monitoring_frequency": monitoring_frequency},
            ],
            "disposition": "PENDING_REVIEW",
            "confidence": "HIGH",
            "timestamp": timestamp,
        })
    else:
        evidence.append({
            "evidence_id": f"edd_not_required_{entity_key}",
            "source_type": "utility",
            "source_name": "edd_requirements",
            "entity_screened": entity_name,
            "entity_context": entity_context,
            "claim": (
                "EDD not required based on current assessment. "
                f"Risk score: {risk_assessment.total_score} "
                f"({risk_assessment.risk_level.value}). "
                f"Monitoring frequency: {monitoring_frequency}."
            ),
            "evidence_level": "S",
            "supporting_data": [
                {"risk_score": risk_assessment.total_score},
                {"risk_level": risk_assessment.risk_level.value},
                {"monitoring_frequency": monitoring_frequency},
            ],
            "disposition": "CLEAR",
            "confidence": "HIGH",
            "timestamp": timestamp,
        })

    # Monitoring schedule with computed next review date
    freq_days_map = {
        "monthly": 30,
        "quarterly": 90,
        "semi_annual": 180,
        "annual": 365,
    }
    freq_days = freq_days_map.get(monitoring_frequency, 365)
    monitoring_schedule = {
        "frequency": monitoring_frequency,
        "next_review_date": (datetime.now() + timedelta(days=freq_days)).strftime("%Y-%m-%d"),
        "review_interval_days": freq_days,
    }

    return {
        "edd_required": edd_required,
        "triggers": triggers,
        "measures": measures,
        "approval_required": approval_required,
        "monitoring_frequency": monitoring_frequency,
        "monitoring_schedule": monitoring_schedule,
        "evidence": evidence,
    }


# =============================================================================
# Trigger Checks
# =============================================================================

def _check_pep_triggers(client, investigation, triggers: list) -> None:
    """Check PEP-related EDD triggers (delegates to shared_checks)."""
    # If PEP agent failed entirely, trigger EDD since we cannot confirm clear
    if investigation and "PEPDetection" in (investigation.failed_agents or []):
        triggers.append(
            "PEP screening agent failed — EDD required as precaution "
            "(cannot confirm non-PEP status)"
        )
    pep_triggers = check_pep_edd_triggers(client, investigation)
    for pt in pep_triggers:
        trigger_text = pt["trigger"]
        if trigger_text not in triggers:
            triggers.append(trigger_text)


def _check_fatf_country_triggers(client, triggers: list) -> None:
    """Check FATF grey/black list country triggers."""
    countries_to_check = set()

    if isinstance(client, IndividualClient):
        if client.citizenship:
            countries_to_check.add(client.citizenship)
        if client.country_of_residence:
            countries_to_check.add(client.country_of_residence)
        if client.country_of_birth:
            countries_to_check.add(client.country_of_birth)
        countries_to_check.update(client.tax_residencies)
    elif isinstance(client, BusinessClient):
        countries_to_check.update(client.countries_of_operation)
        if client.incorporation_jurisdiction:
            countries_to_check.add(client.incorporation_jurisdiction)
        for ubo in client.beneficial_owners:
            if ubo.citizenship:
                countries_to_check.add(ubo.citizenship)
            if ubo.country_of_residence:
                countries_to_check.add(ubo.country_of_residence)

    for country in countries_to_check:
        if country in FATF_BLACK_LIST:
            triggers.append(
                f"FATF black list country: {country} — high-risk jurisdiction"
            )
        elif country in FATF_GREY_LIST:
            triggers.append(
                f"FATF grey list country: {country} — increased monitoring jurisdiction"
            )


def _check_sanctions_triggers(investigation, triggers: list) -> None:
    """Check sanctions match triggers."""
    if not investigation:
        return

    sanctions_results = []
    if investigation.individual_sanctions:
        sanctions_results.append(investigation.individual_sanctions)
    if investigation.entity_sanctions:
        sanctions_results.append(investigation.entity_sanctions)

    for sr in sanctions_results:
        # Defense-in-depth: if all evidence records are CLEAR with no matches,
        # skip trigger even if agent-level disposition is stale
        if sr.evidence_records and not sr.matches:
            all_clear = all(
                getattr(er, 'disposition', None) == DispositionStatus.CLEAR
                for er in sr.evidence_records
            )
            if all_clear:
                continue
        if sr.disposition in (
            DispositionStatus.POTENTIAL_MATCH,
            DispositionStatus.CONFIRMED_MATCH,
            DispositionStatus.PENDING_REVIEW,
        ):
            triggers.append(
                f"Sanctions screening: {sr.disposition.value} for "
                f"'{sr.entity_screened}'"
            )

    # Check UBO sanctions
    if investigation.ubo_screening:
        for ubo_name, ubo_results in investigation.ubo_screening.items():
            if isinstance(ubo_results, dict) and "sanctions" in ubo_results:
                sanctions_data = ubo_results["sanctions"]
                if isinstance(sanctions_data, dict):
                    # Failed UBO screening → trigger EDD (cannot confirm clean)
                    if sanctions_data.get(FAILED_SENTINEL_KEY):
                        triggers.append(
                            f"UBO sanctions screening failed for '{ubo_name}' — cannot confirm clear"
                        )
                        continue
                    disp = sanctions_data.get("disposition", "")
                    if disp in ("POTENTIAL_MATCH", "CONFIRMED_MATCH", "PENDING_REVIEW"):
                        triggers.append(
                            f"UBO sanctions: {disp} for '{ubo_name}'"
                        )


def _check_adverse_media_triggers(investigation, triggers: list) -> None:
    """Check adverse media triggers (main client + UBO)."""
    if not investigation:
        return

    media_results = []
    if investigation.individual_adverse_media:
        media_results.append(investigation.individual_adverse_media)
    if investigation.business_adverse_media:
        media_results.append(investigation.business_adverse_media)

    for mr in media_results:
        if mr.overall_level == AdverseMediaLevel.HIGH_RISK:
            triggers.append(
                f"High-risk adverse media for '{mr.entity_screened}'"
            )
        elif mr.overall_level == AdverseMediaLevel.MATERIAL_CONCERN:
            triggers.append(
                f"Material adverse media concern for '{mr.entity_screened}'"
            )

    # Check UBO adverse media
    if investigation.ubo_screening:
        for ubo_name, ubo_results in investigation.ubo_screening.items():
            if not isinstance(ubo_results, dict) or "adverse_media" not in ubo_results:
                continue
            media_data = ubo_results["adverse_media"]
            if not isinstance(media_data, dict):
                continue
            # Failed UBO adverse media screening → trigger EDD
            if media_data.get(FAILED_SENTINEL_KEY):
                triggers.append(
                    f"UBO adverse media screening failed for '{ubo_name}' — cannot confirm clear"
                )
                continue
            level = media_data.get("overall_level", "CLEAR")
            if level == "HIGH_RISK":
                triggers.append(
                    f"High-risk adverse media for UBO '{ubo_name}'"
                )
            elif level == "MATERIAL_CONCERN":
                triggers.append(
                    f"Material adverse media concern for UBO '{ubo_name}'"
                )


def _check_transaction_triggers(client, triggers: list) -> None:
    """Check for unusual transaction patterns relative to profile."""
    if isinstance(client, IndividualClient):
        for acct in client.account_requests:
            if acct.initial_deposit and client.annual_income and client.annual_income > 0:
                ratio = acct.initial_deposit / client.annual_income
                if ratio > 10:
                    triggers.append(
                        f"Initial deposit (${acct.initial_deposit:,.0f}) is "
                        f"{ratio:.0f}x annual income — unusual relative to profile"
                    )
    elif isinstance(client, BusinessClient):
        if (
            client.expected_transaction_volume
            and client.annual_revenue
            and client.annual_revenue > 0
        ):
            ratio = client.expected_transaction_volume / client.annual_revenue
            if ratio > 10:
                triggers.append(
                    f"Expected transaction volume "
                    f"(${client.expected_transaction_volume:,.0f}) is "
                    f"{ratio:.0f}x annual revenue — unusual relative to profile"
                )


def _check_ownership_complexity_triggers(client, triggers: list) -> None:
    """Check for complex ownership structures (business only)."""
    if not isinstance(client, BusinessClient):
        return

    num_ubos = len(client.beneficial_owners)

    if num_ubos > UBO_COMPLEX_OWNERSHIP_THRESHOLD:
        triggers.append(
            f"Complex ownership structure: {num_ubos} beneficial owners declared"
        )
    elif num_ubos == 0:
        triggers.append(
            "No beneficial owners declared — potential opacity in ownership structure"
        )

    # Check for multi-jurisdiction UBOs (proxy for layered structures)
    if num_ubos > 0:
        ubo_countries = set()
        for ubo in client.beneficial_owners:
            if ubo.citizenship:
                ubo_countries.add(ubo.citizenship)
            if ubo.country_of_residence:
                ubo_countries.add(ubo.country_of_residence)

        # Remove Canada from count
        ubo_countries_non_ca = {
            c for c in ubo_countries if c.lower() not in ("canada", "ca")
        }
        if len(ubo_countries_non_ca) > 3:
            triggers.append(
                f"Multi-jurisdictional ownership: beneficial owners across "
                f"{len(ubo_countries_non_ca)} non-Canadian jurisdictions"
            )


# =============================================================================
# EDD Measure Determination
# =============================================================================

def _determine_edd_measures(
    client,
    risk_assessment: RiskAssessment,
    investigation,
    triggers: list,
) -> list:
    """Determine specific EDD measures based on triggers."""
    measures = []

    # Always required for EDD
    measures.append(
        "Enhanced source of wealth documentation — "
        "obtain detailed explanation and supporting evidence"
    )
    measures.append(
        "Corroborate source of funds through independent sources "
        "(bank statements, tax returns, financial statements)"
    )
    measures.append(
        "Document EDD rationale and findings in client file"
    )

    # PEP-specific measures
    pep_triggers = [t for t in triggers if "PEP" in t.upper() or "HIO" in t.upper()]
    if pep_triggers:
        measures.append(
            "Senior management approval required for relationship establishment"
        )
        measures.append(
            "Establish source of wealth independent of client representations"
        )
        measures.append(
            "Conduct enhanced ongoing monitoring of transactions"
        )

    # Sanctions-specific measures
    sanctions_triggers = [t for t in triggers if "sanctions" in t.lower()]
    if sanctions_triggers:
        measures.append(
            "URGENT: Escalate sanctions match to Compliance Officer immediately"
        )
        measures.append(
            "Do not proceed with transaction until sanctions disposition is resolved"
        )
        measures.append(
            "Document sanctions screening results and disposition reasoning"
        )

    # FATF country measures
    fatf_triggers = [t for t in triggers if "FATF" in t]
    if fatf_triggers:
        measures.append(
            "Obtain additional information on purpose and intended nature "
            "of business relationship"
        )
        measures.append(
            "Conduct enhanced monitoring of transactions involving "
            "high-risk jurisdictions"
        )
        for t in fatf_triggers:
            if "black list" in t:
                measures.append(
                    "Apply countermeasures as directed by FINTRAC for "
                    "FATF black list jurisdictions"
                )
                break

    # Adverse media measures
    media_triggers = [t for t in triggers if "adverse media" in t.lower()]
    if media_triggers:
        measures.append(
            "Review and document all identified adverse media articles"
        )
        measures.append(
            "Assess relevance and recency of adverse media to current "
            "business relationship"
        )

    # High risk score measures
    if risk_assessment.risk_level == RiskLevel.CRITICAL:
        measures.append(
            "Senior management approval required (CRITICAL risk level)"
        )
        measures.append(
            "Consider whether to proceed with or terminate the relationship"
        )

    # Business-specific measures
    if isinstance(client, BusinessClient):
        ownership_triggers = [
            t for t in triggers if "ownership" in t.lower() or "beneficial owner" in t.lower()
        ]
        if ownership_triggers:
            measures.append(
                "Obtain corporate structure chart showing all ownership layers"
            )
            measures.append(
                "Verify beneficial ownership through independent corporate registry searches"
            )
        measures.append(
            "On-site verification of business premises (if feasible)"
        )

    # Transaction-related measures
    transaction_triggers = [
        t for t in triggers if "transaction" in t.lower() or "deposit" in t.lower()
    ]
    if transaction_triggers:
        measures.append(
            "Obtain detailed explanation of expected transaction patterns"
        )
        measures.append(
            "Set transaction monitoring alerts at appropriate thresholds"
        )

    return measures


def _determine_approval_level(
    client, risk_assessment, investigation, triggers
) -> str | None:
    """Determine what level of approval is required."""
    # PEP always requires senior management
    pep_triggers = [t for t in triggers if "PEP" in t.upper() or "HIO" in t.upper()]
    if pep_triggers:
        return "senior_management"

    # CRITICAL risk requires senior management
    if risk_assessment.risk_level == RiskLevel.CRITICAL:
        return "senior_management"

    # Confirmed sanctions match requires compliance officer + senior management
    sanctions_confirmed = [
        t for t in triggers if "CONFIRMED_MATCH" in t
    ]
    if sanctions_confirmed:
        return "senior_management_and_compliance_officer"

    # HIGH risk requires compliance officer review
    if risk_assessment.risk_level == RiskLevel.HIGH:
        return "compliance_officer"

    # Any EDD trigger requires at minimum supervisor approval
    if triggers:
        return "supervisor"

    return None


def _determine_monitoring_frequency(
    risk_assessment: RiskAssessment, edd_required: bool
) -> str:
    """Determine ongoing monitoring frequency."""
    if risk_assessment.risk_level == RiskLevel.CRITICAL:
        return "monthly"
    elif risk_assessment.risk_level == RiskLevel.HIGH:
        return "quarterly"
    elif risk_assessment.risk_level == RiskLevel.MEDIUM or edd_required:
        return "semi_annual"
    else:
        return "annual"
