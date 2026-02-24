"""
Risk scoring engine for KYC client assessment.

Two-pass design:
- Pass 1 (Stage 1): Preliminary score from client intake data alone
- Pass 2 (Stage 3): Revised score incorporating UBO cascade + synthesis findings

Tiers: 0-15 LOW, 16-35 MEDIUM, 36-60 HIGH, 61+ CRITICAL
"""

from constants import (
    AMPLIFICATION_MULTI_FATF_CONNECTIONS,
    AMPLIFICATION_PEP_HIGH_RISK_JURISDICTION,
    AMPLIFICATION_YOUNG_OFFSHORE_COMPLEX,
    EU_HIGH_RISK_THIRD_COUNTRY_POINTS,
    PEP_EXPIRED_RESIDUAL_POINTS,
    RISK_TIER_HIGH_MAX,
    RISK_TIER_LOW_MAX,
    RISK_TIER_MEDIUM_MAX,
    UBO_RISK_CONTRIBUTION_FACTOR,
    WEALTH_INCOME_RATIO_ELEVATED,
    WEALTH_INCOME_RATIO_VERY_HIGH,
)
from models import (
    BusinessClient,
    IndividualClient,
    RiskAssessment,
    RiskFactor,
    RiskLevel,
)
from utilities.reference_data import (
    EU_HIGH_RISK_THIRD_COUNTRIES,
    FATF_BLACK_LIST,
    FATF_GREY_LIST,
    HIGH_RISK_INDUSTRIES,
    HIGH_RISK_OCCUPATIONS,
    OFAC_SANCTIONED_COUNTRIES,
    OFFSHORE_JURISDICTIONS,
    SOURCE_OF_FUNDS_RISK,
)


def _score_to_risk_level(score: int) -> RiskLevel:
    """Convert numeric score to risk level."""
    if score <= RISK_TIER_LOW_MAX:
        return RiskLevel.LOW
    elif score <= RISK_TIER_MEDIUM_MAX:
        return RiskLevel.MEDIUM
    elif score <= RISK_TIER_HIGH_MAX:
        return RiskLevel.HIGH
    else:
        return RiskLevel.CRITICAL


