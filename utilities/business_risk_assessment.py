"""
Business-Specific Risk Assessment.

Analyzes business-specific risk factors beyond the numeric score,
including ownership structure complexity, operational analysis,
industry risk, and jurisdictional exposure.
Pure deterministic logic, no API calls.
"""

from datetime import UTC, datetime

from constants import (
    TRANSACTION_REVENUE_RATIO_ELEVATED,
    TRANSACTION_REVENUE_RATIO_HIGH,
    UBO_COMPLEX_OWNERSHIP_THRESHOLD,
    UBO_OWNERSHIP_COVERAGE_CONCERN,
)
from models import BusinessClient
from utilities.reference_data import (
    FATF_BLACK_LIST,
    FATF_GREY_LIST,
    HIGH_RISK_INDUSTRIES,
    OFAC_SANCTIONED_COUNTRIES,
    OFFSHORE_JURISDICTIONS,
)


def assess_business_risk_factors(client: BusinessClient) -> dict:
    """
    Assess business-specific risk factors beyond the numeric score.

    Returns dict with:
        risk_factors: list of RiskFactor-compatible dicts
        ownership_analysis: dict — ownership structure assessment
        operational_analysis: dict — operational risk assessment
        transaction_analysis: dict — transaction pattern assessment
        overall_narrative: str — human-readable summary
        evidence: list of EvidenceRecord-compatible dicts

    Analyzes:
    - Entity age and maturity
    - Industry risk (cross-ref against HIGH_RISK_INDUSTRIES)
    - Ownership structure complexity
    - Beneficial ownership transparency
    - Countries of operation (FATF, sanctions, offshore)
    - Transaction volume relative to entity size/age
    - Incorporation jurisdiction
    - Nature of business
    - Client relationship characteristics
    """
    timestamp = datetime.now(UTC).isoformat()
    risk_factors = []
    evidence = []

    # Perform sub-assessments
    ownership = _analyze_ownership(client, risk_factors)
    operational = _analyze_operations(client, risk_factors)
    transaction = _analyze_transactions(client, risk_factors)

    # Build overall narrative
    narrative = _build_narrative(
        client, risk_factors, ownership, operational, transaction
    )

    # Build evidence records
    entity_key = client.legal_name.lower().replace(" ", "_")
    evidence.append({
        "evidence_id": f"biz_risk_{entity_key}",
        "source_type": "utility",
        "source_name": "business_risk_assessment",
        "entity_screened": client.legal_name,
        "entity_context": "business client — risk factor assessment",
        "claim": (
            f"Business risk assessment identified {len(risk_factors)} risk factor(s). "
            f"Ownership risk: {ownership.get('risk_level', 'n/a')}. "
            f"Operational risk: {operational.get('risk_level', 'n/a')}. "
            f"Transaction risk: {transaction.get('risk_level', 'n/a')}."
        ),
        "evidence_level": "S",
        "supporting_data": [
            {"risk_factors_count": len(risk_factors)},
            {"ownership_risk": ownership.get("risk_level", "n/a")},
            {"operational_risk": operational.get("risk_level", "n/a")},
            {"transaction_risk": transaction.get("risk_level", "n/a")},
            {"total_risk_points": sum(f["points"] for f in risk_factors)},
        ],
        "disposition": "PENDING_REVIEW",
        "confidence": "HIGH",
        "timestamp": timestamp,
    })

    # Add specific evidence for high-risk factors
    high_risk_factors = [f for f in risk_factors if f["points"] >= 15]
    if high_risk_factors:
        evidence.append({
            "evidence_id": f"biz_high_risk_{entity_key}",
            "source_type": "utility",
            "source_name": "business_risk_assessment",
            "entity_screened": client.legal_name,
            "entity_context": "business client — elevated risk factors",
            "claim": (
                f"{len(high_risk_factors)} elevated risk factor(s) identified: "
                + "; ".join(f["factor"] for f in high_risk_factors)
            ),
            "evidence_level": "S",
            "supporting_data": [
                {"factor": f["factor"], "points": f["points"], "category": f["category"]}
                for f in high_risk_factors
            ],
            "disposition": "PENDING_REVIEW",
            "confidence": "HIGH",
            "timestamp": timestamp,
        })

    return {
        "risk_factors": risk_factors,
        "ownership_analysis": ownership,
        "operational_analysis": operational,
        "transaction_analysis": transaction,
        "overall_narrative": narrative,
        "evidence": evidence,
    }


