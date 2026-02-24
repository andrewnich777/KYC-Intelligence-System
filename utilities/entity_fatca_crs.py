"""
Entity FATCA/CRS Classification.

Determines FATCA and CRS obligations for business entities based on
entity classification (FI, Active NFFE, Passive NFFE) and controlling
person analysis. Pure deterministic logic, no API calls.
"""

import re
from datetime import UTC, datetime

from models import BusinessClient
from utilities.reference_data import CRS_NON_PARTICIPATING
from utilities.shared_checks import is_us_country

# Industry keywords that suggest financial institution status
_FI_KEYWORDS = [
    "bank", "credit union", "trust company", "insurance",
    "investment fund", "mutual fund", "hedge fund", "asset management",
    "brokerage", "securities dealer", "custodian", "depository",
    "pension fund", "venture capital", "private equity",
]

# Industry keywords that suggest passive income entity
_PASSIVE_KEYWORDS = [
    "holding company", "investment holding", "family office",
    "trust", "estate", "passive investment", "rental income",
    "royalty", "licensing revenue",
]

# Pre-compiled word-boundary patterns for FI and passive keyword matching
_FI_PATTERN = re.compile(
    r'\b(?:' + '|'.join(re.escape(kw) for kw in _FI_KEYWORDS) + r')\b',
    re.IGNORECASE,
)
_PASSIVE_PATTERN = re.compile(
    r'\b(?:' + '|'.join(re.escape(kw) for kw in _PASSIVE_KEYWORDS) + r')\b',
    re.IGNORECASE,
)


def classify_entity_fatca_crs(client: BusinessClient) -> dict:
    """
    Determine FATCA and CRS obligations for a business entity.

    Returns dict with:
        entity_classification: str — FI, active_nffe, passive_nffe, or undetermined
        fatca: dict — FATCA analysis
        crs: dict — CRS analysis
        required_forms: list of str — forms required
        reporting_obligations: list of str — reporting obligations
        controlling_persons: list of dicts — controlling person assessments
        evidence: list of EvidenceRecord-compatible dicts

    Classification hierarchy:
    1. Financial Institution (FI) -> reports under own obligations
    2. Active NFFE -> no FATCA reporting (meets active income test)
    3. Passive NFFE -> look through to controlling persons (>25% ownership)
    """
    timestamp = datetime.now(UTC).isoformat()
    evidence = []

    # Step 1: Classify the entity
    entity_class = _classify_entity(client)

    # Step 2: Assess FATCA obligations
    fatca_result = _assess_entity_fatca(client, entity_class, timestamp, evidence)

    # Step 3: Assess CRS obligations
    crs_result = _assess_entity_crs(client, entity_class, timestamp, evidence)

    # Step 4: Assess controlling persons (for Passive NFFE)
    controlling_persons = []
    if entity_class == "passive_nffe":
        controlling_persons = _assess_controlling_persons(
            client, timestamp, evidence
        )

    # Step 5: Determine required forms and reporting
    required_forms = _determine_required_forms(
        client, entity_class, fatca_result, crs_result, controlling_persons
    )
    reporting_obligations = _determine_reporting_obligations(
        client, entity_class, fatca_result, crs_result, controlling_persons
    )

    # Build classification evidence
    entity_key = client.legal_name.lower().replace(" ", "_")
    evidence.insert(0, {
        "evidence_id": f"entity_class_{entity_key}",
        "source_type": "utility",
        "source_name": "entity_fatca_crs",
        "entity_screened": client.legal_name,
        "entity_context": "business client — entity classification",
        "claim": (
            f"Entity classified as: {entity_class}. "
            f"FATCA reporting: {'required' if fatca_result['reporting_required'] else 'not required'}. "
            f"CRS reporting: {'required' if crs_result['reporting_required'] else 'not required'}."
        ),
        "evidence_level": "S",
        "supporting_data": [
            {"entity_classification": entity_class},
            {"fatca_reporting": fatca_result["reporting_required"]},
            {"crs_reporting": crs_result["reporting_required"]},
            {"controlling_persons_assessed": len(controlling_persons)},
        ],
        "disposition": "PENDING_REVIEW",
        "confidence": "MEDIUM",
        "timestamp": timestamp,
    })

    return {
        "entity_classification": entity_class,
        "fatca": fatca_result,
        "crs": crs_result,
        "required_forms": required_forms,
        "reporting_obligations": reporting_obligations,
        "controlling_persons": controlling_persons,
        "evidence": evidence,
    }