def calculate_individual_risk_score(
    client: IndividualClient,
    ubo_scores: dict[str, int] | None = None,
) -> RiskAssessment:
    """
    Calculate risk score for an individual client.

    Args:
        client: Individual client data
        ubo_scores: Optional dict of {ubo_name: score} from cascade (Stage 3 only)

    Returns:
        RiskAssessment with total score, level, and contributing factors
    """
    factors = []

    # PEP risk
    if client.pep_self_declaration:
        pep_details = (client.pep_details or "").lower()
        if any(kw in pep_details for kw in ["foreign", "international"]):
            factors.append(RiskFactor(factor="Foreign PEP (self-declared)", points=40, category="pep", source="client_intake"))
        elif any(kw in pep_details for kw in ["head of international", "hio"]):
            factors.append(RiskFactor(factor="Head of International Organization", points=30, category="pep", source="client_intake"))
        else:
            factors.append(RiskFactor(factor="Domestic PEP (self-declared)", points=25, category="pep", source="client_intake"))

    # Citizenship risk
    citizenship = (client.citizenship or "").strip()
    if citizenship in FATF_BLACK_LIST:
        factors.append(RiskFactor(factor=f"Citizenship: {citizenship} (FATF black list)", points=30, category="citizenship", source="client_intake"))
    elif citizenship in FATF_GREY_LIST:
        factors.append(RiskFactor(factor=f"Citizenship: {citizenship} (FATF grey list)", points=15, category="citizenship", source="client_intake"))
    elif citizenship in OFAC_SANCTIONED_COUNTRIES:
        factors.append(RiskFactor(factor=f"Citizenship: {citizenship} (OFAC sanctioned)", points=20, category="citizenship", source="client_intake"))
    elif citizenship in EU_HIGH_RISK_THIRD_COUNTRIES:
        factors.append(RiskFactor(factor=f"Citizenship: {citizenship} (EU high-risk third country)", points=EU_HIGH_RISK_THIRD_COUNTRY_POINTS, category="citizenship", source="client_intake"))

    # Country of birth
    cob = (client.country_of_birth or "").strip()
    if cob and cob != citizenship:
        if cob in FATF_BLACK_LIST:
            factors.append(RiskFactor(factor=f"Country of birth: {cob} (FATF black list)", points=15, category="country_of_birth", source="client_intake"))
        elif cob in FATF_GREY_LIST:
            factors.append(RiskFactor(factor=f"Country of birth: {cob} (FATF grey list)", points=8, category="country_of_birth", source="client_intake"))

    # Occupation risk
    if client.employment and client.employment.occupation:
        occ = client.employment.occupation.lower().replace(" ", "_")
        if occ in HIGH_RISK_OCCUPATIONS or any(hr in occ for hr in HIGH_RISK_OCCUPATIONS):
            factors.append(RiskFactor(factor=f"High-risk occupation: {client.employment.occupation}", points=10, category="occupation", source="client_intake"))

    # Source of funds
    if client.source_of_funds:
        sof_key = client.source_of_funds.lower().replace(" ", "_")
        sof_points = SOURCE_OF_FUNDS_RISK.get(sof_key, 0)
        if sof_points > 0:
            factors.append(RiskFactor(factor=f"Source of funds: {client.source_of_funds}", points=sof_points, category="source_of_funds", source="client_intake"))

    # Wealth/income ratio
    if client.net_worth and client.annual_income and client.annual_income > 0:
        ratio = client.net_worth / client.annual_income
        if ratio > WEALTH_INCOME_RATIO_VERY_HIGH:
            factors.append(RiskFactor(factor=f"Wealth/income ratio: {ratio:.0f}x (very high)", points=15, category="wealth_ratio", source="client_intake"))
        elif ratio > WEALTH_INCOME_RATIO_ELEVATED:
            factors.append(RiskFactor(factor=f"Wealth/income ratio: {ratio:.0f}x (elevated)", points=8, category="wealth_ratio", source="client_intake"))

    # US person
    if client.us_person:
        factors.append(RiskFactor(factor="US person — FATCA reporting required", points=5, category="us_nexus", source="client_intake"))

    # Tax residencies
    non_ca_residencies = [t for t in client.tax_residencies if t.lower() not in ("canada", "ca")]
    if non_ca_residencies:
        for tr in non_ca_residencies:
            if tr in FATF_BLACK_LIST:
                factors.append(RiskFactor(factor=f"Tax residency: {tr} (FATF black list)", points=20, category="tax_residency", source="client_intake"))
            elif tr in FATF_GREY_LIST:
                factors.append(RiskFactor(factor=f"Tax residency: {tr} (FATF grey list)", points=10, category="tax_residency", source="client_intake"))
            elif tr in EU_HIGH_RISK_THIRD_COUNTRIES:
                factors.append(RiskFactor(factor=f"Tax residency: {tr} (EU high-risk third country)", points=EU_HIGH_RISK_THIRD_COUNTRY_POINTS, category="tax_residency", source="client_intake"))
            elif tr in OFFSHORE_JURISDICTIONS:
                factors.append(RiskFactor(factor=f"Tax residency: {tr} (offshore jurisdiction)", points=8, category="tax_residency", source="client_intake"))
            else:
                factors.append(RiskFactor(factor=f"Non-Canadian tax residency: {tr}", points=3, category="tax_residency", source="client_intake"))

    # Third-party determination
    if client.third_party_determination:
        factors.append(RiskFactor(factor="Third-party account determination", points=15, category="third_party", source="client_intake"))

    # Amplification pass
    factors.extend(_apply_amplification(factors))

    total = sum(f.points for f in factors)
    level = _score_to_risk_level(total)

    return RiskAssessment(
        total_score=total,
        risk_level=level,
        risk_factors=factors,
        is_preliminary=ubo_scores is None,
        score_history=[{"stage": "intake", "score": total, "level": level.value}],
    )


