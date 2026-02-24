"""
Compliance Actions and Reporting Obligations.

Determines required compliance actions, reporting obligations, timelines,
and escalation requirements based on client risk profile and investigation
findings. Pure deterministic logic, no API calls.
"""

from datetime import UTC, datetime, timedelta

from constants import (
    LARGE_CASH_TRANSACTION_THRESHOLD,
    LARGE_EFT_THRESHOLD,
    LARGE_VIRTUAL_CURRENCY_THRESHOLD,
)
from models import (
    AdverseMediaLevel,
    BusinessClient,
    DispositionStatus,
    IndividualClient,
    InvestigationResults,
    PEPLevel,
    RiskAssessment,
    RiskLevel,
)
from utilities.shared_checks import check_str_triggers, is_us_country


def determine_compliance_actions(
    client,
    risk_assessment: RiskAssessment,
    investigation: InvestigationResults = None,
) -> dict:
    """
    Determine required compliance actions and reporting obligations.

    Returns dict with:
        reports: list of dicts — required reports with type, trigger, timeline, notes
        actions: list of str — required compliance actions
        timelines: dict — key deadlines mapped to action type
        escalations: list of str — items requiring escalation
        evidence: list of EvidenceRecord-compatible dicts

    Possible reports:
    - STR: "HUMAN DECISION REQUIRED" — never auto-file
    - Terrorist Property Report: if confirmed match to terrorist list
    - FATCA Report: if US person identified
    - CRS Report: if non-Canadian tax residency
    - Large Cash Transaction Report: if single cash transaction >= $10,000 CAD

    Actions:
    - Document retention (minimum 5 years)
    - Ongoing monitoring schedule assignment
    - Risk rating review schedule
    - Training notifications
    """
    timestamp = datetime.now(UTC).isoformat()
    evidence = []

    # Get entity name
    if isinstance(client, IndividualClient):
        entity_name = client.full_name
        entity_context = "individual client"
    elif isinstance(client, BusinessClient):
        entity_name = client.legal_name
        entity_context = "business client"
    else:
        entity_name = "unknown"
        entity_context = "unknown client type"

    # Determine reports
    reports = _determine_reports(client, risk_assessment, investigation)

    # Determine actions
    actions = _determine_actions(client, risk_assessment, investigation)

    # Determine timelines
    timelines = _determine_timelines(reports, risk_assessment)

    # Determine escalations
    escalations = _determine_escalations(client, risk_assessment, investigation)

    # Build evidence
    entity_key = entity_name.lower().replace(" ", "_")
    evidence.append({
        "evidence_id": f"compliance_{entity_key}",
        "source_type": "utility",
        "source_name": "compliance_actions",
        "entity_screened": entity_name,
        "entity_context": entity_context,
        "claim": (
            f"Compliance actions determined: {len(reports)} report(s), "
            f"{len(actions)} action(s), {len(escalations)} escalation(s)."
        ),
        "evidence_level": "S",
        "supporting_data": [
            {"reports": [{"type": r["type"], "trigger": r.get("trigger", "")} for r in reports]},
            {"actions": actions},
            {"escalations": escalations if escalations else []},
        ],
        "disposition": "PENDING_REVIEW" if escalations else "CLEAR",
        "confidence": "HIGH",
        "timestamp": timestamp,
    })

    # Additional evidence for STR considerations
    str_reports = [r for r in reports if r["type"] == "STR"]
    if str_reports:
        evidence.append({
            "evidence_id": f"str_consideration_{entity_key}",
            "source_type": "utility",
            "source_name": "compliance_actions",
            "entity_screened": entity_name,
            "entity_context": entity_context,
            "claim": (
                "HUMAN DECISION REQUIRED: Suspicious Transaction Report (STR) "
                "consideration triggered. This utility identifies potential triggers "
                "but STR filing decisions MUST be made by a qualified compliance officer."
            ),
            "evidence_level": "S",
            "supporting_data": [
                {"str_triggers": [r["trigger"] for r in str_reports]},
                {"note": "STR filing is a human decision — never auto-file"},
            ],
            "disposition": "PENDING_REVIEW",
            "confidence": "HIGH",
            "timestamp": timestamp,
        })

    return {
        "reports": reports,
        "actions": actions,
        "timelines": timelines,
        "escalations": escalations,
        "evidence": evidence,
    }


