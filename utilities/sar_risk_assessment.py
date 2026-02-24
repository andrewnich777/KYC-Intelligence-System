"""
SAR/STR Risk Assessment Utility.

Deterministic assessment combining all investigation findings to determine
SAR/STR risk level and generate draft narrative elements. Pure Python,
no API calls.

Risk levels:
- LOW: No SAR indicators
- MEDIUM: Some indicators present, monitoring recommended
- HIGH: Multiple indicators, STR consideration required
- CRITICAL: Strong indicators, STR filing likely warranted
"""

from datetime import UTC, datetime

from models import (
    AdverseMediaLevel,
    BusinessClient,
    DispositionStatus,
    IndividualClient,
    InvestigationResults,
    PEPLevel,
)


def assess_sar_risk(
    client,
    investigation: InvestigationResults,
) -> dict:
    """
    Assess SAR/STR risk by combining all investigation findings.

    Returns dict with:
        sar_risk_level: LOW | MEDIUM | HIGH | CRITICAL
        triggers: list of trigger descriptions
        draft_narrative_elements: list of narrative building blocks for STR
        filing_timeline: str — recommended timeline if filing warranted
        evidence: list of EvidenceRecord-compatible dicts
    """
    triggers = []
    narrative_elements = []
    risk_score = 0

    # 1. Sanctions matches
    for sr in [investigation.individual_sanctions, investigation.entity_sanctions]:
        if sr and sr.disposition == DispositionStatus.CONFIRMED_MATCH:
            triggers.append(f"Confirmed sanctions match: {sr.entity_screened}")
            narrative_elements.append(
                f"Subject '{sr.entity_screened}' has a confirmed match on sanctions screening. "
                f"Sources: {', '.join(sr.screening_sources[:5])}."
            )
            risk_score += 40
        elif sr and sr.disposition == DispositionStatus.POTENTIAL_MATCH:
            triggers.append(f"Potential sanctions match: {sr.entity_screened}")
            narrative_elements.append(
                f"Subject '{sr.entity_screened}' has a potential match on sanctions screening "
                f"requiring further verification."
            )
            risk_score += 20

    # 2. PEP status
    if investigation.pep_classification:
        pep = investigation.pep_classification
        if pep.detected_level == PEPLevel.FOREIGN_PEP:
            triggers.append(f"Foreign PEP detected: {pep.entity_screened}")
            narrative_elements.append(
                f"Subject '{pep.entity_screened}' identified as Foreign PEP. "
                f"Enhanced due diligence and source of wealth verification required."
            )
            risk_score += 15
        elif pep.detected_level in (PEPLevel.DOMESTIC_PEP, PEPLevel.HIO):
            triggers.append(f"{pep.detected_level.value} detected: {pep.entity_screened}")
            risk_score += 10

    # 3. Adverse media crime categories
    for mr in [investigation.individual_adverse_media, investigation.business_adverse_media]:
        if mr and mr.overall_level in (AdverseMediaLevel.HIGH_RISK, AdverseMediaLevel.MATERIAL_CONCERN):
            crime_categories = [
                c for c in (mr.categories or [])
                if c in (
                    "fraud", "money_laundering", "terrorist_financing",
                    "bribery", "corruption", "tax_evasion",
                    "sanctions_evasion", "organized_crime",
                )
            ]
            if crime_categories:
                triggers.append(
                    f"Adverse media ({mr.overall_level.value}): {', '.join(crime_categories)}"
                )
                narrative_elements.append(
                    f"Adverse media screening for '{mr.entity_screened}' reveals "
                    f"{mr.overall_level.value} findings in categories: {', '.join(crime_categories)}."
                )
                risk_score += 20 if mr.overall_level == AdverseMediaLevel.HIGH_RISK else 10

    # 4. Misrepresentation results
    misrep = investigation.misrepresentation_detection
    if misrep and isinstance(misrep, dict):
        if misrep.get("has_material_misrepresentation"):
            triggers.append("Material misrepresentation detected in client declarations")
            critical_misreps = [
                m for m in misrep.get("misrepresentations", [])
                if m.get("severity") in ("MATERIAL", "CRITICAL")
            ]
            for m in critical_misreps[:3]:
                narrative_elements.append(
                    f"Misrepresentation in '{m['field']}': declared '{m['declared_value']}' "
                    f"but investigation found '{m['found_value']}'. Severity: {m['severity']}."
                )
            risk_score += 25
        if misrep.get("str_consideration_triggered"):
            triggers.append("CRITICAL misrepresentation — STR consideration triggered")
            risk_score += 15

    # 5. Transaction monitoring findings
    if investigation.transaction_monitoring:
        tm = investigation.transaction_monitoring
        high_typologies = [
            t for t in (tm.industry_typologies + tm.geographic_typologies)
            if t.relevance == "HIGH"
        ]
        if high_typologies:
            triggers.append(
                f"{len(high_typologies)} high-relevance AML typologies identified"
            )
            for t in high_typologies[:3]:
                narrative_elements.append(
                    f"AML typology '{t.typology_name}' (HIGH relevance): {t.description[:100]}."
                )
            risk_score += 10 * min(len(high_typologies), 3)

        if tm.sar_risk_indicators:
            triggers.append(
                f"Transaction monitoring SAR indicators: {', '.join(tm.sar_risk_indicators[:3])}"
            )
            risk_score += 5 * min(len(tm.sar_risk_indicators), 3)

    # 6. Wealth/income anomalies
    if isinstance(client, IndividualClient):
        if (client.annual_income and client.net_worth and client.annual_income > 0):
            ratio = client.net_worth / client.annual_income
            if ratio > 20:
                triggers.append(
                    f"Unusual wealth/income ratio: {ratio:.1f}x "
                    f"(net worth ${client.net_worth:,.0f} vs income ${client.annual_income:,.0f})"
                )
                risk_score += 10
    elif isinstance(client, BusinessClient):
        if (client.expected_transaction_volume and client.annual_revenue
                and client.annual_revenue > 0):
            ratio = client.expected_transaction_volume / client.annual_revenue
            if ratio > 3:
                triggers.append(
                    f"Transaction volume {ratio:.1f}x annual revenue — potential pass-through"
                )
                risk_score += 15

    # 7. UBO screening results
    if investigation.ubo_screening:
        for ubo_name, ubo_data in investigation.ubo_screening.items():
            if isinstance(ubo_data, dict):
                s = ubo_data.get("sanctions", {})
                if isinstance(s, dict) and s.get("disposition") in (
                    "POTENTIAL_MATCH", "CONFIRMED_MATCH"
                ):
                    triggers.append(f"UBO sanctions concern: {ubo_name}")
                    narrative_elements.append(
                        f"Beneficial owner '{ubo_name}' has sanctions screening concern "
                        f"(disposition: {s.get('disposition')})."
                    )
                    risk_score += 20

    # Determine overall risk level
    if risk_score >= 60:
        sar_risk_level = "CRITICAL"
        filing_timeline = "Immediate — within 3 business days"
    elif risk_score >= 35:
        sar_risk_level = "HIGH"
        filing_timeline = "Within 30 days of detection"
    elif risk_score >= 15:
        sar_risk_level = "MEDIUM"
        filing_timeline = "Monitor and reassess within 90 days"
    else:
        sar_risk_level = "LOW"
        filing_timeline = "No filing indicated — standard monitoring"

    # Build evidence
    timestamp = datetime.now(UTC).isoformat()
    entity_name = (
        client.full_name if isinstance(client, IndividualClient)
        else client.legal_name
    )
    entity_key = entity_name.lower().replace(" ", "_")

    evidence = [{
        "evidence_id": f"sar_risk_{entity_key}",
        "source_type": "utility",
        "source_name": "sar_risk_assessment",
        "entity_screened": entity_name,
        "claim": (
            f"SAR risk assessment: {sar_risk_level} "
            f"(score {risk_score}, {len(triggers)} trigger(s))"
        ),
        "evidence_level": "S",
        "supporting_data": [
            {"sar_risk_level": sar_risk_level},
            {"risk_score": risk_score},
            {"triggers": triggers},
        ],
        "disposition": "PENDING_REVIEW" if sar_risk_level in ("HIGH", "CRITICAL") else "CLEAR",
        "confidence": "HIGH",
        "timestamp": timestamp,
    }]

    return {
        "sar_risk_level": sar_risk_level,
        "risk_score": risk_score,
        "triggers": triggers,
        "draft_narrative_elements": narrative_elements,
        "filing_timeline": filing_timeline,
        "evidence": evidence,
    }