def _analyze_ownership(client: BusinessClient, risk_factors: list) -> dict:
    """Analyze ownership structure complexity and transparency."""
    analysis = {
        "risk_level": "low",
        "total_beneficial_owners": len(client.beneficial_owners),
        "ownership_coverage": 0.0,
        "concerns": [],
        "findings": [],
    }

    # Ownership coverage — what percentage is accounted for?
    total_ownership = sum(
        ubo.ownership_percentage for ubo in client.beneficial_owners
    )
    analysis["ownership_coverage"] = round(total_ownership, 2)

    # No beneficial owners declared
    if not client.beneficial_owners:
        analysis["risk_level"] = "high"
        analysis["concerns"].append(
            "No beneficial owners declared — ownership structure opaque"
        )
        risk_factors.append({
            "factor": "No beneficial owners declared",
            "points": 15,
            "category": "ownership_transparency",
            "source": "business_risk_assessment",
        })
    else:
        # Ownership gap
        if total_ownership < UBO_OWNERSHIP_COVERAGE_CONCERN:
            analysis["risk_level"] = "high"
            analysis["concerns"].append(
                f"Only {total_ownership:.0f}% of ownership identified — "
                f"{100 - total_ownership:.0f}% unaccounted for"
            )
            risk_factors.append({
                "factor": f"Ownership gap: {100 - total_ownership:.0f}% unidentified",
                "points": 12,
                "category": "ownership_transparency",
                "source": "business_risk_assessment",
            })
        elif total_ownership < 100:
            analysis["findings"].append(
                f"{total_ownership:.0f}% of ownership identified — "
                f"{100 - total_ownership:.0f}% held by minor shareholders"
            )

        # Complex ownership (many UBOs)
        num_ubos = len(client.beneficial_owners)
        if num_ubos > UBO_COMPLEX_OWNERSHIP_THRESHOLD:
            analysis["risk_level"] = "high"
            analysis["concerns"].append(
                f"Complex ownership: {num_ubos} beneficial owners"
            )
            risk_factors.append({
                "factor": f"Complex ownership structure ({num_ubos} beneficial owners)",
                "points": 10,
                "category": "ownership_complexity",
                "source": "business_risk_assessment",
            })
        elif num_ubos > 3:
            if analysis["risk_level"] == "low":
                analysis["risk_level"] = "medium"
            analysis["findings"].append(
                f"Moderately complex ownership: {num_ubos} beneficial owners"
            )

        # Multi-jurisdictional UBOs
        ubo_countries = set()
        for ubo in client.beneficial_owners:
            if ubo.citizenship:
                ubo_countries.add(ubo.citizenship)
            if ubo.country_of_residence:
                ubo_countries.add(ubo.country_of_residence)

        non_ca_countries = {
            c for c in ubo_countries if c.lower() not in ("canada", "ca")
        }
        if len(non_ca_countries) > 3:
            analysis["risk_level"] = "high"
            analysis["concerns"].append(
                f"Beneficial owners span {len(non_ca_countries)} non-Canadian jurisdictions"
            )
            risk_factors.append({
                "factor": (
                    f"Multi-jurisdictional ownership: UBOs in "
                    f"{', '.join(sorted(non_ca_countries))}"
                ),
                "points": 10,
                "category": "ownership_complexity",
                "source": "business_risk_assessment",
            })
        analysis["ubo_jurisdictions"] = sorted(ubo_countries)

        # PEP beneficial owners
        pep_ubos = [ubo for ubo in client.beneficial_owners if ubo.pep_self_declaration]
        if pep_ubos:
            analysis["risk_level"] = "high"
            for ubo in pep_ubos:
                analysis["concerns"].append(
                    f"PEP beneficial owner: {ubo.full_name} "
                    f"({ubo.ownership_percentage}%)"
                )
            risk_factors.append({
                "factor": f"PEP beneficial owner(s): {len(pep_ubos)}",
                "points": 20,
                "category": "pep",
                "source": "business_risk_assessment",
            })

        # High-risk jurisdiction UBOs
        for ubo in client.beneficial_owners:
            countries = []
            if ubo.citizenship:
                countries.append(ubo.citizenship)
            if ubo.country_of_residence:
                countries.append(ubo.country_of_residence)

            for country in countries:
                if country in FATF_BLACK_LIST:
                    analysis["risk_level"] = "high"
                    analysis["concerns"].append(
                        f"UBO {ubo.full_name} linked to FATF black list country: {country}"
                    )
                    risk_factors.append({
                        "factor": f"UBO {ubo.full_name} — FATF black list: {country}",
                        "points": 20,
                        "category": "ubo_jurisdiction",
                        "source": "business_risk_assessment",
                    })
                elif country in FATF_GREY_LIST:
                    if analysis["risk_level"] == "low":
                        analysis["risk_level"] = "medium"
                    analysis["concerns"].append(
                        f"UBO {ubo.full_name} linked to FATF grey list country: {country}"
                    )
                    risk_factors.append({
                        "factor": f"UBO {ubo.full_name} — FATF grey list: {country}",
                        "points": 10,
                        "category": "ubo_jurisdiction",
                        "source": "business_risk_assessment",
                    })

    return analysis