def _classify_entity(client: BusinessClient) -> str:
    """
    Classify entity into FI, Active NFFE, or Passive NFFE.

    Classification hierarchy:
    1. FI — if industry/nature suggests financial institution
    2. Active NFFE — if business has active commercial operations
    3. Passive NFFE — if income is primarily passive (investment, royalties)
    4. Undetermined — if insufficient data
    """
    industry = (client.industry or "").lower()
    nature = (client.nature_of_business or "").lower()
    biz_type = (client.business_type or "").lower()
    combined = f"{industry} {nature} {biz_type}"

    # Check for Financial Institution indicators (word-boundary matching)
    if _FI_PATTERN.search(combined):
        return "financial_institution"

    # Check for passive income indicators (word-boundary matching)
    if _PASSIVE_PATTERN.search(combined):
        return "passive_nffe"

    # If entity has substantial revenue and active business operations,
    # classify as Active NFFE
    if client.annual_revenue and client.annual_revenue > 0:
        # Active NFFE test: >50% of income from active business
        # Since we cannot verify exact income split from intake data alone,
        # we infer from business nature
        if any(
            kw in combined
            for kw in [
                "manufacturing", "retail", "wholesale", "technology",
                "consulting", "construction", "transportation",
                "healthcare", "agriculture", "mining", "energy",
                "telecommunications", "media", "education",
                "hospitality", "food", "services",
            ]
        ):
            return "active_nffe"

    # If entity has active operations but no clear classification
    if client.nature_of_business and not any(kw in combined for kw in _PASSIVE_KEYWORDS):
        return "active_nffe"

    # Default: insufficient data to determine
    if not client.nature_of_business and not client.industry:
        return "undetermined"

    # Conservative default for entities we cannot clearly classify
    return "passive_nffe"


def _assess_entity_fatca(
    client: BusinessClient,
    entity_class: str,
    timestamp: str,
    evidence: list,
) -> dict:
    """Assess FATCA obligations for the entity."""
    us_nexus_indicators = []

    # Check entity-level US nexus
    if client.us_nexus:
        us_nexus_indicators.append("Entity self-declared US nexus")

    if client.us_tin:
        us_nexus_indicators.append("US TIN provided")

    # Check incorporation jurisdiction
    if is_us_country(client.incorporation_jurisdiction):
        us_nexus_indicators.append("Incorporated in the United States")

    # Check countries of operation
    for country in client.countries_of_operation:
        if is_us_country(country):
            us_nexus_indicators.append(f"Operations in: {country}")
            break

    # Check UBO US person status
    us_ubos = [
        ubo for ubo in client.beneficial_owners if ubo.us_person
    ]
    if us_ubos:
        for ubo in us_ubos:
            us_nexus_indicators.append(
                f"US person beneficial owner: {ubo.full_name} "
                f"({ubo.ownership_percentage}%)"
            )

    has_us_nexus = len(us_nexus_indicators) > 0

    # Determine reporting based on entity classification
    if entity_class == "financial_institution":
        reporting_required = True  # FIs always report
        classification_note = (
            "Financial Institution — reports under own FATCA obligations"
        )
    elif entity_class == "active_nffe":
        reporting_required = has_us_nexus
        classification_note = (
            "Active NFFE — FATCA reporting only if US nexus present"
        )
    elif entity_class == "passive_nffe":
        reporting_required = has_us_nexus or len(us_ubos) > 0
        classification_note = (
            "Passive NFFE — look-through to controlling persons required"
        )
    else:
        reporting_required = has_us_nexus
        classification_note = (
            "Entity classification undetermined — conservative FATCA treatment"
        )

    result = {
        "us_nexus": has_us_nexus,
        "us_nexus_indicators": us_nexus_indicators,
        "us_beneficial_owners": [
            {
                "name": ubo.full_name,
                "ownership_percentage": ubo.ownership_percentage,
            }
            for ubo in us_ubos
        ],
        "reporting_required": reporting_required,
        "classification_note": classification_note,
        "w8_or_w9_required": has_us_nexus,
    }

    # Build evidence
    if has_us_nexus:
        entity_key = client.legal_name.lower().replace(" ", "_")
        evidence.append({
            "evidence_id": f"fatca_entity_{entity_key}",
            "source_type": "utility",
            "source_name": "entity_fatca_crs",
            "entity_screened": client.legal_name,
            "entity_context": "business client — FATCA assessment",
            "claim": (
                f"US nexus identified: {len(us_nexus_indicators)} indicator(s). "
                f"Entity class: {entity_class}. FATCA reporting required."
            ),
            "evidence_level": "S",
            "supporting_data": [
                {"us_nexus_indicators": us_nexus_indicators},
                {"us_beneficial_owners_count": len(us_ubos)},
            ],
            "disposition": "PENDING_REVIEW",
            "confidence": "HIGH",
            "timestamp": timestamp,
        })

    return result


