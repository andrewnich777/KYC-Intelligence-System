"""
Material Misrepresentation Detection.

Deterministic utility comparing declared client information vs investigation-discovered
information. Flags discrepancies with severity levels:
- IMMATERIAL: Minor inconsistency, no compliance impact
- NOTABLE: Worth documenting but not necessarily concerning
- MATERIAL: Significant discrepancy affecting risk assessment
- CRITICAL: Deliberate concealment or major contradiction — STR consideration
"""

from datetime import UTC, datetime

from models import (
    BusinessClient,
    IndividualClient,
    InvestigationResults,
    PEPLevel,
)


def detect_misrepresentation(
    client,
    investigation: InvestigationResults,
) -> dict:
    """
    Compare declared client information against investigation findings.

    Returns dict with:
        misrepresentations: list of dicts with field, declared_value, found_value,
                           severity, evidence_ids, explanation
        has_material_misrepresentation: bool
        str_consideration_triggered: bool
        evidence: list of EvidenceRecord-compatible dicts
    """
    misrepresentations = []

    if isinstance(client, IndividualClient):
        misrepresentations.extend(_check_individual(client, investigation))
    elif isinstance(client, BusinessClient):
        misrepresentations.extend(_check_business(client, investigation))

    has_material = any(
        m["severity"] in ("MATERIAL", "CRITICAL") for m in misrepresentations
    )
    str_triggered = any(m["severity"] == "CRITICAL" for m in misrepresentations)

    # Build evidence records
    timestamp = datetime.now(UTC).isoformat()
    entity_name = (
        client.full_name if isinstance(client, IndividualClient)
        else client.legal_name
    )
    entity_key = entity_name.lower().replace(" ", "_")

    evidence = []
    if misrepresentations:
        evidence.append({
            "evidence_id": f"misrep_{entity_key}",
            "source_type": "utility",
            "source_name": "misrepresentation_detection",
            "entity_screened": entity_name,
            "claim": (
                f"Misrepresentation detection: {len(misrepresentations)} discrepancy(ies) found, "
                f"{sum(1 for m in misrepresentations if m['severity'] in ('MATERIAL', 'CRITICAL'))} material/critical."
            ),
            "evidence_level": "S",
            "supporting_data": [
                {"misrepresentations": misrepresentations},
            ],
            "disposition": "PENDING_REVIEW" if has_material else "CLEAR",
            "confidence": "HIGH",
            "timestamp": timestamp,
        })
    else:
        evidence.append({
            "evidence_id": f"misrep_{entity_key}_clear",
            "source_type": "utility",
            "source_name": "misrepresentation_detection",
            "entity_screened": entity_name,
            "claim": "Misrepresentation detection: no discrepancies found between declared and discovered information.",
            "evidence_level": "S",
            "supporting_data": [],
            "disposition": "CLEAR",
            "confidence": "HIGH",
            "timestamp": timestamp,
        })

    return {
        "misrepresentations": misrepresentations,
        "has_material_misrepresentation": has_material,
        "str_consideration_triggered": str_triggered,
        "evidence": evidence,
    }


def _check_individual(client: IndividualClient, investigation: InvestigationResults) -> list[dict]:
    """Check individual client for misrepresentations."""
    findings = []

    # 1. PEP: declared False vs detected non-NOT_PEP
    if investigation.pep_classification:
        pep = investigation.pep_classification
        if not client.pep_self_declaration and pep.detected_level != PEPLevel.NOT_PEP:
            severity = "CRITICAL" if pep.detected_level == PEPLevel.FOREIGN_PEP else "MATERIAL"
            findings.append({
                "field": "pep_self_declaration",
                "declared_value": "False (not a PEP)",
                "found_value": f"Detected as {pep.detected_level.value}",
                "severity": severity,
                "evidence_ids": [er.evidence_id for er in pep.evidence_records[:3]],
                "explanation": (
                    f"Client declared they are not a PEP, but investigation detected "
                    f"{pep.detected_level.value} status. "
                    + ("Foreign PEP requires permanent EDD — non-disclosure is a critical concern."
                       if pep.detected_level == PEPLevel.FOREIGN_PEP
                       else "PEP non-disclosure warrants enhanced scrutiny.")
                ),
            })

    # 2. Employment: declared employer vs undisclosed directorships
    if client.employment and client.employment.employer:
        declared_employer = client.employment.employer.lower()
        # Check adverse media for references to other companies/positions
        if investigation.individual_adverse_media:
            for article in investigation.individual_adverse_media.articles_found:
                summary = (article.summary or "").lower()
                if any(kw in summary for kw in ("director of", "ceo of", "founder of", "chairman of")):
                    if declared_employer not in summary:
                        findings.append({
                            "field": "employment",
                            "declared_value": client.employment.employer,
                            "found_value": f"Undisclosed position referenced in media: {(article.title or 'Unknown')[:80]}",
                            "severity": "NOTABLE",
                            "evidence_ids": [],
                            "explanation": (
                                "Media references a corporate position not disclosed in employment information. "
                                "May indicate undisclosed directorships or business interests."
                            ),
                        })
                        break

    # 3. Citizenship/jurisdiction: declared vs found in investigation
    if investigation.jurisdiction_risk and client.citizenship:
        assessed = investigation.jurisdiction_risk.jurisdictions_assessed
        declared_citizenship = client.citizenship.lower()
        # Look for jurisdictions mentioned in adverse media that differ from declared
        if investigation.individual_adverse_media:
            for article in investigation.individual_adverse_media.articles_found:
                summary = (article.summary or "").lower()
                for j in assessed:
                    if j.lower() != declared_citizenship and j.lower() in summary and j.lower() != "canada":
                        findings.append({
                            "field": "citizenship_jurisdictions",
                            "declared_value": client.citizenship,
                            "found_value": f"Connection to {j} found in adverse media",
                            "severity": "NOTABLE",
                            "evidence_ids": [],
                            "explanation": (
                                f"Investigation surfaced connections to {j} not reflected "
                                f"in declared citizenship ({client.citizenship})."
                            ),
                        })
                        break
                else:
                    continue
                break

    # 4. Source of funds: declared vs adverse media findings about wealth origins
    if client.source_of_funds and investigation.individual_adverse_media:
        client.source_of_funds.lower()
        crime_categories = investigation.individual_adverse_media.categories or []
        wealth_crimes = [c for c in crime_categories if c in (
            "fraud", "embezzlement", "tax_evasion", "money_laundering",
        )]
        if wealth_crimes:
            findings.append({
                "field": "source_of_funds",
                "declared_value": client.source_of_funds,
                "found_value": f"Adverse media categories: {', '.join(wealth_crimes)}",
                "severity": "MATERIAL",
                "evidence_ids": [],
                "explanation": (
                    f"Client declared source of funds as '{client.source_of_funds}' but "
                    f"adverse media includes {', '.join(wealth_crimes)} categories, "
                    f"which may contradict the declared source."
                ),
            })

    return findings