def _analyze_operations(client: BusinessClient, risk_factors: list) -> dict:
    """Analyze operational risk factors."""
    analysis = {
        "risk_level": "low",
        "concerns": [],
        "findings": [],
    }

    # Entity age
    entity_age_years = None
    if client.incorporation_date:
        try:
            inc_date = datetime.strptime(client.incorporation_date, "%Y-%m-%d")
            entity_age_years = (datetime.now() - inc_date).days / 365.25
            analysis["entity_age_years"] = round(entity_age_years, 1)

            if entity_age_years < 1:
                analysis["risk_level"] = "high"
                analysis["concerns"].append(
                    f"Very new entity ({entity_age_years:.1f} years) — "
                    "shell company risk"
                )
                risk_factors.append({
                    "factor": f"Entity age < 1 year ({entity_age_years:.1f} years)",
                    "points": 15,
                    "category": "entity_age",
                    "source": "business_risk_assessment",
                })
            elif entity_age_years < 2:
                if analysis["risk_level"] == "low":
                    analysis["risk_level"] = "medium"
                analysis["concerns"].append(
                    f"New entity ({entity_age_years:.1f} years) — limited track record"
                )
                risk_factors.append({
                    "factor": f"Entity age < 2 years ({entity_age_years:.1f} years)",
                    "points": 8,
                    "category": "entity_age",
                    "source": "business_risk_assessment",
                })
            elif entity_age_years < 5:
                analysis["findings"].append(
                    f"Entity age: {entity_age_years:.1f} years — relatively young"
                )
        except (ValueError, TypeError):
            analysis["findings"].append(
                "Incorporation date format not parseable"
            )
    else:
        analysis["findings"].append("Incorporation date not provided")

    # Industry risk
    if client.industry:
        industry_key = client.industry.lower().replace(" ", "_").replace("/", "_")
        matched = False
        for hr_industry in HIGH_RISK_INDUSTRIES:
            if hr_industry in industry_key or industry_key in hr_industry:
                matched = True
                break
        if matched:
            analysis["risk_level"] = "high"
            analysis["concerns"].append(
                f"High-risk industry: {client.industry}"
            )
            risk_factors.append({
                "factor": f"High-risk industry: {client.industry}",
                "points": 15,
                "category": "industry",
                "source": "business_risk_assessment",
            })
        else:
            analysis["findings"].append(f"Industry: {client.industry} (not high-risk)")
    else:
        analysis["findings"].append("Industry not specified")

    # Nature of business keywords
    if client.nature_of_business:
        nature_lower = client.nature_of_business.lower()
        high_risk_keywords = {
            "import_export": ["import", "export", "trade", "shipping"],
            "cash_intensive": ["cash", "atm", "money transfer", "remittance", "currency exchange"],
            "virtual_assets": ["crypto", "bitcoin", "virtual currency", "digital asset", "blockchain"],
            "gambling": ["casino", "gambling", "gaming", "lottery", "betting"],
            "precious_materials": ["gold", "diamond", "precious metal", "gemstone", "jewel"],
        }

        for category, keywords in high_risk_keywords.items():
            for kw in keywords:
                if kw in nature_lower:
                    if analysis["risk_level"] == "low":
                        analysis["risk_level"] = "medium"
                    analysis["concerns"].append(
                        f"Nature of business includes high-risk keyword: '{kw}' "
                        f"(category: {category})"
                    )
                    risk_factors.append({
                        "factor": (
                            f"Nature of business — {category}: "
                            f"'{client.nature_of_business}'"
                        ),
                        "points": 10,
                        "category": "nature_of_business",
                        "source": "business_risk_assessment",
                    })
                    break  # Only one factor per category

    # Incorporation jurisdiction
    if client.incorporation_jurisdiction:
        jurisdiction = client.incorporation_jurisdiction
        if jurisdiction in OFFSHORE_JURISDICTIONS:
            analysis["risk_level"] = "high"
            analysis["concerns"].append(
                f"Incorporated in offshore jurisdiction: {jurisdiction}"
            )
            risk_factors.append({
                "factor": f"Offshore incorporation: {jurisdiction}",
                "points": 12,
                "category": "incorporation_jurisdiction",
                "source": "business_risk_assessment",
            })
        elif jurisdiction in FATF_BLACK_LIST:
            analysis["risk_level"] = "high"
            analysis["concerns"].append(
                f"Incorporated in FATF black list country: {jurisdiction}"
            )
            risk_factors.append({
                "factor": f"FATF black list incorporation: {jurisdiction}",
                "points": 25,
                "category": "incorporation_jurisdiction",
                "source": "business_risk_assessment",
            })
        elif jurisdiction in FATF_GREY_LIST:
            if analysis["risk_level"] == "low":
                analysis["risk_level"] = "medium"
            analysis["concerns"].append(
                f"Incorporated in FATF grey list country: {jurisdiction}"
            )
            risk_factors.append({
                "factor": f"FATF grey list incorporation: {jurisdiction}",
                "points": 12,
                "category": "incorporation_jurisdiction",
                "source": "business_risk_assessment",
            })

    # Countries of operation
    high_risk_ops = []
    for country in client.countries_of_operation:
        if country.lower() in ("canada", "ca"):
            continue
        if country in FATF_BLACK_LIST:
            high_risk_ops.append((country, "FATF black list", 25))
        elif country in OFAC_SANCTIONED_COUNTRIES:
            high_risk_ops.append((country, "OFAC sanctioned", 15))
        elif country in FATF_GREY_LIST:
            high_risk_ops.append((country, "FATF grey list", 10))
        elif country in OFFSHORE_JURISDICTIONS:
            high_risk_ops.append((country, "offshore jurisdiction", 8))

    for country, label, points in high_risk_ops:
        _RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        if points >= 15:
            analysis["risk_level"] = "high"
        elif _RISK_ORDER.get(analysis["risk_level"], 0) < _RISK_ORDER["medium"]:
            analysis["risk_level"] = "medium"
        analysis["concerns"].append(
            f"Operations in {label} country: {country}"
        )
        risk_factors.append({
            "factor": f"Operations in {country} ({label})",
            "points": points,
            "category": "operational_jurisdiction",
            "source": "business_risk_assessment",
        })

    analysis["countries_of_operation"] = list(client.countries_of_operation)
    analysis["high_risk_operations"] = [
        {"country": c, "designation": l} for c, l, _ in high_risk_ops
    ]

    return analysis


