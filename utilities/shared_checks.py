"""
Shared utility functions for logic duplicated across 3+ files.

Centralizes US indicia checking, PEP classification, STR triggers,
and ownership analysis.
"""

from constants import CANADA_TERMS, US_TERMS


def is_us_country(country: str) -> bool:
    """Check if a country string refers to the United States."""
    return (country or "").strip().lower() in US_TERMS


def is_canada_country(country: str) -> bool:
    """Check if a country string refers to Canada."""
    return (country or "").strip().lower() in CANADA_TERMS


def check_individual_us_indicia(client) -> list[str]:
    """
    Check 7 US indicia per IRS FATCA requirements for an individual client.
    Returns list of indicia descriptions found.
    """
    indicia = []

    # 1. US citizenship
    if client.citizenship and is_us_country(client.citizenship):
        indicia.append("US citizenship")

    # 2. US birth
    if client.country_of_birth and is_us_country(client.country_of_birth):
        indicia.append("US birthplace")

    # 3. US person declaration
    if client.us_person:
        if "US citizenship" not in indicia:
            indicia.append("US person (self-declared)")

    # 4. US address
    if client.address and is_us_country(client.address.country or ""):
        indicia.append("US residence address")

    # 5. US tax residency
    if any(is_us_country(t) for t in client.tax_residencies):
        if "US citizenship" not in indicia and not client.us_person:
            indicia.append("US tax residency declared")

    # 6. US TIN provided
    if client.us_tin:
        if not indicia:
            indicia.append("US TIN provided without other US indicia declared")

    return indicia


def check_entity_us_nexus(client) -> list[str]:
    """
    Check US nexus indicators for a business entity.
    Returns list of US nexus indicator descriptions.
    """
    indicators = []

    if client.us_nexus:
        indicators.append("Entity self-declared US nexus")

    if getattr(client, "us_tin", None):
        indicators.append("US TIN provided")

    inc_jurisdiction = (getattr(client, "incorporation_jurisdiction", "") or "").strip()
    if is_us_country(inc_jurisdiction):
        indicators.append("Incorporated in the United States")

    for country in getattr(client, "countries_of_operation", []):
        if is_us_country(country):
            indicators.append(f"Operations in: {country}")
            break

    us_ubos = [
        ubo for ubo in getattr(client, "beneficial_owners", [])
        if ubo.us_person
    ]
    for ubo in us_ubos:
        indicators.append(
            f"US person beneficial owner: {ubo.full_name} "
            f"({ubo.ownership_percentage}%)"
        )

    return indicators


def classify_pep_from_investigation(investigation) -> tuple[str, int]:
    """
    Classify PEP level from investigation results.
    Returns (pep_level_value, risk_points).
    """
    if not investigation or not investigation.pep_classification:
        return ("NOT_PEP", 0)

    from models import PEPLevel
    pep = investigation.pep_classification
    level = pep.detected_level

    if level == PEPLevel.FOREIGN_PEP:
        return (level.value, 40)
    elif level == PEPLevel.DOMESTIC_PEP:
        return (level.value, 25)
    elif level == PEPLevel.HIO:
        return (level.value, 30)
    elif level in (PEPLevel.PEP_FAMILY, PEPLevel.PEP_ASSOCIATE):
        return (level.value, 20)
    else:
        return ("NOT_PEP", 0)