def calculate_business_risk_score(
    client: BusinessClient,
    ubo_scores: dict[str, int] | None = None,
) -> RiskAssessment:
    """
    Calculate risk score for a business client.

    When ubo_scores is None (Stage 1): skips UBO risk factor.
    When ubo_scores is provided (Stage 3): adds max(ubo_scores) * UBO_RISK_CONTRIBUTION_FACTOR (0.75).
    """
    factors = []

    # Entity age
    if client.incorporation_date:
        try:
            from datetime import datetime
            inc_date = datetime.strptime(client.incorporation_date, "%Y-%m-%d")
            years = (datetime.now() - inc_date).days / 365.25
            if years < 1:
                factors.append(RiskFactor(factor="Entity age < 1 year (shell company risk)", points=15, category="entity_age", source="client_intake"))
            elif years < 3:
                factors.append(RiskFactor(factor="Entity age < 3 years", points=8, category="entity_age", source="client_intake"))
        except (ValueError, TypeError):
            pass

    # Industry risk
    if client.industry:
        industry_key = client.industry.lower().replace(" ", "_").replace("/", "_")
        if industry_key in HIGH_RISK_INDUSTRIES or any(hr in industry_key for hr in HIGH_RISK_INDUSTRIES):
            factors.append(RiskFactor(factor=f"High-risk industry: {client.industry}", points=15, category="industry", source="client_intake"))

    # Countries of operation
    for country in client.countries_of_operation:
        if country.lower() in ("canada", "ca"):
            continue
        if country in FATF_BLACK_LIST:
            factors.append(RiskFactor(factor=f"Operations in {country} (FATF black list)", points=25, category="jurisdiction", source="client_intake"))
        elif country in FATF_GREY_LIST:
            factors.append(RiskFactor(factor=f"Operations in {country} (FATF grey list)", points=12, category="jurisdiction", source="client_intake"))
        elif country in OFAC_SANCTIONED_COUNTRIES:
            factors.append(RiskFactor(factor=f"Operations in {country} (OFAC sanctioned)", points=15, category="jurisdiction", source="client_intake"))
        elif country in EU_HIGH_RISK_THIRD_COUNTRIES:
            factors.append(RiskFactor(factor=f"Operations in {country} (EU high-risk third country)", points=EU_HIGH_RISK_THIRD_COUNTRY_POINTS, category="jurisdiction", source="client_intake"))
        elif country in OFFSHORE_JURISDICTIONS:
            factors.append(RiskFactor(factor=f"Operations in {country} (offshore jurisdiction)", points=8, category="jurisdiction", source="client_intake"))

    # Transaction volume
    if client.expected_transaction_volume:
        if client.expected_transaction_volume > 10_000_000:
            factors.append(RiskFactor(factor="Transaction volume > $10M", points=10, category="transaction_volume", source="client_intake"))
        elif client.expected_transaction_volume > 1_000_000:
            factors.append(RiskFactor(factor="Transaction volume > $1M", points=5, category="transaction_volume", source="client_intake"))

    # Ownership complexity
    if len(client.beneficial_owners) > 4:
        factors.append(RiskFactor(factor=f"Complex ownership ({len(client.beneficial_owners)} beneficial owners)", points=10, category="ownership_complexity", source="client_intake"))
    elif len(client.beneficial_owners) == 0:
        factors.append(RiskFactor(factor="No beneficial owners declared", points=15, category="ownership_complexity", source="client_intake"))

    # US nexus
    if client.us_nexus:
        factors.append(RiskFactor(factor="US nexus — FATCA/OFAC compliance required", points=10, category="us_nexus", source="client_intake"))

    # Incorporation jurisdiction
    if client.incorporation_jurisdiction:
        if client.incorporation_jurisdiction in OFFSHORE_JURISDICTIONS:
            factors.append(RiskFactor(factor=f"Incorporated in {client.incorporation_jurisdiction} (offshore)", points=12, category="incorporation", source="client_intake"))

    # UBO cascade scores (Pass 2 only)
    if ubo_scores:
        max_ubo_score = max(ubo_scores.values()) if ubo_scores else 0
        if max_ubo_score > 0:
            ubo_contribution = int(max_ubo_score * UBO_RISK_CONTRIBUTION_FACTOR)
            max_ubo_name = max(ubo_scores, key=ubo_scores.get)
            factors.append(RiskFactor(
                factor=f"UBO cascade: {max_ubo_name} (score {max_ubo_score} x {UBO_RISK_CONTRIBUTION_FACTOR})",
                points=ubo_contribution,
                category="ubo_cascade",
                source="synthesis",
            ))

    # Third-party
    if client.third_party_determination:
        factors.append(RiskFactor(factor="Third-party account determination", points=15, category="third_party", source="client_intake"))

    # Amplification pass
    factors.extend(_apply_amplification(factors))

    total = sum(f.points for f in factors)
    level = _score_to_risk_level(total)

    return RiskAssessment(
        total_score=total,
        risk_level=level,
        risk_factors=factors,
        is_preliminary=ubo_scores is None,
        score_history=[{"stage": "intake", "score": total, "level": level.value}],
    )


