"""
Static reference data for KYC risk assessment.
FATF lists, high-risk industries, offshore jurisdictions, PEP positions.
"""

# Reference data version — bump when updating any list below
REFERENCE_DATA_VERSION = "2025.1"
FATF_LIST_LAST_UPDATED = "2025-02"
OFAC_LIST_LAST_UPDATED = "2025-01"

# FATF Grey List (Jurisdictions Under Increased Monitoring) — as of 2024-2025
FATF_GREY_LIST = [
    "Algeria", "Angola", "Bulgaria", "Burkina Faso", "Cameroon",
    "Côte d'Ivoire", "Croatia", "Democratic Republic of the Congo",
    "Haiti", "Kenya", "Lebanon", "Mali", "Monaco", "Mozambique",
    "Namibia", "Nigeria", "Philippines", "Senegal", "South Africa",
    "South Sudan", "Syria", "Tanzania", "Venezuela", "Vietnam", "Yemen",
]

# FATF Black List (High-Risk Jurisdictions Subject to a Call for Action)
FATF_BLACK_LIST = [
    "Iran", "Myanmar", "North Korea",
]

# Countries with active OFAC sanctions programs
OFAC_SANCTIONED_COUNTRIES = [
    "Cuba", "Iran", "North Korea", "Syria", "Russia",
    "Belarus", "Venezuela", "Myanmar", "Libya", "Somalia",
    "Sudan", "South Sudan", "Yemen", "Zimbabwe",
    "Central African Republic", "Democratic Republic of the Congo",
    "Iraq", "Lebanon", "Mali", "Nicaragua", "Ethiopia",
]

# Countries with FINTRAC directives or advisories
FINTRAC_HIGH_RISK_COUNTRIES = [
    "Iran", "North Korea",  # Countermeasures
]

# EU High-Risk Third Countries (Commission Delegated Regulation 2016/1675, as amended)
# These overlap with but differ from FATF lists.
EU_HIGH_RISK_THIRD_COUNTRIES = [
    "Afghanistan", "Barbados", "Burkina Faso", "Cameroon",
    "Democratic Republic of the Congo", "Gibraltar", "Haiti",
    "Jamaica", "Mali", "Mozambique", "Myanmar", "Nigeria",
    "Panama", "Philippines", "Senegal", "South Africa",
    "South Sudan", "Syria", "Tanzania", "Trinidad and Tobago",
    "Uganda", "United Arab Emirates", "Vanuatu", "Vietnam", "Yemen",
]

# Basel AML Index — top-40 highest-risk countries (2024 public edition, score 0-10)
# Higher score = higher ML/TF risk.  Published annually by the Basel Institute
# on Governance.  Only the top-40 are hardcoded; agents can look up others.
BASEL_AML_INDEX: dict[str, float] = {
    "Myanmar": 7.76,
    "Haiti": 7.48,
    "Democratic Republic of the Congo": 7.35,
    "Mozambique": 7.25,
    "Madagascar": 7.16,
    "Chad": 7.10,
    "Cameroon": 7.05,
    "Venezuela": 7.01,
    "Senegal": 6.98,
    "Sierra Leone": 6.96,
    "Yemen": 6.93,
    "Afghanistan": 6.90,
    "Nigeria": 6.87,
    "Tanzania": 6.84,
    "Mali": 6.80,
    "Kenya": 6.77,
    "Uganda": 6.73,
    "Vietnam": 6.70,
    "Laos": 6.67,
    "Tajikistan": 6.64,
    "Bolivia": 6.60,
    "Bangladesh": 6.56,
    "Pakistan": 6.53,
    "Cambodia": 6.50,
    "Guinea-Bissau": 6.47,
    "Honduras": 6.43,
    "Paraguay": 6.40,
    "Nepal": 6.37,
    "Angola": 6.33,
    "Nicaragua": 6.30,
    "Burkina Faso": 6.27,
    "Philippines": 6.24,
    "South Sudan": 6.20,
    "Libya": 6.17,
    "Zimbabwe": 6.13,
    "Zambia": 6.10,
    "Algeria": 6.07,
    "Côte d'Ivoire": 6.03,
    "Togo": 6.00,
    "Dominican Republic": 5.97,
}