def _assess_entity_crs(
    client: BusinessClient,
    entity_class: str,
    timestamp: str,
    evidence: list,
) -> dict:
    """Assess CRS obligations for the entity."""
    # Collect all non-Canadian jurisdictions
    all_jurisdictions = set()

    for country in client.countries_of_operation:
        if country.strip().lower() not in ("canada", "ca"):
            all_jurisdictions.add(country)

    if client.incorporation_jurisdiction:
        inc = client.incorporation_jurisdiction.strip()
        if inc.lower() not in ("canada", "ca"):
            all_jurisdictions.add(inc)

    # UBO tax residencies
    ubo_crs_jurisdictions = set()
    for ubo in client.beneficial_owners:
        for tax_res in ubo.tax_residencies:
            if tax_res.strip().lower() not in ("canada", "ca"):
                ubo_crs_jurisdictions.add(tax_res)
        if ubo.country_of_residence:
            res = ubo.country_of_residence.strip()
            if res.lower() not in ("canada", "ca"):
                ubo_crs_jurisdictions.add(res)

    # Filter out US (FATCA, not CRS) for entity-level
    crs_entity_jurisdictions = [
        j for j in all_jurisdictions if j not in CRS_NON_PARTICIPATING
    ]
    crs_ubo_jurisdictions = [
        j for j in ubo_crs_jurisdictions if j not in CRS_NON_PARTICIPATING
    ]

    # For passive NFFE, UBO jurisdictions are reportable
    if entity_class == "passive_nffe":
        reportable = list(set(crs_entity_jurisdictions + crs_ubo_jurisdictions))
    else:
        reportable = crs_entity_jurisdictions

    reporting_required = len(reportable) > 0
    self_cert_required = reporting_required or len(all_jurisdictions) > 0

    result = {
        "reportable_jurisdictions": reportable,
        "entity_level_jurisdictions": crs_entity_jurisdictions,
        "ubo_level_jurisdictions": crs_ubo_jurisdictions,
        "self_certification_required": self_cert_required,
        "reporting_required": reporting_required,
    }

    # Build evidence
    if reporting_required:
        entity_key = client.legal_name.lower().replace(" ", "_")
        evidence.append({
            "evidence_id": f"crs_entity_{entity_key}",
            "source_type": "utility",
            "source_name": "entity_fatca_crs",
            "entity_screened": client.legal_name,
            "entity_context": "business client — CRS assessment",
            "claim": (
                f"CRS reporting required for {len(reportable)} jurisdiction(s): "
                f"{', '.join(reportable)}."
            ),
            "evidence_level": "S",
            "supporting_data": [
                {"entity_jurisdictions": crs_entity_jurisdictions},
                {"ubo_jurisdictions": crs_ubo_jurisdictions},
            ],
            "disposition": "PENDING_REVIEW",
            "confidence": "HIGH",
            "timestamp": timestamp,
        })

    return result