def _determine_reports(
    client,
    risk_assessment: RiskAssessment,
    investigation: InvestigationResults = None,
) -> list:
    """Determine required or potentially required reports."""
    reports = []

    # -------------------------------------------------------------------------
    # STR (Suspicious Transaction Report) — NEVER auto-file
    # -------------------------------------------------------------------------
    str_triggers = check_str_triggers(client, investigation)

    if str_triggers:
        reports.append({
            "type": "STR",
            "full_name": "Suspicious Transaction Report",
            "trigger": "; ".join(str_triggers),
            "timeline": "30 days from detection",
            "filing_decision": "HUMAN DECISION REQUIRED",
            "notes": (
                "This utility identifies potential STR triggers but does NOT "
                "make a filing decision. A qualified compliance officer must "
                "assess whether reasonable grounds to suspect exist. "
                "Filing or non-filing must be documented with rationale."
            ),
        })

    # -------------------------------------------------------------------------
    # Terrorist Property Report
    # -------------------------------------------------------------------------
    terrorist_match = False
    if investigation:
        for sr in [investigation.individual_sanctions, investigation.entity_sanctions]:
            if sr and sr.disposition == DispositionStatus.CONFIRMED_MATCH:
                # Check if any match is against a terrorist list
                for match in sr.matches:
                    list_name = (match.list_name or "").lower()
                    if any(
                        kw in list_name
                        for kw in ("terrorist", "criminal code", "unscr", "isil", "al-qaida",
                                   "jvcfoa", "magnitsky", "public safety", "listed entities")
                    ):
                        terrorist_match = True
                        break

    if terrorist_match:
        reports.append({
            "type": "TPR",
            "full_name": "Terrorist Property Report",
            "trigger": "Confirmed match to terrorist listing",
            "timeline": "Immediately upon discovery",
            "filing_decision": "REQUIRED",
            "notes": (
                "FINTRAC requires immediate filing of a Terrorist Property Report "
                "when there is a match to a listed terrorist entity. "
                "All property must be frozen. Contact RCMP and CSIS as appropriate."
            ),
        })

    # -------------------------------------------------------------------------
    # FATCA Report
    # -------------------------------------------------------------------------
    fatca_required = False
    fatca_trigger = ""

    if isinstance(client, IndividualClient):
        if client.us_person:
            fatca_required = True
            fatca_trigger = "Client is US person (self-declared)"
        elif client.citizenship and is_us_country(client.citizenship):
            fatca_required = True
            fatca_trigger = "US citizenship"
        elif any(is_us_country(t) for t in client.tax_residencies):
            fatca_required = True
            fatca_trigger = "US tax residency"
    elif isinstance(client, BusinessClient):
        if client.us_nexus:
            fatca_required = True
            fatca_trigger = "Entity has US nexus"
        else:
            us_ubos = [ubo for ubo in client.beneficial_owners if ubo.us_person]
            if us_ubos:
                fatca_required = True
                names = ", ".join(u.full_name for u in us_ubos)
                fatca_trigger = f"US person beneficial owner(s): {names}"

    if fatca_required:
        reports.append({
            "type": "FATCA",
            "full_name": "FATCA Report (Part XVIII of Income Tax Act)",
            "trigger": fatca_trigger,
            "timeline": "Annual — by May 1 (CRA filing deadline)",
            "filing_decision": "REQUIRED",
            "notes": (
                "Report US account holder information to CRA, who will exchange "
                "with IRS under the Canada-US IGA. Ensure W-9 is obtained."
            ),
        })

    # -------------------------------------------------------------------------
    # CRS Report
    # -------------------------------------------------------------------------
    crs_jurisdictions = []

    if isinstance(client, IndividualClient):
        non_ca = [
            t for t in client.tax_residencies
            if t.lower() not in ("canada", "ca")
            and not is_us_country(t)
        ]
        crs_jurisdictions.extend(non_ca)
    elif isinstance(client, BusinessClient):
        for country in client.countries_of_operation:
            if country.lower() not in ("canada", "ca") and not is_us_country(country):
                crs_jurisdictions.append(country)
        for ubo in client.beneficial_owners:
            for tr in ubo.tax_residencies:
                if tr.lower() not in ("canada", "ca") and not is_us_country(tr):
                    if tr not in crs_jurisdictions:
                        crs_jurisdictions.append(tr)

    if crs_jurisdictions:
        reports.append({
            "type": "CRS",
            "full_name": "CRS Report (Part XIX of Income Tax Act)",
            "trigger": f"Non-Canadian tax residency: {', '.join(crs_jurisdictions)}",
            "timeline": "Annual — by May 1 (CRA filing deadline)",
            "filing_decision": "REQUIRED",
            "notes": (
                "Report to CRA for automatic exchange of information with "
                f"participating jurisdictions: {', '.join(crs_jurisdictions)}."
            ),
        })

    # -------------------------------------------------------------------------
    # Large Cash Transaction Report (LCTR)
    # -------------------------------------------------------------------------
    lctr_triggers = []
    if isinstance(client, (IndividualClient, BusinessClient)):
        for acct in client.account_requests:
            if acct.initial_deposit and acct.initial_deposit >= LARGE_CASH_TRANSACTION_THRESHOLD:
                expected = (acct.expected_activity or "").lower()
                if "cash" in expected:
                    lctr_triggers.append(
                        f"Initial deposit of ${acct.initial_deposit:,.0f} "
                        f"with cash activity expected"
                    )

    if lctr_triggers:
        reports.append({
            "type": "LCTR",
            "full_name": "Large Cash Transaction Report",
            "trigger": "; ".join(lctr_triggers),
            "timeline": "Within 15 calendar days of the transaction",
            "filing_decision": "REQUIRED (if cash transaction >= $10,000 CAD)",
            "notes": (
                "FINTRAC requires reporting of any single cash transaction "
                "of $10,000 CAD or more (or multiple transactions within "
                "24 hours totaling $10,000+). Monitor for structuring."
            ),
        })

    # -------------------------------------------------------------------------
    # Large Virtual Currency Transaction Report (LVCTR)
    # -------------------------------------------------------------------------
    lvctr_triggers = []
    for acct in getattr(client, "account_requests", []):
        if acct.initial_deposit and acct.initial_deposit >= LARGE_VIRTUAL_CURRENCY_THRESHOLD:
            expected = (acct.expected_activity or "").lower()
            acct_type = (acct.account_type or "").lower()
            if any(kw in expected or kw in acct_type
                   for kw in ("crypto", "virtual currency", "bitcoin", "digital asset")):
                lvctr_triggers.append(
                    f"Initial deposit of ${acct.initial_deposit:,.0f} "
                    f"with virtual currency activity expected"
                )

    if lvctr_triggers:
        reports.append({
            "type": "LVCTR",
            "full_name": "Large Virtual Currency Transaction Report",
            "trigger": "; ".join(lvctr_triggers),
            "timeline": "Within 15 calendar days of the transaction",
            "filing_decision": "REQUIRED (if VC transaction >= $10,000 CAD)",
            "notes": (
                "FINTRAC requires reporting of any virtual currency "
                "transaction of $10,000 CAD or more (receiving or "
                "transferring). Monitor for structuring across wallets."
            ),
        })

    # -------------------------------------------------------------------------
    # Electronic Funds Transfer Report (EFTR)
    # -------------------------------------------------------------------------
    eftr_triggers = []
    for acct in getattr(client, "account_requests", []):
        if acct.initial_deposit and acct.initial_deposit >= LARGE_EFT_THRESHOLD:
            expected = (acct.expected_activity or "").lower()
            if any(kw in expected
                   for kw in ("wire", "eft", "international transfer",
                              "cross-border", "remittance", "swift")):
                eftr_triggers.append(
                    f"Initial deposit of ${acct.initial_deposit:,.0f} "
                    f"with international EFT activity expected"
                )

    if eftr_triggers:
        reports.append({
            "type": "EFTR",
            "full_name": "Electronic Funds Transfer Report",
            "trigger": "; ".join(eftr_triggers),
            "timeline": "Within 5 business days of the transaction",
            "filing_decision": "REQUIRED (if international EFT >= $10,000 CAD)",
            "notes": (
                "FINTRAC requires reporting of international electronic "
                "funds transfers of $10,000 CAD or more (sending or "
                "receiving). Applies to SWIFT, wire transfers, and "
                "other cross-border EFTs."
            ),
        })

    # -------------------------------------------------------------------------
    # Misrepresentation-triggered STR consideration
    # -------------------------------------------------------------------------
    if investigation:
        misrep = investigation.misrepresentation_detection
        if isinstance(misrep, dict) and misrep.get("str_consideration_triggered"):
            critical_misreps = [
                m for m in misrep.get("misrepresentations", [])
                if m.get("severity") == "CRITICAL"
            ]
            if critical_misreps:
                misrep_details = "; ".join(
                    f"{m['field']}: declared '{m['declared_value']}', found '{m['found_value']}'"
                    for m in critical_misreps[:3]
                )
                # Only add if no existing STR report covers this
                existing_str_triggers = [r["trigger"] for r in reports if r["type"] == "STR"]
                if not any("misrepresentation" in t.lower() for t in existing_str_triggers):
                    reports.append({
                        "type": "STR",
                        "full_name": "Suspicious Transaction Report",
                        "trigger": f"Critical misrepresentation: {misrep_details}",
                        "timeline": "30 days from detection",
                        "filing_decision": "HUMAN DECISION REQUIRED",
                        "notes": (
                            "Critical misrepresentation in client declarations may indicate "
                            "deliberate concealment. Compliance officer must assess whether "
                            "reasonable grounds to suspect exist."
                        ),
                    })

    # -------------------------------------------------------------------------
    # SAR Risk Assessment-triggered STR consideration
    # -------------------------------------------------------------------------
    if investigation:
        sar = investigation.sar_risk_assessment
        if isinstance(sar, dict) and sar.get("sar_risk_level") in ("HIGH", "CRITICAL"):
            sar_triggers = sar.get("triggers", [])
            trigger_text = "; ".join(sar_triggers[:3]) if sar_triggers else "Elevated SAR risk"
            existing_str_triggers = [r["trigger"] for r in reports if r["type"] == "STR"]
            if not any("sar" in t.lower() for t in existing_str_triggers):
                reports.append({
                    "type": "STR",
                    "full_name": "Suspicious Transaction Report",
                    "trigger": f"SAR risk {sar.get('sar_risk_level')}: {trigger_text}",
                    "timeline": "30 days from detection",
                    "filing_decision": "HUMAN DECISION REQUIRED",
                    "notes": (
                        f"SAR risk assessment determined {sar.get('sar_risk_level')} risk level. "
                        "Review draft narrative elements and triggers before making filing decision."
                    ),
                })

    return reports


