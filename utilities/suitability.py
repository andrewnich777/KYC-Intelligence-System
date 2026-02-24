"""
CIRO Rule 3202 Suitability Assessment.

Evaluates client suitability for requested account types based on
income, net worth, risk tolerance, knowledge, and investment objectives.
Pure deterministic logic, no API calls.
"""

from datetime import UTC, datetime

from constants import (
    SUITABILITY_DEPOSIT_INCOME_RATIO_ELEVATED,
    SUITABILITY_DEPOSIT_INCOME_RATIO_HIGH,
    SUITABILITY_HIGH_INCOME_THRESHOLD,
    SUITABILITY_LEVERAGE_NET_WORTH_MIN,
    SUITABILITY_LOW_INCOME_THRESHOLD,
    SUITABILITY_LOW_NET_WORTH_THRESHOLD,
    WEALTH_INCOME_RATIO_ELEVATED,
    WEALTH_INCOME_RATIO_VERY_HIGH,
)
from models import BusinessClient, IndividualClient


def assess_suitability(client) -> dict:
    """
    Evaluate client suitability per CIRO Rule 3202.

    Returns dict with:
        suitable: bool — overall suitability determination
        concerns: list of str — identified issues
        recommendations: list of str — suggested actions
        details: dict of sub-assessments (income, risk_tolerance, objectives, etc.)
        evidence: list of EvidenceRecord-compatible dicts

    Checks:
    - Income/net worth consistency
    - Risk tolerance vs knowledge alignment
    - Investment objectives vs time horizon consistency
    - Source of funds consistency with employment
    - Account type appropriateness
    """
    if isinstance(client, IndividualClient):
        return _assess_individual_suitability(client)
    elif isinstance(client, BusinessClient):
        return _assess_business_suitability(client)
    else:
        return {
            "suitable": False,
            "concerns": ["Unable to determine client type"],
            "recommendations": [],
            "details": {},
            "evidence": [],
        }