# High-risk industries for AML/CFT purposes
HIGH_RISK_INDUSTRIES = [
    "money_services_business",
    "virtual_currency_exchange",
    "casino_gaming",
    "precious_metals_stones",
    "real_estate",
    "import_export",
    "arms_defense",
    "cash_intensive_business",
    "art_antiquities",
    "professional_services_trust",
    "non_profit_charity",
    "tobacco",
    "marijuana_cannabis",
    "construction",
    "offshore_banking",
]

# Offshore / tax haven jurisdictions
OFFSHORE_JURISDICTIONS = [
    "British Virgin Islands", "Cayman Islands", "Bermuda",
    "Jersey", "Guernsey", "Isle of Man",
    "Panama", "Bahamas", "Seychelles",
    "Mauritius", "Luxembourg", "Liechtenstein",
    "Monaco", "Andorra", "San Marino",
    "Vanuatu", "Samoa", "Marshall Islands",
    "Belize", "Nevis", "Saint Kitts and Nevis",
    "Turks and Caicos", "Gibraltar", "Malta",
    "Cyprus", "Netherlands Antilles", "Curaçao",
    "Aruba", "Sint Maarten",
]

# PEP positions — used for detection
DOMESTIC_PEP_POSITIONS = [
    "member_of_parliament", "senator", "cabinet_minister",
    "premier", "prime_minister", "governor_general",
    "supreme_court_justice", "federal_court_judge",
    "mayor_major_city", "head_of_government_agency",
    "deputy_minister", "ambassador", "high_commissioner",
    "military_general", "central_bank_governor",
    "crown_corporation_head",
]

FOREIGN_PEP_POSITIONS = [
    "head_of_state", "head_of_government", "cabinet_minister",
    "member_of_parliament", "senator", "supreme_court_justice",
    "ambassador", "high_commissioner", "military_general",
    "central_bank_governor", "state_owned_enterprise_head",
    "senior_political_party_official",
]

HIO_POSITIONS = [
    "un_secretary_general", "un_agency_head",
    "world_bank_president", "imf_managing_director",
    "wto_director_general", "nato_secretary_general",
    "eu_commission_president", "eu_council_president",
    "interpol_president", "icj_judge",
    "who_director_general", "iaea_director_general",
]

# Source of funds categories and their risk weights
SOURCE_OF_FUNDS_RISK = {
    "employment_income": 0,
    "salary": 0,
    "investment_returns": 0,
    "pension": 0,
    "inheritance": 5,
    "gift": 10,
    "business_income": 5,
    "real_estate_sale": 5,
    "legal_settlement": 10,
    "lottery_gambling": 15,
    "cryptocurrency": 15,
    "foreign_transfer": 10,
    "cash_savings": 10,
    "unknown": 20,
}

# Occupation risk levels
HIGH_RISK_OCCUPATIONS = [
    "politician", "government_official", "diplomat",
    "arms_dealer", "casino_operator", "money_service_operator",
    "precious_metals_dealer", "real_estate_developer",
    "lawyer_trust_services", "accountant_offshore",
    "import_export_trader",
]

# CRS participating jurisdictions (most countries — list non-participants)
CRS_NON_PARTICIPATING = [
    "United States",  # Uses FATCA instead
]

# Countries for which FATCA applies (US person determination)
FATCA_TRIGGER_COUNTRIES = ["United States"]


# =============================================================================
# Override Loading (from reference_data_updater.py output)
# =============================================================================

def _load_overrides() -> None:
    """Load reference_data_override.json if it exists, merging with static lists.

    Fail-safe: if the file is missing or corrupt, static lists remain unchanged.
    """
    import json
    from pathlib import Path

    override_path = Path(__file__).parent.parent / "screening_lists" / "reference_data_override.json"
    if not override_path.exists():
        return

    try:
        data = json.loads(override_path.read_text(encoding="utf-8"))
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Could not load reference data overrides from {override_path}: {e}")
        return

    _LIST_MAP = {
        "FATF Grey List": "FATF_GREY_LIST",
        "FATF Black List": "FATF_BLACK_LIST",
        "OFAC Sanctioned Countries": "OFAC_SANCTIONED_COUNTRIES",
        "FINTRAC High-Risk Countries": "FINTRAC_HIGH_RISK_COUNTRIES",
        "EU High-Risk Third Countries": "EU_HIGH_RISK_THIRD_COUNTRIES",
    }

    current_module = globals()
    for display_name, var_name in _LIST_MAP.items():
        if display_name in data and isinstance(data[display_name], list):
            current_module[var_name] = data[display_name]


_load_overrides()
