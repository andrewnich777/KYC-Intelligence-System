"""
Individual FATCA/CRS Classification.

Determines FATCA and CRS obligations for individual clients based on
US indicia (7 indicators per IRS) and CRS tax residency analysis.
Pure deterministic logic, no API calls.
"""

from datetime import UTC, datetime

from models import IndividualClient
from utilities.reference_data import CRS_NON_PARTICIPATING
from utilities.shared_checks import is_us_country


def classify_individual_fatca_crs(client: IndividualClient) -> dict:
    """
    Determine FATCA and CRS obligations for an individual client.

    Returns dict with:
        fatca: dict — FATCA analysis (us_indicia found, classification, W-9 status)
        crs: dict — CRS analysis (reportable jurisdictions, self-certification status)
        required_forms: list of str — forms the client must complete
        reporting_obligations: list of str — reporting obligations for the firm
        evidence: list of EvidenceRecord-compatible dicts

    FATCA (7 US indicia):
    1. US citizenship or lawful permanent resident
    2. US birthplace
    3. US residence address
    4. US telephone number (not available in intake — flagged as unchecked)
    5. Standing instructions to transfer to US account (not in intake — flagged)
    6. Power of attorney to person with US address (not in intake — flagged)
    7. "In care of" or "hold mail" address that is sole address (not in intake — flagged)

    CRS:
    - If tax_residencies includes non-Canadian jurisdiction: CRS self-certification required
    - Report to each jurisdiction where tax resident (except Canada)
    """
    timestamp = datetime.now(UTC).isoformat()
    evidence = []

    fatca_result = _assess_fatca(client, timestamp, evidence)
    crs_result = _assess_crs(client, timestamp, evidence)

    required_forms = []
    reporting_obligations = []

    # Collect required forms
    if fatca_result["us_person"]:
        required_forms.append("IRS Form W-9 (Request for Taxpayer Identification Number)")
        if not client.us_tin:
            required_forms.append(
                "US TIN required — obtain SSN or ITIN from client"
            )
        reporting_obligations.append(
            "FATCA reporting to CRA (who exchanges with IRS) — annual, by May 1"
        )
    elif fatca_result["indicia_found"] and not fatca_result["us_person"]:
        # Indicia found but client has not self-declared as US person
        required_forms.append(
            "IRS Form W-8BEN (Certificate of Foreign Status) with reasonable explanation "
            "for US indicia, OR Form W-9 if client is actually a US person"
        )
        reporting_obligations.append(
            "FATCA: resolve US indicia — obtain W-8BEN with curing documentation "
            "or W-9 if US person"
        )

    if crs_result["reportable_jurisdictions"]:
        required_forms.append("CRS Self-Certification Form (individual)")
        for jurisdiction in crs_result["reportable_jurisdictions"]:
            reporting_obligations.append(
                f"CRS reporting for {jurisdiction} tax residency — annual, by May 1"
            )

    # Always need at least a self-certification for CRS
    if "CRS Self-Certification Form (individual)" not in required_forms:
        required_forms.append(
            "CRS Self-Certification Form (individual) — "
            "confirm Canadian-only tax residency"
        )

    return {
        "fatca": fatca_result,
        "crs": crs_result,
        "required_forms": required_forms,
        "reporting_obligations": reporting_obligations,
        "evidence": evidence,
    }