def _assess_controlling_persons(
    client: BusinessClient,
    timestamp: str,
    evidence: list,
) -> list:
    """
    Assess each controlling person (beneficial owner with >25% ownership)
    for US indicia and CRS residency.
    """
    controlling_persons = []

    for ubo in client.beneficial_owners:
        if ubo.ownership_percentage < 25:
            continue

        person = {
            "name": ubo.full_name,
            "ownership_percentage": ubo.ownership_percentage,
            "role": ubo.role,
            "us_indicia": [],
            "crs_jurisdictions": [],
        }

        # Check US indicia for this controlling person
        if ubo.us_person:
            person["us_indicia"].append("Self-declared US person")
        if ubo.citizenship and is_us_country(ubo.citizenship):
            person["us_indicia"].append("US citizenship")
        if ubo.country_of_residence and is_us_country(ubo.country_of_residence):
            person["us_indicia"].append("US residence")
        us_tax = [
            t for t in ubo.tax_residencies
            if is_us_country(t)
        ]
        if us_tax:
            person["us_indicia"].append("US tax residency")

        person["is_us_person"] = len(person["us_indicia"]) > 0

        # Check CRS jurisdictions
        non_ca_residencies = [
            t for t in ubo.tax_residencies
            if t.strip().lower() not in ("canada", "ca")
        ]
        person["crs_jurisdictions"] = [
            t for t in non_ca_residencies if t not in CRS_NON_PARTICIPATING
        ]

        if ubo.country_of_residence:
            res = ubo.country_of_residence.strip()
            if (
                res.lower() not in ("canada", "ca")
                and res not in CRS_NON_PARTICIPATING
                and res not in person["crs_jurisdictions"]
            ):
                person["crs_jurisdictions"].append(res)

        person["crs_reportable"] = len(person["crs_jurisdictions"]) > 0

        # Required forms for this person
        person["required_forms"] = []
        if person["is_us_person"]:
            person["required_forms"].append("IRS Form W-9")
        if person["crs_reportable"]:
            person["required_forms"].append("CRS Self-Certification (controlling person)")

        controlling_persons.append(person)

        # Build evidence for each flagged controlling person
        if person["is_us_person"] or person["crs_reportable"]:
            ubo_key = ubo.full_name.lower().replace(" ", "_")
            evidence.append({
                "evidence_id": f"cp_{ubo_key}_{client.legal_name.lower().replace(' ', '_')}",
                "source_type": "utility",
                "source_name": "entity_fatca_crs",
                "entity_screened": ubo.full_name,
                "entity_context": (
                    f"Controlling person of {client.legal_name} "
                    f"({ubo.ownership_percentage}% owner)"
                ),
                "claim": (
                    f"Controlling person FATCA/CRS flags: "
                    f"US person={'YES' if person['is_us_person'] else 'NO'}, "
                    f"CRS jurisdictions={person['crs_jurisdictions'] or 'none'}."
                ),
                "evidence_level": "S",
                "supporting_data": [
                    {"us_indicia": person["us_indicia"]},
                    {"crs_jurisdictions": person["crs_jurisdictions"]},
                    {"required_forms": person["required_forms"]},
                ],
                "disposition": "PENDING_REVIEW",
                "confidence": "HIGH" if person["is_us_person"] else "MEDIUM",
                "timestamp": timestamp,
            })

    return controlling_persons


def _determine_required_forms(
    client: BusinessClient,
    entity_class: str,
    fatca: dict,
    crs: dict,
    controlling_persons: list,
) -> list:
    """Determine all required FATCA/CRS forms."""
    forms = []

    # Entity-level forms
    if entity_class == "financial_institution":
        forms.append("FATCA Financial Institution registration confirmation")
    elif fatca["us_nexus"]:
        if entity_class == "active_nffe":
            forms.append(
                "IRS Form W-8BEN-E (Certificate of Status — Active NFFE)"
            )
        else:
            forms.append(
                "IRS Form W-8BEN-E (Certificate of Status — Passive NFFE)"
            )
    else:
        forms.append(
            "IRS Form W-8BEN-E (Certificate of Foreign Status of Beneficial Owner)"
        )

    if crs["self_certification_required"]:
        forms.append("CRS Entity Self-Certification Form")

    # Controlling person forms
    for cp in controlling_persons:
        forms.extend(cp.get("required_forms", []))

    # Deduplicate while preserving order
    seen = set()
    unique_forms = []
    for f in forms:
        if f not in seen:
            seen.add(f)
            unique_forms.append(f)

    return unique_forms


def _determine_reporting_obligations(
    client: BusinessClient,
    entity_class: str,
    fatca: dict,
    crs: dict,
    controlling_persons: list,
) -> list:
    """Determine all reporting obligations."""
    obligations = []

    if fatca["reporting_required"]:
        if entity_class == "financial_institution":
            obligations.append(
                "FATCA: entity reports under own FI obligations"
            )
        elif entity_class == "passive_nffe":
            us_cps = [cp for cp in controlling_persons if cp.get("is_us_person")]
            if us_cps:
                names = ", ".join(cp["name"] for cp in us_cps)
                obligations.append(
                    f"FATCA: report US controlling persons ({names}) — annual, by May 1"
                )
            if fatca["us_nexus"]:
                obligations.append(
                    "FATCA: entity-level reporting for US nexus — annual, by May 1"
                )
        else:
            obligations.append(
                "FATCA: entity reporting for US nexus — annual, by May 1"
            )

    if crs["reporting_required"]:
        for jurisdiction in crs["reportable_jurisdictions"]:
            obligations.append(
                f"CRS: report to {jurisdiction} — annual, by May 1"
            )

    if not obligations:
        obligations.append(
            "No FATCA/CRS reporting obligations identified at this time"
        )

    return obligations