def _apply_amplification(factors: list[RiskFactor]) -> list[RiskFactor]:
    """Detect compounding risk factor combinations and add amplification bonuses.

    Rules:
    1. Young entity (<1yr) + offshore jurisdiction + complex ownership → bonus
    2. Multiple distinct FATF grey/black list connections (>=2 countries) → bonus
    3. PEP + high-risk jurisdiction (FATF/EU/OFAC) → bonus
    """
    categories = {f.category for f in factors}
    {f.factor.lower() for f in factors}
    amplifications: list[RiskFactor] = []

    # Rule 1: Young entity + offshore + complex ownership
    has_young_entity = any(f.category == "entity_age" and "< 1 year" in f.factor for f in factors)
    has_offshore = any("offshore" in f.factor.lower() for f in factors)
    has_complex_ownership = "ownership_complexity" in categories
    if has_young_entity and has_offshore and has_complex_ownership:
        amplifications.append(RiskFactor(
            factor="Risk amplification: young entity + offshore + complex ownership",
            points=AMPLIFICATION_YOUNG_OFFSHORE_COMPLEX,
            category="amplification",
            source="risk_engine",
        ))

    # Rule 2: Multiple FATF grey/black list connections across different countries
    fatf_countries: set[str] = set()
    for f in factors:
        if "fatf" in f.factor.lower() and ("grey" in f.factor.lower() or "black" in f.factor.lower()):
            # Extract country from factor text (format: "...: Country (FATF ...)")
            parts = f.factor.split(":")
            if len(parts) >= 2:
                country = parts[1].split("(")[0].strip()
                fatf_countries.add(country)
    if len(fatf_countries) >= 2:
        amplifications.append(RiskFactor(
            factor=f"Risk amplification: {len(fatf_countries)} FATF-listed jurisdictions ({', '.join(sorted(fatf_countries))})",
            points=AMPLIFICATION_MULTI_FATF_CONNECTIONS,
            category="amplification",
            source="risk_engine",
        ))

    # Rule 3: PEP + high-risk jurisdiction
    has_pep = "pep" in categories
    has_high_risk_jurisdiction = any(
        f.category in ("citizenship", "jurisdiction", "tax_residency")
        and any(kw in f.factor.lower() for kw in ("fatf", "ofac", "eu high-risk"))
        for f in factors
    )
    if has_pep and has_high_risk_jurisdiction:
        amplifications.append(RiskFactor(
            factor="Risk amplification: PEP with high-risk jurisdiction connection",
            points=AMPLIFICATION_PEP_HIGH_RISK_JURISDICTION,
            category="amplification",
            source="risk_engine",
        ))

    return amplifications


def revise_risk_score(
    preliminary: RiskAssessment,
    ubo_scores: dict[str, int] | None = None,
    synthesis_factors: list[RiskFactor] | None = None,
    pep_edd_expired: bool = False,
) -> RiskAssessment:
    """
    Revise risk score with UBO cascade results and synthesis findings.
    Called by Stage 3 pipeline.

    If *pep_edd_expired* is True, any PEP risk factor is replaced with
    a residual "Former PEP" factor worth PEP_EXPIRED_RESIDUAL_POINTS (5 pts).
    Per PCMLTFA, domestic PEP EDD expires 5 years after leaving office.
    """
    factors = list(preliminary.risk_factors or [])

    # PEP decay: replace full PEP points with residual awareness
    if pep_edd_expired:
        pep_factors = [f for f in factors if f.category == "pep"]
        if pep_factors:  # Only apply decay if PEP factors actually exist
            factors = [f for f in factors if f.category != "pep"]
            factors.append(RiskFactor(
                factor="Former PEP — EDD window expired (residual awareness)",
                points=PEP_EXPIRED_RESIDUAL_POINTS,
                category="pep",
                source="synthesis",
            ))

    # Add UBO cascade contribution (strip any existing UBO factors first to prevent double-counting)
    if ubo_scores:
        factors = [f for f in factors if f.category != "ubo_cascade"]
        max_ubo_score = max(ubo_scores.values()) if ubo_scores else 0
        if max_ubo_score > 0:
            ubo_contribution = int(max_ubo_score * UBO_RISK_CONTRIBUTION_FACTOR)
            max_ubo_name = max(ubo_scores, key=ubo_scores.get)
            factors.append(RiskFactor(
                factor=f"UBO cascade: {max_ubo_name} (score {max_ubo_score} x {UBO_RISK_CONTRIBUTION_FACTOR})",
                points=ubo_contribution,
                category="ubo_cascade",
                source="synthesis",
            ))

    # Add synthesis-discovered factors
    if synthesis_factors:
        factors.extend(synthesis_factors)

    # Re-run amplification with the full revised factor set (strip old amplifications first)
    factors = [f for f in factors if f.category != "amplification"]
    factors.extend(_apply_amplification(factors))

    total = sum(f.points for f in factors)
    level = _score_to_risk_level(total)

    history = list(preliminary.score_history)
    history.append({"stage": "synthesis_revision", "score": total, "level": level.value})

    return RiskAssessment(
        total_score=total,
        risk_level=level,
        risk_factors=factors,
        is_preliminary=False,
        score_history=history,
    )