def _analyze_transactions(client: BusinessClient, risk_factors: list) -> dict:
    """Analyze transaction patterns relative to entity profile."""
    analysis = {
        "risk_level": "low",
        "concerns": [],
        "findings": [],
    }

    # Transaction volume vs revenue
    if client.expected_transaction_volume and client.annual_revenue:
        if client.annual_revenue > 0:
            ratio = client.expected_transaction_volume / client.annual_revenue
            analysis["volume_revenue_ratio"] = round(ratio, 2)

            if ratio > TRANSACTION_REVENUE_RATIO_HIGH:
                analysis["risk_level"] = "high"
                analysis["concerns"].append(
                    f"Transaction volume (${client.expected_transaction_volume:,.0f}) "
                    f"is {ratio:.0f}x annual revenue (${client.annual_revenue:,.0f}) — "
                    "significantly disproportionate"
                )
                risk_factors.append({
                    "factor": (
                        f"Transaction volume {ratio:.0f}x revenue "
                        f"(${client.expected_transaction_volume:,.0f} vs "
                        f"${client.annual_revenue:,.0f})"
                    ),
                    "points": 15,
                    "category": "transaction_anomaly",
                    "source": "business_risk_assessment",
                })
            elif ratio > TRANSACTION_REVENUE_RATIO_ELEVATED:
                if analysis["risk_level"] == "low":
                    analysis["risk_level"] = "medium"
                analysis["concerns"].append(
                    f"Transaction volume is {ratio:.1f}x revenue — elevated"
                )
                risk_factors.append({
                    "factor": f"Elevated transaction volume ({ratio:.1f}x revenue)",
                    "points": 8,
                    "category": "transaction_anomaly",
                    "source": "business_risk_assessment",
                })
            else:
                analysis["findings"].append(
                    f"Transaction volume is {ratio:.1f}x revenue — within normal range"
                )

    # Absolute transaction volume
    if client.expected_transaction_volume:
        analysis["expected_volume"] = client.expected_transaction_volume
        if client.expected_transaction_volume > 50_000_000:
            if analysis["risk_level"] != "high":
                analysis["risk_level"] = "medium"
            analysis["findings"].append(
                f"High absolute transaction volume: "
                f"${client.expected_transaction_volume:,.0f}"
            )
            risk_factors.append({
                "factor": (
                    f"High transaction volume: "
                    f"${client.expected_transaction_volume:,.0f}"
                ),
                "points": 10,
                "category": "transaction_volume",
                "source": "business_risk_assessment",
            })
        elif client.expected_transaction_volume > 10_000_000:
            analysis["findings"].append(
                f"Significant transaction volume: "
                f"${client.expected_transaction_volume:,.0f}"
            )

    # Transaction frequency
    if client.expected_transaction_frequency:
        freq = client.expected_transaction_frequency.lower()
        if "daily" in freq or "multiple" in freq:
            analysis["findings"].append(
                f"High-frequency trading expected: {client.expected_transaction_frequency}"
            )
            if client.annual_revenue and client.annual_revenue < 1_000_000:
                analysis["concerns"].append(
                    "High-frequency transactions for relatively small entity"
                )
                risk_factors.append({
                    "factor": "High-frequency transactions for small entity",
                    "points": 8,
                    "category": "transaction_frequency",
                    "source": "business_risk_assessment",
                })

    # Transaction volume vs entity age
    if (
        client.expected_transaction_volume
        and client.incorporation_date
        and client.expected_transaction_volume > 5_000_000
    ):
        try:
            inc_date = datetime.strptime(client.incorporation_date, "%Y-%m-%d")
            age_years = (datetime.now() - inc_date).days / 365.25
            if age_years < 2:
                analysis["risk_level"] = "high"
                analysis["concerns"].append(
                    f"High transaction volume "
                    f"(${client.expected_transaction_volume:,.0f}) "
                    f"for entity less than {age_years:.1f} years old"
                )
                risk_factors.append({
                    "factor": (
                        f"High volume for young entity: "
                        f"${client.expected_transaction_volume:,.0f} at "
                        f"{age_years:.1f} years old"
                    ),
                    "points": 12,
                    "category": "transaction_entity_age",
                    "source": "business_risk_assessment",
                })
        except (ValueError, TypeError):
            pass

    # Initial deposit analysis
    for acct in client.account_requests:
        if acct.initial_deposit and acct.initial_deposit >= 1_000_000:
            analysis["findings"].append(
                f"Large initial deposit: ${acct.initial_deposit:,.0f} "
                f"for '{acct.account_type}'"
            )
            if client.annual_revenue and client.annual_revenue > 0:
                dep_ratio = acct.initial_deposit / client.annual_revenue
                if dep_ratio > 2:
                    analysis["concerns"].append(
                        f"Initial deposit (${acct.initial_deposit:,.0f}) exceeds "
                        f"{dep_ratio:.1f}x annual revenue"
                    )

    return analysis