def _assess_individual_suitability(client: IndividualClient) -> dict:
    """Assess suitability for an individual client."""
    concerns = []
    recommendations = []
    details = {}
    evidence = []
    timestamp = datetime.now(UTC).isoformat()

    # -------------------------------------------------------------------------
    # 1. Income / net worth consistency
    # -------------------------------------------------------------------------
    income_assessment = {"status": "pass", "notes": []}

    if client.employment:
        status = client.employment.status.lower() if client.employment.status else ""
        if status in ("employed", "self_employed"):
            if client.annual_income is not None and client.annual_income <= 0:
                income_assessment["status"] = "concern"
                income_assessment["notes"].append(
                    "Client reports employed/self-employed status but zero or negative income"
                )
                concerns.append(
                    "Income inconsistency: employment status is "
                    f"'{client.employment.status}' but annual income is "
                    f"${client.annual_income:,.0f}"
                )
        elif status in ("retired", "student", "unemployed"):
            if client.annual_income and client.annual_income > SUITABILITY_HIGH_INCOME_THRESHOLD:
                income_assessment["status"] = "flag"
                income_assessment["notes"].append(
                    f"High income (${client.annual_income:,.0f}) reported "
                    f"with '{status}' employment status — verify source"
                )
                concerns.append(
                    f"Income/employment mismatch: ${client.annual_income:,.0f} "
                    f"income with '{status}' status"
                )
                recommendations.append(
                    "Request documentation supporting income source "
                    f"given '{status}' employment status"
                )
    else:
        income_assessment["status"] = "incomplete"
        income_assessment["notes"].append("Employment information not provided")
        recommendations.append("Obtain employment information for suitability assessment")

    # Net worth relative to income
    if client.net_worth is not None and client.annual_income is not None and client.annual_income > 0:
        ratio = client.net_worth / client.annual_income
        income_assessment["wealth_income_ratio"] = round(ratio, 1)
        if ratio > WEALTH_INCOME_RATIO_VERY_HIGH:
            income_assessment["notes"].append(
                f"Net worth is {ratio:.0f}x annual income — unusually high, "
                "verify source of wealth"
            )
            concerns.append(
                f"Wealth/income ratio of {ratio:.0f}x is unusually high"
            )
            recommendations.append("Request detailed source of wealth documentation")
        elif ratio > WEALTH_INCOME_RATIO_ELEVATED:
            income_assessment["notes"].append(
                f"Net worth is {ratio:.0f}x annual income — elevated ratio"
            )
    elif client.net_worth is None:
        income_assessment["notes"].append("Net worth not provided")
        recommendations.append("Obtain net worth estimate for suitability assessment")

    details["income_assessment"] = income_assessment

    # -------------------------------------------------------------------------
    # 2. Risk tolerance vs knowledge alignment
    # -------------------------------------------------------------------------
    risk_assessment = {"status": "pass", "notes": []}

    for acct in client.account_requests:
        risk_tol = (acct.risk_tolerance or "").lower()
        objectives = (acct.investment_objectives or "").lower()

        if risk_tol in ("high", "aggressive", "speculative"):
            # Check if client profile supports high-risk tolerance
            if client.annual_income is not None and client.annual_income < SUITABILITY_LOW_INCOME_THRESHOLD:
                risk_assessment["status"] = "concern"
                risk_assessment["notes"].append(
                    f"High risk tolerance for '{acct.account_type}' "
                    f"with income of ${client.annual_income:,.0f}"
                )
                concerns.append(
                    f"Risk tolerance mismatch: high/aggressive tolerance "
                    f"with relatively low income (${client.annual_income:,.0f})"
                )
            if client.net_worth is not None and client.net_worth < SUITABILITY_LOW_NET_WORTH_THRESHOLD:
                risk_assessment["status"] = "concern"
                risk_assessment["notes"].append(
                    f"High risk tolerance with limited net worth "
                    f"(${client.net_worth:,.0f})"
                )
                concerns.append(
                    f"Risk tolerance mismatch: high/aggressive tolerance "
                    f"with limited net worth (${client.net_worth:,.0f})"
                )

        if risk_tol in ("low", "conservative") and "growth" in objectives:
            risk_assessment["status"] = "flag"
            risk_assessment["notes"].append(
                f"Conservative risk tolerance conflicts with growth objectives "
                f"for '{acct.account_type}'"
            )
            concerns.append(
                "Risk/objective conflict: conservative risk tolerance "
                "with growth-oriented investment objectives"
            )
            recommendations.append(
                "Discuss risk tolerance vs growth objectives with client to ensure alignment"
            )

        if risk_tol in ("high", "aggressive", "speculative") and (
            "income" in objectives or "preservation" in objectives or "safety" in objectives
        ):
            risk_assessment["status"] = "flag"
            risk_assessment["notes"].append(
                f"Aggressive risk tolerance conflicts with income/preservation objectives "
                f"for '{acct.account_type}'"
            )
            concerns.append(
                "Risk/objective conflict: aggressive risk tolerance "
                "with income or preservation objectives"
            )

    if not client.account_requests:
        risk_assessment["status"] = "incomplete"
        risk_assessment["notes"].append("No account requests to assess")

    details["risk_tolerance_assessment"] = risk_assessment

    # -------------------------------------------------------------------------
    # 3. Investment objectives vs time horizon consistency
    # -------------------------------------------------------------------------
    horizon_assessment = {"status": "pass", "notes": []}

    for acct in client.account_requests:
        objectives = (acct.investment_objectives or "").lower()
        horizon = (acct.time_horizon or "").lower()

        if ("growth" in objectives or "aggressive" in objectives) and (
            "short" in horizon or horizon in ("< 1 year", "1 year", "less than 1 year")
        ):
            horizon_assessment["status"] = "concern"
            horizon_assessment["notes"].append(
                f"Growth/aggressive objectives with short time horizon "
                f"for '{acct.account_type}'"
            )
            concerns.append(
                "Objective/horizon mismatch: growth objectives with short-term horizon"
            )
            recommendations.append(
                "Clarify time horizon or adjust investment objectives to match"
            )

        if ("preservation" in objectives or "income" in objectives) and (
            "long" in horizon or "10" in horizon or "20" in horizon
        ):
            horizon_assessment["status"] = "flag"
            horizon_assessment["notes"].append(
                f"Preservation/income objectives with long time horizon "
                f"for '{acct.account_type}' — may miss growth opportunity"
            )
            recommendations.append(
                "Discuss whether preservation-only approach is appropriate "
                "for long-term horizon"
            )

    details["horizon_assessment"] = horizon_assessment

    # -------------------------------------------------------------------------
    # 4. Source of funds consistency with employment
    # -------------------------------------------------------------------------
    sof_assessment = {"status": "pass", "notes": []}

    if client.source_of_funds:
        sof = client.source_of_funds.lower()
        emp_status = ""
        if client.employment:
            emp_status = (client.employment.status or "").lower()

        if ("employment" in sof or "salary" in sof) and emp_status in (
            "retired", "student", "unemployed"
        ):
            sof_assessment["status"] = "concern"
            sof_assessment["notes"].append(
                f"Source of funds is '{client.source_of_funds}' but "
                f"employment status is '{emp_status}'"
            )
            concerns.append(
                f"Source of funds inconsistency: reports '{client.source_of_funds}' "
                f"but employment status is '{emp_status}'"
            )
            recommendations.append(
                "Verify source of funds documentation against employment status"
            )

        if "inheritance" in sof or "gift" in sof:
            sof_assessment["notes"].append(
                f"Source of funds is '{client.source_of_funds}' — "
                "may require supporting documentation"
            )
            recommendations.append(
                f"Request documentation supporting '{client.source_of_funds}' "
                "(e.g., estate documents, gift letter)"
            )

        if "lottery" in sof or "gambling" in sof or "cryptocurrency" in sof:
            sof_assessment["status"] = "flag"
            sof_assessment["notes"].append(
                f"Higher-risk source of funds: '{client.source_of_funds}'"
            )
            concerns.append(
                f"Higher-risk source of funds: {client.source_of_funds}"
            )
            recommendations.append(
                f"Obtain detailed documentation for '{client.source_of_funds}' "
                "source of funds"
            )
    else:
        sof_assessment["status"] = "incomplete"
        sof_assessment["notes"].append("Source of funds not provided")
        recommendations.append("Obtain source of funds information")

    details["source_of_funds_assessment"] = sof_assessment

    # -------------------------------------------------------------------------
    # 5. Account type appropriateness
    # -------------------------------------------------------------------------
    account_assessment = {"status": "pass", "notes": []}

    for acct in client.account_requests:
        acct_type = (acct.account_type or "").lower()

        # Large initial deposits relative to income
        if acct.initial_deposit and client.annual_income and client.annual_income > 0:
            deposit_ratio = acct.initial_deposit / client.annual_income
            if deposit_ratio > SUITABILITY_DEPOSIT_INCOME_RATIO_HIGH:
                account_assessment["status"] = "concern"
                account_assessment["notes"].append(
                    f"Initial deposit (${acct.initial_deposit:,.0f}) is "
                    f"{deposit_ratio:.1f}x annual income for '{acct.account_type}'"
                )
                concerns.append(
                    f"Large initial deposit relative to income: "
                    f"${acct.initial_deposit:,.0f} vs ${client.annual_income:,.0f} income"
                )
                recommendations.append(
                    "Verify source of initial deposit funds"
                )
            elif deposit_ratio > SUITABILITY_DEPOSIT_INCOME_RATIO_ELEVATED:
                account_assessment["notes"].append(
                    f"Initial deposit is {deposit_ratio:.1f}x annual income — "
                    "elevated but may be reasonable"
                )

        # Margin / leverage accounts
        if any(
            kw in acct_type
            for kw in ("margin", "leverage", "options", "futures", "derivatives")
        ):
            if client.net_worth is not None and client.net_worth < SUITABILITY_LEVERAGE_NET_WORTH_MIN:
                account_assessment["status"] = "concern"
                account_assessment["notes"].append(
                    f"Leveraged/derivative account type '{acct.account_type}' "
                    f"with limited net worth (${client.net_worth:,.0f})"
                )
                concerns.append(
                    f"Leverage/derivative account may be unsuitable "
                    f"for client with net worth of ${client.net_worth:,.0f}"
                )
                recommendations.append(
                    "Assess client knowledge and experience with leveraged products"
                )

    details["account_type_assessment"] = account_assessment

    # -------------------------------------------------------------------------
    # Overall determination
    # -------------------------------------------------------------------------
    has_concerns = any(
        d.get("status") == "concern"
        for d in details.values()
        if isinstance(d, dict)
    )
    has_flags = any(
        d.get("status") == "flag"
        for d in details.values()
        if isinstance(d, dict)
    )
    has_incomplete = any(
        d.get("status") == "incomplete"
        for d in details.values()
        if isinstance(d, dict)
    )

    if has_concerns:
        suitable = False
        recommendations.insert(0, "Resolve identified concerns before proceeding with onboarding")
    elif has_flags or has_incomplete:
        suitable = True  # Provisionally suitable, but needs attention
        recommendations.insert(0, "Address flagged items and complete missing information")
    else:
        suitable = True

    # Build evidence records
    entity_key = client.full_name.lower().replace(" ", "_")
    evidence.append({
        "evidence_id": f"suit_{entity_key}",
        "source_type": "utility",
        "source_name": "suitability",
        "entity_screened": client.full_name,
        "entity_context": "individual client",
        "claim": (
            f"Suitability assessment: {'suitable' if suitable else 'concerns identified'}. "
            f"{len(concerns)} concerns, {len(recommendations)} recommendations."
        ),
        "evidence_level": "S",
        "supporting_data": [
            {"concerns_count": len(concerns)},
            {"recommendations_count": len(recommendations)},
            {"sub_assessments": {k: v.get("status", "n/a") for k, v in details.items() if isinstance(v, dict)}},
        ],
        "disposition": "CLEAR" if suitable and not has_flags else "PENDING_REVIEW",
        "confidence": "HIGH" if not has_incomplete else "MEDIUM",
        "timestamp": timestamp,
    })

    return {
        "suitable": suitable,
        "concerns": concerns,
        "recommendations": recommendations,
        "details": details,
        "evidence": evidence,
    }