def check_pep_edd_triggers(client, investigation) -> list[dict]:
    """
    Check PEP-related EDD triggers from both self-declaration and investigation.
    Returns list of trigger dicts with 'trigger' and 'source' keys.
    """
    from models import BusinessClient, IndividualClient, PEPLevel

    triggers = []

    # Self-declaration
    if isinstance(client, IndividualClient) and client.pep_self_declaration:
        pep_details = (client.pep_details or "").lower()
        if any(kw in pep_details for kw in ("foreign", "international")):
            triggers.append({
                "trigger": "Foreign PEP (self-declared) — permanent EDD requirement",
                "source": "self_declaration",
            })
        elif any(kw in pep_details for kw in ("head of international", "hio")):
            triggers.append({
                "trigger": "Head of International Organization (self-declared) — 5-year EDD from leaving office",
                "source": "self_declaration",
            })
        else:
            triggers.append({
                "trigger": "Domestic PEP (self-declared) — 5-year EDD from leaving office",
                "source": "self_declaration",
            })

    # Investigation-detected PEP
    if investigation and investigation.pep_classification:
        pep = investigation.pep_classification
        existing_trigger_texts = [t["trigger"] for t in triggers]

        # Check if PEP EDD window has expired (domestic PEP / HIO: 5 years after leaving office)
        pep_edd_expired = False
        if pep.edd_expiry_date:
            try:
                from datetime import datetime
                expiry = datetime.strptime(pep.edd_expiry_date[:10], "%Y-%m-%d")
                if expiry < datetime.now():
                    pep_edd_expired = True
            except (ValueError, TypeError):
                pass

        if pep.detected_level == PEPLevel.FOREIGN_PEP:
            trigger = "Foreign PEP (investigation-detected) — permanent EDD requirement"
            if trigger not in existing_trigger_texts:
                triggers.append({"trigger": trigger, "source": "investigation"})
        elif pep.detected_level == PEPLevel.DOMESTIC_PEP:
            if pep_edd_expired:
                trigger = "Former domestic PEP (EDD window expired) — standard monitoring"
                if trigger not in existing_trigger_texts:
                    triggers.append({"trigger": trigger, "source": "investigation", "expired": True})
            else:
                trigger = "Domestic PEP (investigation-detected) — 5-year EDD"
                if trigger not in existing_trigger_texts:
                    triggers.append({"trigger": trigger, "source": "investigation"})
        elif pep.detected_level == PEPLevel.HIO:
            if pep_edd_expired:
                trigger = "Former HIO (EDD window expired) — standard monitoring"
                if trigger not in existing_trigger_texts:
                    triggers.append({"trigger": trigger, "source": "investigation", "expired": True})
            else:
                trigger = "Head of International Organization (detected) — 5-year EDD"
                if trigger not in existing_trigger_texts:
                    triggers.append({"trigger": trigger, "source": "investigation"})
        elif pep.detected_level in (PEPLevel.PEP_FAMILY, PEPLevel.PEP_ASSOCIATE):
            triggers.append({
                "trigger": (
                    f"PEP family member/close associate ({pep.detected_level.value}) — "
                    "EDD required per FINTRAC"
                ),
                "source": "investigation",
            })

    # Business UBO PEP declarations
    if isinstance(client, BusinessClient):
        for ubo in client.beneficial_owners:
            if ubo.pep_self_declaration:
                triggers.append({
                    "trigger": (
                        f"Beneficial owner PEP: {ubo.full_name} "
                        f"({ubo.ownership_percentage}% owner)"
                    ),
                    "source": "ubo_declaration",
                })

    return triggers


def check_str_triggers(client, investigation) -> list[str]:
    """
    Check for Suspicious Transaction Report triggers.
    Returns list of trigger description strings.
    """
    from constants import DEPOSIT_INCOME_RATIO_SUSPICIOUS, WEALTH_INCOME_RATIO_VERY_HIGH
    from models import (
        AdverseMediaLevel,
        BusinessClient,
        DispositionStatus,
        IndividualClient,
    )

    str_triggers = []

    if investigation:
        # Sanctions concerns
        for sr in [investigation.individual_sanctions, investigation.entity_sanctions]:
            if sr and sr.disposition in (
                DispositionStatus.POTENTIAL_MATCH,
                DispositionStatus.CONFIRMED_MATCH,
            ):
                str_triggers.append(
                    f"Sanctions {sr.disposition.value}: {sr.entity_screened}"
                )

        # Adverse media suggesting financial crime
        for mr in [investigation.individual_adverse_media, investigation.business_adverse_media]:
            if mr and mr.overall_level in (
                AdverseMediaLevel.HIGH_RISK,
                AdverseMediaLevel.MATERIAL_CONCERN,
            ):
                crime_categories = [
                    c for c in mr.categories
                    if c in (
                        "fraud", "money_laundering", "terrorist_financing",
                        "bribery", "corruption", "tax_evasion",
                        "sanctions_evasion", "organized_crime",
                    )
                ]
                if crime_categories:
                    str_triggers.append(
                        f"Adverse media ({mr.overall_level.value}) for "
                        f"'{mr.entity_screened}': {', '.join(crime_categories)}"
                    )

        # UBO sanctions matches
        if investigation.ubo_screening:
            for ubo_name, ubo_data in investigation.ubo_screening.items():
                if isinstance(ubo_data, dict) and "sanctions" in ubo_data:
                    s = ubo_data["sanctions"]
                    if isinstance(s, dict) and s.get("disposition") in (
                        "POTENTIAL_MATCH", "CONFIRMED_MATCH"
                    ):
                        str_triggers.append(f"UBO sanctions match: {ubo_name}")

    # Unusual patterns based on client data
    if isinstance(client, IndividualClient):
        if (
            client.annual_income
            and client.net_worth
            and client.annual_income > 0
            and client.net_worth / client.annual_income > WEALTH_INCOME_RATIO_VERY_HIGH
        ):
            str_triggers.append(
                "Unusual wealth/income ratio may warrant further inquiry"
            )
    elif isinstance(client, BusinessClient):
        if (
            client.expected_transaction_volume
            and client.annual_revenue
            and client.annual_revenue > 0
            and client.expected_transaction_volume / client.annual_revenue > DEPOSIT_INCOME_RATIO_SUSPICIOUS
        ):
            str_triggers.append(
                "Transaction volume significantly exceeds revenue — "
                "potential pass-through activity"
            )

    return str_triggers