def _determine_actions(
    client,
    risk_assessment: RiskAssessment,
    investigation: InvestigationResults = None,
) -> list:
    """Determine required compliance actions."""
    actions = []

    # Universal actions
    actions.append(
        "Document retention: maintain all KYC records for minimum 5 years "
        "from end of business relationship (PCMLTFA requirement)"
    )
    actions.append(
        f"Assign ongoing monitoring schedule: "
        f"{_monitoring_label(risk_assessment.risk_level)}"
    )
    actions.append(
        f"Schedule risk rating review: "
        f"{_review_schedule(risk_assessment.risk_level)}"
    )

    # Risk-level-specific actions
    if risk_assessment.risk_level == RiskLevel.CRITICAL:
        actions.append(
            "Obtain senior management approval before establishing relationship"
        )
        actions.append(
            "Establish enhanced transaction monitoring with lower thresholds"
        )
        actions.append(
            "Document rationale for proceeding with high-risk relationship"
        )
    elif risk_assessment.risk_level == RiskLevel.HIGH:
        actions.append(
            "Obtain compliance officer approval before onboarding"
        )
        actions.append(
            "Set enhanced transaction monitoring alerts"
        )

    # Source of funds/wealth documentation
    if isinstance(client, IndividualClient):
        if client.source_of_funds:
            sof = client.source_of_funds.lower()
            if sof in ("inheritance", "gift", "lottery_gambling", "cryptocurrency", "unknown"):
                actions.append(
                    f"Obtain supporting documentation for source of funds: "
                    f"'{client.source_of_funds}'"
                )
        if risk_assessment.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            actions.append(
                "Obtain and verify source of wealth documentation"
            )

    # Business-specific actions
    if isinstance(client, BusinessClient):
        actions.append(
            "Verify and maintain current beneficial ownership information"
        )
        if not client.beneficial_owners:
            actions.append(
                "PRIORITY: Determine all beneficial owners (>25% ownership/control)"
            )
        actions.append(
            "Obtain and retain articles of incorporation or equivalent"
        )

    # PEP-related actions
    if isinstance(client, IndividualClient) and client.pep_self_declaration:
        actions.append(
            "Establish purpose and intended nature of business relationship "
            "with PEP client"
        )
        actions.append(
            "Determine source of wealth through independent means"
        )

    # Investigation-triggered actions
    if investigation:
        if investigation.pep_classification and investigation.pep_classification.edd_required:
            actions.append(
                "Implement EDD measures for PEP as per assessment"
            )

        # Training notifications for new risk types
        risk_categories = set()
        for factor in risk_assessment.risk_factors:
            risk_categories.add(factor.category)

        unusual_categories = risk_categories.intersection({
            "pep", "sanctions", "terrorist_financing", "ubo_cascade",
        })
        if unusual_categories:
            actions.append(
                f"Training notification: ensure staff are trained on "
                f"{', '.join(unusual_categories)} risk handling procedures"
            )

        # Transaction monitoring-driven actions
        if investigation.transaction_monitoring:
            tm = investigation.transaction_monitoring
            freq = tm.recommended_monitoring_frequency
            if freq in ("enhanced", "elevated"):
                actions.append(
                    f"Transaction monitoring: implement {freq} monitoring "
                    f"based on AML typology assessment"
                )
            high_typologies = [
                t for t in (tm.industry_typologies + tm.geographic_typologies)
                if t.relevance == "HIGH"
            ]
            if high_typologies:
                typology_names = ", ".join(t.typology_name for t in high_typologies[:3])
                actions.append(
                    f"Configure AML alerts for identified typologies: {typology_names}"
                )

    return actions