def _assess_fatca(
    client: IndividualClient, timestamp: str, evidence: list
) -> dict:
    """Assess FATCA obligations based on 7 US indicia."""
    indicia = []
    indicia_details = {}

    # Indicium 1: US citizenship or lawful permanent resident
    is_us_citizen = is_us_country(client.citizenship)
    if is_us_citizen:
        indicia.append("US citizenship")
        indicia_details["us_citizenship"] = True
    else:
        indicia_details["us_citizenship"] = False

    # Also check explicit us_person flag (may indicate green card holder)
    if client.us_person:
        if "US citizenship" not in indicia:
            indicia.append("US person (self-declared — may be green card holder)")
        indicia_details["us_person_declaration"] = True
    else:
        indicia_details["us_person_declaration"] = False

    # Indicium 2: US birthplace
    if is_us_country(client.country_of_birth):
        indicia.append("US birthplace")
        indicia_details["us_birthplace"] = True
    else:
        indicia_details["us_birthplace"] = False

    # Indicium 3: US residence address
    if client.address and is_us_country(client.address.country):
        indicia.append("US residence address")
        indicia_details["us_address"] = True
    else:
        indicia_details["us_address"] = False

    # Indicium 4: US telephone number
    # Not captured in intake model — flag as unchecked
    indicia_details["us_telephone"] = "not_checked"

    # Indicium 5: Standing instructions to transfer to US account
    indicia_details["us_transfer_instructions"] = "not_checked"

    # Indicium 6: Power of attorney to person with US address
    indicia_details["us_poa"] = "not_checked"

    # Indicium 7: "In care of" or "hold mail" address as sole address
    has_hold_mail = False
    if client.address and client.address.street:
        street_lower = client.address.street.lower()
        if "c/o" in street_lower or "in care of" in street_lower or "hold mail" in street_lower:
            has_hold_mail = True
            indicia.append("'In care of' or 'hold mail' address detected")
    indicia_details["hold_mail_address"] = has_hold_mail

    # Check US tax residency
    us_tax_resident = any(is_us_country(t) for t in client.tax_residencies)
    if us_tax_resident and "US citizenship" not in indicia and not client.us_person:
        indicia.append("US tax residency declared")
    indicia_details["us_tax_residency"] = us_tax_resident

    # Check US TIN
    if client.us_tin:
        if not indicia:
            indicia.append("US TIN provided without other US indicia declared")
        indicia_details["us_tin_provided"] = True
    else:
        indicia_details["us_tin_provided"] = False

    # Determine classification — flag as US person if ANY indicator present
    is_us_birth = is_us_country(client.country_of_birth)
    us_person = client.us_person or is_us_citizen or us_tax_resident or is_us_birth
    indicia_found = len(indicia) > 0

    # Build explicit indicator list for audit trail
    potential_us_person_indicators: list[str] = []
    if is_us_citizen:
        potential_us_person_indicators.append("US citizenship")
    if client.us_person:
        potential_us_person_indicators.append("US person self-declaration")
    if us_tax_resident:
        potential_us_person_indicators.append("US tax residency")
    if is_us_birth:
        potential_us_person_indicators.append("US country of birth")
    if client.us_tin:
        potential_us_person_indicators.append("US TIN provided")

    # Unchecked indicia (items we cannot verify from intake alone)
    unchecked = [
        k for k, v in indicia_details.items() if v == "not_checked"
    ]

    # Follow-up actions for unchecked indicia
    follow_up_actions: list[str] = []
    _follow_up_map = {
        "us_telephone": "US telephone: Verify during account setup — request primary phone number",
        "us_transfer_instructions": "Standing instructions: Check after first 90 days of account activity",
        "us_poa": "Power of attorney: Verify during document collection phase",
    }
    for indicium_key in unchecked:
        guidance = _follow_up_map.get(indicium_key)
        if guidance:
            follow_up_actions.append(guidance)

    fatca_result = {
        "us_person": us_person,
        "indicia_found": indicia_found,
        "indicia": indicia,
        "indicia_details": indicia_details,
        "potential_us_person_indicators": potential_us_person_indicators,
        "unchecked_indicia": unchecked,
        "follow_up_actions": follow_up_actions,
        "w9_required": us_person,
        "w8ben_required": indicia_found and not us_person,
        "reporting_required": us_person,
    }

    # Build evidence
    if indicia_found:
        evidence.append({
            "evidence_id": f"fatca_indicia_{client.full_name.lower().replace(' ', '_')}",
            "source_type": "utility",
            "source_name": "individual_fatca_crs",
            "entity_screened": client.full_name,
            "entity_context": "individual client — FATCA assessment",
            "claim": (
                f"FATCA US indicia found: {len(indicia)} indicator(s). "
                f"US person determination: {'YES' if us_person else 'NO (indicia require curing)'}."
            ),
            "evidence_level": "S",
            "supporting_data": [
                {"indicia": indicia},
                {"us_person": us_person},
                {"unchecked_indicia_count": len(unchecked)},
            ],
            "disposition": "PENDING_REVIEW",
            "confidence": "HIGH" if us_person else "MEDIUM",
            "timestamp": timestamp,
        })
    else:
        evidence.append({
            "evidence_id": f"fatca_clear_{client.full_name.lower().replace(' ', '_')}",
            "source_type": "utility",
            "source_name": "individual_fatca_crs",
            "entity_screened": client.full_name,
            "entity_context": "individual client — FATCA assessment",
            "claim": (
                "No US indicia identified from available intake data. "
                f"{len(unchecked)} indicia could not be checked from intake alone."
            ),
            "evidence_level": "S",
            "supporting_data": [
                {"indicia": []},
                {"unchecked_indicia_count": len(unchecked)},
            ],
            "disposition": "CLEAR",
            "confidence": "MEDIUM",
            "timestamp": timestamp,
        })

    return fatca_result