def analyze_ownership_structure(beneficial_owners: list) -> dict:
    """
    Analyze ownership structure complexity and transparency.
    Returns dict with risk_level, total_owners, ownership_coverage, concerns.
    """
    from constants import (
        UBO_COMPLEX_OWNERSHIP_THRESHOLD,
        UBO_OWNERSHIP_COVERAGE_CONCERN,
    )
    from utilities.reference_data import FATF_BLACK_LIST, FATF_GREY_LIST

    analysis = {
        "risk_level": "low",
        "total_owners": len(beneficial_owners),
        "ownership_coverage": 0.0,
        "concerns": [],
        "multi_jurisdictional": False,
        "pep_owners": [],
        "high_risk_jurisdiction_owners": [],
    }

    if not beneficial_owners:
        analysis["risk_level"] = "high"
        analysis["concerns"].append(
            "No beneficial owners declared — ownership structure opaque"
        )
        return analysis

    total_ownership = sum(ubo.ownership_percentage for ubo in beneficial_owners)
    analysis["ownership_coverage"] = round(total_ownership, 2)

    if total_ownership < UBO_OWNERSHIP_COVERAGE_CONCERN:
        analysis["risk_level"] = "high"
        analysis["concerns"].append(
            f"Only {total_ownership:.0f}% of ownership identified — "
            f"{100 - total_ownership:.0f}% unaccounted for"
        )

    num_ubos = len(beneficial_owners)
    if num_ubos > UBO_COMPLEX_OWNERSHIP_THRESHOLD:
        analysis["risk_level"] = "high"
        analysis["concerns"].append(
            f"Complex ownership: {num_ubos} beneficial owners"
        )

    # Multi-jurisdictional check
    ubo_countries = set()
    for ubo in beneficial_owners:
        if ubo.citizenship:
            ubo_countries.add(ubo.citizenship)
        if ubo.country_of_residence:
            ubo_countries.add(ubo.country_of_residence)

    non_ca_countries = {
        c for c in ubo_countries
        if (c or "").lower() not in ("canada", "ca")
    }
    if len(non_ca_countries) > 3:
        analysis["multi_jurisdictional"] = True
        analysis["risk_level"] = "high"
        analysis["concerns"].append(
            f"Beneficial owners span {len(non_ca_countries)} non-Canadian jurisdictions"
        )

    # PEP beneficial owners
    for ubo in beneficial_owners:
        if ubo.pep_self_declaration:
            analysis["pep_owners"].append(ubo.full_name)
            analysis["risk_level"] = "high"

    # High-risk jurisdiction UBOs
    for ubo in beneficial_owners:
        countries = []
        if ubo.citizenship:
            countries.append(ubo.citizenship)
        if ubo.country_of_residence:
            countries.append(ubo.country_of_residence)
        for country in countries:
            if country in FATF_BLACK_LIST or country in FATF_GREY_LIST:
                analysis["high_risk_jurisdiction_owners"].append(
                    {"name": ubo.full_name, "country": country}
                )
                if country in FATF_BLACK_LIST:
                    analysis["risk_level"] = "high"
                elif analysis["risk_level"] == "low":
                    analysis["risk_level"] = "medium"

    return analysis