def _determine_timelines(reports: list, risk_assessment: RiskAssessment) -> dict:
    """Build a timelines dict from reports and risk level."""
    timelines = {}
    today = datetime.now()

    # Compute deadlines for report types
    for report in reports:
        report_type = report["type"]
        computed_deadline = None

        if report_type == "STR":
            computed_deadline = (today + timedelta(days=30)).strftime("%Y-%m-%d")
        elif report_type == "TPR":
            computed_deadline = today.strftime("%Y-%m-%d")
        elif report_type in ("FATCA", "CRS"):
            # Next May 1
            next_may = datetime(today.year, 5, 1)
            if today >= next_may:
                next_may = datetime(today.year + 1, 5, 1)
            computed_deadline = next_may.strftime("%Y-%m-%d")
        elif report_type == "LCTR" or report_type == "LVCTR":
            computed_deadline = (today + timedelta(days=15)).strftime("%Y-%m-%d")
        elif report_type == "EFTR":
            # 5 business days ≈ 7 calendar days (conservative estimate)
            computed_deadline = (today + timedelta(days=7)).strftime("%Y-%m-%d")

        timelines[report_type] = {
            "deadline": report["timeline"],
            "filing_decision": report["filing_decision"],
            "computed_deadline": computed_deadline,
        }

    # Add standard timelines
    timelines["initial_review"] = {
        "deadline": "Before onboarding completion",
        "description": "Complete all KYC checks and obtain required approvals",
        "computed_deadline": today.strftime("%Y-%m-%d"),
    }

    if risk_assessment.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
        timelines["risk_review"] = {
            "deadline": "Within 12 months of onboarding",
            "description": "First periodic risk review for high/critical clients",
            "computed_deadline": (today + timedelta(days=365)).strftime("%Y-%m-%d"),
        }
    else:
        timelines["risk_review"] = {
            "deadline": "Within 24 months of onboarding",
            "description": "First periodic risk review",
            "computed_deadline": (today + timedelta(days=730)).strftime("%Y-%m-%d"),
        }

    timelines["document_retention"] = {
        "deadline": "5 years from end of business relationship",
        "description": "Minimum retention period per PCMLTFA",
    }

    return timelines