def _check_business(client: BusinessClient, investigation: InvestigationResults) -> list[dict]:
    """Check business client for misrepresentations."""
    findings = []

    # 1. UBOs: declared vs entity_verification discrepancies
    if investigation.entity_verification and investigation.entity_verification.discrepancies:
        for disc in investigation.entity_verification.discrepancies:
            disc_lower = disc.lower()
            # Check if discrepancy relates to ownership
            if any(kw in disc_lower for kw in ("owner", "ubo", "beneficial", "shareholder", "director")):
                findings.append({
                    "field": "beneficial_owners",
                    "declared_value": ", ".join(ubo.full_name for ubo in client.beneficial_owners) or "None declared",
                    "found_value": disc,
                    "severity": "MATERIAL",
                    "evidence_ids": [er.evidence_id for er in investigation.entity_verification.evidence_records[:3]],
                    "explanation": (
                        "Entity verification found ownership discrepancy: "
                        f"{disc}. Undisclosed beneficial ownership is a critical AML concern."
                    ),
                })

    # 2. Industry: declared vs actual operations found in adverse media
    if client.industry and investigation.business_adverse_media:
        declared_industry = client.industry.lower()
        for article in investigation.business_adverse_media.articles_found:
            summary = (article.summary or "").lower()
            # Check for industry mismatches
            suspicious_industries = ["casino", "gambling", "cryptocurrency", "weapons",
                                     "arms", "mining", "tobacco", "cannabis"]
            for si in suspicious_industries:
                if si in summary and si not in declared_industry:
                    findings.append({
                        "field": "industry",
                        "declared_value": client.industry,
                        "found_value": f"Media references {si} operations: {(article.title or 'Unknown')[:80]}",
                        "severity": "MATERIAL",
                        "evidence_ids": [],
                        "explanation": (
                            f"Client declared industry as '{client.industry}' but adverse media "
                            f"references involvement in {si}, which may indicate undisclosed "
                            f"high-risk business activities."
                        ),
                    })
                    break
            else:
                continue
            break

    # 3. Jurisdictions: declared vs investigation-surfaced
    if client.countries_of_operation and investigation.jurisdiction_risk:
        declared_countries = {c.lower() for c in client.countries_of_operation}
        assessed = investigation.jurisdiction_risk.jurisdictions_assessed
        fatf_grey = investigation.jurisdiction_risk.fatf_grey_list
        fatf_black = investigation.jurisdiction_risk.fatf_black_list
        high_risk_found = [
            j for j in assessed
            if j.lower() not in declared_countries
            and (j in fatf_grey or j in fatf_black)
        ]
        if high_risk_found:
            severity = "CRITICAL" if any(j in fatf_black for j in high_risk_found) else "MATERIAL"
            findings.append({
                "field": "countries_of_operation",
                "declared_value": ", ".join(client.countries_of_operation),
                "found_value": f"Undeclared high-risk jurisdictions found: {', '.join(high_risk_found)}",
                "severity": severity,
                "evidence_ids": [],
                "explanation": (
                    f"Investigation surfaced connections to high-risk jurisdictions "
                    f"({', '.join(high_risk_found)}) not declared in countries of operation. "
                    + ("FATF black-listed jurisdiction non-disclosure is a critical concern."
                       if any(j in fatf_black for j in high_risk_found)
                       else "FATF grey-listed jurisdiction non-disclosure is a material concern.")
                ),
            })

    # 4. Business purpose: declared intended_use vs adverse media findings
    if client.intended_use and investigation.business_adverse_media:
        crime_categories = investigation.business_adverse_media.categories or []
        serious_crimes = [c for c in crime_categories if c in (
            "fraud", "money_laundering", "terrorist_financing",
            "sanctions_evasion", "organized_crime",
        )]
        if serious_crimes:
            findings.append({
                "field": "intended_use",
                "declared_value": client.intended_use,
                "found_value": f"Adverse media categories: {', '.join(serious_crimes)}",
                "severity": "CRITICAL",
                "evidence_ids": [],
                "explanation": (
                    f"Client declared intended use as '{client.intended_use}' but "
                    f"adverse media includes serious crime categories ({', '.join(serious_crimes)}). "
                    f"STR consideration required."
                ),
            })

    return findings
