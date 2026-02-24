"""
Regulation detector — maps client attributes to applicable regulatory frameworks.

Always applies: FINTRAC (PCMLTFA), CIRO (KYC Rule 3202)
Conditional: OFAC (US nexus), FATCA (US indicia), CRS (non-CA tax residency), EDD (FATF grey/black)
"""

from models import BusinessClient, IndividualClient
from utilities.reference_data import (
    CRS_NON_PARTICIPATING,
    FATF_BLACK_LIST,
    FATF_GREY_LIST,
)
from utilities.shared_checks import check_individual_us_indicia


def detect_applicable_regulations(client) -> list[str]:
    """
    Determine which regulatory frameworks apply to this client.

    Returns list of regulation identifiers:
    - FINTRAC: Always (Canadian financial institution)
    - CIRO: Always (investment dealer KYC)
    - OFAC: If US nexus
    - FATCA: If US indicia
    - CRS: If non-Canadian tax residency
    - EDD: If FATF grey/black country involvement
    """
    regulations = ["FINTRAC", "CIRO"]

    if isinstance(client, IndividualClient):
        # OFAC - US person or US connection
        if client.us_person:
            if "OFAC" not in regulations:
                regulations.append("OFAC")
            if "FATCA" not in regulations:
                regulations.append("FATCA")

        # FATCA - US indicia check (7 indicators per IRS)
        us_indicia = check_individual_us_indicia(client)
        if us_indicia and "FATCA" not in regulations:
            regulations.append("FATCA")

        # CRS - non-Canadian tax residency
        non_ca = [t for t in client.tax_residencies if t.lower() not in ("canada", "ca")]
        crs_applicable = [t for t in non_ca if t not in CRS_NON_PARTICIPATING]
        if crs_applicable:
            regulations.append("CRS")

        # EDD - FATF grey/black country
        countries_to_check = [
            client.citizenship,
            client.country_of_residence,
            client.country_of_birth,
        ] + client.tax_residencies

        for country in countries_to_check:
            if country and (country in FATF_GREY_LIST or country in FATF_BLACK_LIST):
                if "EDD" not in regulations:
                    regulations.append("EDD")
                break

    elif isinstance(client, BusinessClient):
        # OFAC - US nexus
        if client.us_nexus:
            if "OFAC" not in regulations:
                regulations.append("OFAC")
            if "FATCA" not in regulations:
                regulations.append("FATCA")

        # Check UBOs for US indicia
        for ubo in client.beneficial_owners:
            if ubo.us_person:
                if "FATCA" not in regulations:
                    regulations.append("FATCA")
                if "OFAC" not in regulations:
                    regulations.append("OFAC")

        # CRS - non-Canadian operations or UBO tax residencies
        all_countries = list(client.countries_of_operation)
        for ubo in client.beneficial_owners:
            all_countries.extend(ubo.tax_residencies)

        non_ca = [c for c in all_countries if c.lower() not in ("canada", "ca")]
        crs_applicable = [c for c in non_ca if c not in CRS_NON_PARTICIPATING]
        if crs_applicable:
            if "CRS" not in regulations:
                regulations.append("CRS")

        # EDD - FATF countries in operations or UBO nationality
        countries_to_check = list(client.countries_of_operation)
        if client.incorporation_jurisdiction:
            countries_to_check.append(client.incorporation_jurisdiction)
        for ubo in client.beneficial_owners:
            if ubo.citizenship:
                countries_to_check.append(ubo.citizenship)
            if ubo.country_of_residence:
                countries_to_check.append(ubo.country_of_residence)

        for country in countries_to_check:
            if country and (country in FATF_GREY_LIST or country in FATF_BLACK_LIST):
                if "EDD" not in regulations:
                    regulations.append("EDD")
                break

    return regulations