def _determine_escalations(
    client,
    risk_assessment: RiskAssessment,
    investigation: InvestigationResults = None,
) -> list:
    """Determine items requiring escalation."""
    escalations = []

    # Critical risk
    if risk_assessment.risk_level == RiskLevel.CRITICAL:
        escalations.append(
            "CRITICAL risk level — escalate to senior management for "
            "relationship approval/decline decision"
        )

    # Sanctions matches
    if investigation:
        for sr in [investigation.individual_sanctions, investigation.entity_sanctions]:
            if sr and sr.disposition == DispositionStatus.CONFIRMED_MATCH:
                escalations.append(
                    f"CONFIRMED sanctions match for '{sr.entity_screened}' — "
                    "escalate to Compliance Officer and Legal immediately"
                )
            elif sr and sr.disposition == DispositionStatus.POTENTIAL_MATCH:
                escalations.append(
                    f"POTENTIAL sanctions match for '{sr.entity_screened}' — "
                    "escalate to Compliance Officer for disposition"
                )

    # PEP
    if investigation and investigation.pep_classification:
        pep = investigation.pep_classification
        if pep.detected_level == PEPLevel.FOREIGN_PEP:
            escalations.append(
                f"Foreign PEP detected: {pep.entity_screened} — "
                "escalate to senior management"
            )
        elif pep.detected_level in (PEPLevel.DOMESTIC_PEP, PEPLevel.HIO):
            escalations.append(
                f"{pep.detected_level.value} detected: {pep.entity_screened} — "
                "escalate to compliance officer"
            )

    # Adverse media
    if investigation:
        for mr in [investigation.individual_adverse_media, investigation.business_adverse_media]:
            if mr and mr.overall_level == AdverseMediaLevel.HIGH_RISK:
                escalations.append(
                    f"HIGH_RISK adverse media for '{mr.entity_screened}' — "
                    "escalate for STR consideration"
                )

    # Misrepresentation escalation
    if investigation:
        misrep = investigation.misrepresentation_detection
        if isinstance(misrep, dict) and misrep.get("has_material_misrepresentation"):
            critical_count = sum(
                1 for m in misrep.get("misrepresentations", [])
                if m.get("severity") == "CRITICAL"
            )
            if critical_count > 0:
                escalations.append(
                    f"CRITICAL misrepresentation detected ({critical_count} finding(s)) — "
                    "escalate to senior management and consider STR filing"
                )
            else:
                escalations.append(
                    "Material misrepresentation detected — "
                    "escalate to compliance officer for review"
                )

    # SAR risk escalation
    if investigation:
        sar = investigation.sar_risk_assessment
        if isinstance(sar, dict) and sar.get("sar_risk_level") in ("HIGH", "CRITICAL"):
            escalations.append(
                f"SAR risk level {sar['sar_risk_level']} — "
                "escalate for STR filing decision"
            )

    # Third-party accounts
    if isinstance(client, IndividualClient) and client.third_party_determination:
        escalations.append(
            "Third-party determination — ensure third-party identity verified "
            "and documented per FINTRAC requirements"
        )
    elif isinstance(client, BusinessClient) and client.third_party_determination:
        escalations.append(
            "Third-party determination for business account — "
            "verify and document third-party details"
        )

    return escalations


def _monitoring_label(risk_level: RiskLevel) -> str:
    """Get monitoring frequency label for risk level."""
    mapping = {
        RiskLevel.CRITICAL: "monthly monitoring",
        RiskLevel.HIGH: "quarterly monitoring",
        RiskLevel.MEDIUM: "semi-annual monitoring",
        RiskLevel.LOW: "annual monitoring",
    }
    return mapping.get(risk_level, "annual monitoring")


def _review_schedule(risk_level: RiskLevel) -> str:
    """Get risk review schedule for risk level."""
    mapping = {
        RiskLevel.CRITICAL: "every 6 months",
        RiskLevel.HIGH: "every 12 months",
        RiskLevel.MEDIUM: "every 24 months",
        RiskLevel.LOW: "every 36 months",
    }
    return mapping.get(risk_level, "every 36 months")