def _assess_business_suitability(client: BusinessClient) -> dict:
    """
    Assess suitability for a business client.

    Business suitability focuses on account type appropriateness
    relative to business nature, size, and expected activity.
    """
    concerns = []
    recommendations = []
    details = {}
    evidence = []
    timestamp = datetime.now(UTC).isoformat()

    # -------------------------------------------------------------------------
    # 1. Revenue / transaction volume consistency
    # -------------------------------------------------------------------------
    revenue_assessment = {"status": "pass", "notes": []}

    if client.annual_revenue and client.expected_transaction_volume:
        ratio = client.expected_transaction_volume / client.annual_revenue
        revenue_assessment["volume_revenue_ratio"] = round(ratio, 2)
        if ratio > 5:
            revenue_assessment["status"] = "concern"
            revenue_assessment["notes"].append(
                f"Expected transaction volume (${client.expected_transaction_volume:,.0f}) "
                f"is {ratio:.1f}x annual revenue (${client.annual_revenue:,.0f})"
            )
            concerns.append(
                "Transaction volume significantly exceeds annual revenue — "
                "possible pass-through or flow-through activity"
            )
            recommendations.append(
                "Obtain explanation for transaction volume relative to revenue"
            )
        elif ratio > 2:
            revenue_assessment["notes"].append(
                f"Transaction volume is {ratio:.1f}x revenue — elevated but "
                "may be normal for trading/import-export businesses"
            )
    elif client.annual_revenue is None:
        revenue_assessment["status"] = "incomplete"
        revenue_assessment["notes"].append("Annual revenue not provided")
        recommendations.append("Obtain annual revenue estimate for suitability assessment")

    details["revenue_assessment"] = revenue_assessment

    # -------------------------------------------------------------------------
    # 2. Nature of business vs account type
    # -------------------------------------------------------------------------
    business_assessment = {"status": "pass", "notes": []}

    for acct in client.account_requests:
        acct_type = (acct.account_type or "").lower()

        if any(
            kw in acct_type
            for kw in ("personal", "rrsp", "tfsa", "resp")
        ):
            business_assessment["status"] = "concern"
            business_assessment["notes"].append(
                f"Registered/personal account type '{acct.account_type}' "
                "requested by business entity"
            )
            concerns.append(
                f"Account type '{acct.account_type}' is not appropriate "
                "for business entities"
            )

        if any(kw in acct_type for kw in ("margin", "leverage", "derivatives")):
            if client.annual_revenue and client.annual_revenue < 500_000:
                business_assessment["status"] = "flag"
                business_assessment["notes"].append(
                    f"Leveraged account for small business "
                    f"(revenue: ${client.annual_revenue:,.0f})"
                )
                recommendations.append(
                    "Verify business has appropriate expertise and resources "
                    "for leveraged products"
                )

    details["business_account_assessment"] = business_assessment

    # -------------------------------------------------------------------------
    # 3. Source of funds consistency
    # -------------------------------------------------------------------------
    sof_assessment = {"status": "pass", "notes": []}

    if client.source_of_funds:
        sof = client.source_of_funds.lower()
        (client.nature_of_business or "").lower()

        if "personal" in sof or "salary" in sof:
            sof_assessment["status"] = "flag"
            sof_assessment["notes"].append(
                "Personal funds declared as source for business account"
            )
            concerns.append(
                "Source of funds appears personal rather than business-derived"
            )
            recommendations.append(
                "Clarify whether business account will be funded from "
                "business operations or personal funds"
            )
    else:
        sof_assessment["status"] = "incomplete"
        sof_assessment["notes"].append("Source of funds not provided")
        recommendations.append("Obtain source of funds for business account")

    details["source_of_funds_assessment"] = sof_assessment

    # -------------------------------------------------------------------------
    # Overall determination
    # -------------------------------------------------------------------------
    has_concerns = any(
        d.get("status") == "concern"
        for d in details.values()
        if isinstance(d, dict)
    )
    has_incomplete = any(
        d.get("status") == "incomplete"
        for d in details.values()
        if isinstance(d, dict)
    )

    if has_concerns:
        suitable = False
        recommendations.insert(0, "Resolve identified concerns before proceeding")
    elif has_incomplete:
        suitable = True
        recommendations.insert(0, "Complete missing information for full assessment")
    else:
        suitable = True

    entity_key = client.legal_name.lower().replace(" ", "_")
    evidence.append({
        "evidence_id": f"suit_biz_{entity_key}",
        "source_type": "utility",
        "source_name": "suitability",
        "entity_screened": client.legal_name,
        "entity_context": "business client",
        "claim": (
            f"Business suitability assessment: "
            f"{'suitable' if suitable else 'concerns identified'}. "
            f"{len(concerns)} concerns, {len(recommendations)} recommendations."
        ),
        "evidence_level": "S",
        "supporting_data": [
            {"concerns_count": len(concerns)},
            {"recommendations_count": len(recommendations)},
            {"sub_assessments": {k: v.get("status", "n/a") for k, v in details.items() if isinstance(v, dict)}},
        ],
        "disposition": "CLEAR" if suitable else "PENDING_REVIEW",
        "confidence": "HIGH" if not has_incomplete else "MEDIUM",
        "timestamp": timestamp,
    })

    return {
        "suitable": suitable,
        "concerns": concerns,
        "recommendations": recommendations,
        "details": details,
        "evidence": evidence,
    }