def _assess_crs(
    client: IndividualClient, timestamp: str, evidence: list
) -> dict:
    """Assess CRS obligations based on tax residencies."""
    # Identify non-Canadian tax residencies
    non_canadian = [
        t for t in client.tax_residencies
        if t.strip().lower() not in ("canada", "ca")
    ]

    # Filter out US (uses FATCA, not CRS)
    crs_jurisdictions = [
        t for t in non_canadian if t not in CRS_NON_PARTICIPATING
    ]

    # US is reported under FATCA, not CRS
    us_only = [
        t for t in non_canadian if t in CRS_NON_PARTICIPATING
    ]

    # Country of residence may trigger CRS even if not in tax_residencies
    residence = (client.country_of_residence or "").strip()
    if (
        residence.lower() not in ("canada", "ca", "")
        and residence not in CRS_NON_PARTICIPATING
        and residence not in crs_jurisdictions
    ):
        crs_jurisdictions.append(residence)

    self_cert_required = len(crs_jurisdictions) > 0 or len(non_canadian) > 0
    reportable = len(crs_jurisdictions) > 0

    crs_result = {
        "reportable_jurisdictions": crs_jurisdictions,
        "us_fatca_only_jurisdictions": us_only,
        "self_certification_required": self_cert_required,
        "reporting_required": reportable,
        "declared_tax_residencies": list(client.tax_residencies),
    }

    # Build evidence
    if reportable:
        evidence.append({
            "evidence_id": f"crs_{client.full_name.lower().replace(' ', '_')}",
            "source_type": "utility",
            "source_name": "individual_fatca_crs",
            "entity_screened": client.full_name,
            "entity_context": "individual client — CRS assessment",
            "claim": (
                f"CRS reporting required for {len(crs_jurisdictions)} jurisdiction(s): "
                f"{', '.join(crs_jurisdictions)}."
            ),
            "evidence_level": "S",
            "supporting_data": [
                {"reportable_jurisdictions": crs_jurisdictions},
                {"declared_residencies": list(client.tax_residencies)},
            ],
            "disposition": "PENDING_REVIEW",
            "confidence": "HIGH",
            "timestamp": timestamp,
        })
    else:
        evidence.append({
            "evidence_id": f"crs_clear_{client.full_name.lower().replace(' ', '_')}",
            "source_type": "utility",
            "source_name": "individual_fatca_crs",
            "entity_screened": client.full_name,
            "entity_context": "individual client — CRS assessment",
            "claim": "No CRS reportable jurisdictions identified.",
            "evidence_level": "S",
            "supporting_data": [
                {"declared_residencies": list(client.tax_residencies)},
            ],
            "disposition": "CLEAR",
            "confidence": "HIGH" if not non_canadian else "MEDIUM",
            "timestamp": timestamp,
        })

    return crs_result