def _build_narrative(
    client: BusinessClient,
    risk_factors: list,
    ownership: dict,
    operational: dict,
    transaction: dict,
) -> str:
    """Build a human-readable narrative summarizing the assessment."""
    parts = []

    # Opening
    parts.append(
        f"{client.legal_name} is a "
        f"{client.business_type or 'business entity'}"
        f"{' operating as ' + client.operating_name if client.operating_name and client.operating_name != client.legal_name else ''}"
        f"{' in the ' + client.industry + ' industry' if client.industry else ''}"
        f"."
    )

    # Entity age
    if "entity_age_years" in operational:
        age = operational["entity_age_years"]
        if age < 2:
            parts.append(
                f"The entity is relatively new at {age:.1f} years old, "
                "which increases risk due to limited operating history."
            )
        else:
            parts.append(
                f"The entity has been operating for {age:.1f} years."
            )

    # Ownership
    num_ubos = ownership["total_beneficial_owners"]
    coverage = ownership["ownership_coverage"]
    if num_ubos == 0:
        parts.append(
            "No beneficial owners have been declared, which represents "
            "a significant transparency gap."
        )
    elif coverage < 100:
        parts.append(
            f"{num_ubos} beneficial owner(s) identified covering "
            f"{coverage:.0f}% of ownership."
        )
    else:
        parts.append(
            f"Ownership structure includes {num_ubos} identified "
            f"beneficial owner(s) covering {coverage:.0f}% of the entity."
        )

    # Risk factors summary
    total_points = sum(f["points"] for f in risk_factors)
    if total_points > 0:
        categories = set(f["category"] for f in risk_factors)
        parts.append(
            f"The assessment identified {len(risk_factors)} risk factor(s) "
            f"totaling {total_points} points across categories: "
            f"{', '.join(sorted(categories))}."
        )

    # Key concerns
    all_concerns = (
        ownership.get("concerns", [])
        + operational.get("concerns", [])
        + transaction.get("concerns", [])
    )
    if all_concerns:
        parts.append(
            f"Key concerns: {'; '.join(all_concerns[:5])}"
            + ("." if not all_concerns[0].endswith(".") else "")
        )
    else:
        parts.append("No significant concerns were identified in this assessment.")

    return " ".join(parts)
