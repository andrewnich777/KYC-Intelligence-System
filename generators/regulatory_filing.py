"""
Regulatory Filing Pre-fill Generator.

Maps investigation data to FinCEN SAR Form 111 and FINTRAC STR field structures.
Returns structured dicts suitable for:
  1. JSON export (system-to-system integration)
  2. Human-readable filing worksheet in Excel
  3. Future direct API submission (FINTRAC REST, FinCEN BSA E-Filing)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from models import KYCOutput

logger = logging.getLogger(__name__)


def _split_name(full_name: str, cultural_hint: str | None = None) -> tuple[str, str, str]:
    """Split a full name into (first, middle, last) using multicultural parser.

    Args:
        full_name: Full name string.
        cultural_hint: Country/culture hint for name-order detection.

    Returns:
        (first, middle, last) tuple.
    """
    from utilities.name_parser import parse_name
    nc = parse_name(full_name or "", cultural_hint=cultural_hint)
    first = nc.first_name
    middle = nc.middle_names
    last = nc.family_name
    # Single-name case: parser puts it in family_name, but filings need it as first
    if not first and last and not middle:
        first, last = last, ""
    return first, middle, last


def _get_reporting_entity() -> dict:
    """Get reporting entity information from config or defaults."""
    entity = {
        "institution_name": os.environ.get("REPORTING_ENTITY_NAME", "[INSTITUTION NAME]"),
        "institution_id": os.environ.get("REPORTING_ENTITY_ID", "[INSTITUTION ID]"),
        "fintrac_number": os.environ.get("REPORTING_ENTITY_FINTRAC", "[FINTRAC #]"),
        "rssd_number": os.environ.get("REPORTING_ENTITY_RSSD", "[RSSD #]"),
        "ein": os.environ.get("REPORTING_ENTITY_EIN", "[EIN]"),
        "address": os.environ.get("REPORTING_ENTITY_ADDRESS", "[ADDRESS]"),
        "city": os.environ.get("REPORTING_ENTITY_CITY", "[CITY]"),
        "state": os.environ.get("REPORTING_ENTITY_STATE", "[STATE/PROVINCE]"),
        "zip": os.environ.get("REPORTING_ENTITY_ZIP", "[ZIP/POSTAL CODE]"),
        "country": os.environ.get("REPORTING_ENTITY_COUNTRY", "CA"),
        "contact_name": os.environ.get("REPORTING_ENTITY_CONTACT", "[CONTACT NAME]"),
        "contact_phone": os.environ.get("REPORTING_ENTITY_PHONE", "[PHONE]"),
    }
    placeholders = [k for k, v in entity.items() if isinstance(v, str) and v.startswith("[")]
    if placeholders:
        logger.warning("Reporting entity has placeholder values for: %s — set REPORTING_ENTITY_* env vars", ", ".join(placeholders))
    entity["_has_placeholders"] = bool(placeholders)
    entity["_placeholder_fields"] = placeholders
    return entity


def _extract_activity_dates(output: Any) -> tuple[str, str]:
    """Extract activity date range from investigation timestamps."""
    start = output.generated_at.strftime("%Y-%m-%d")
    end = start  # Same day for KYC investigation
    return start, end


def _map_activity_type_codes(output: Any) -> list[str]:
    """Map investigation findings to FinCEN activity type codes."""
    codes: list[str] = []
    investigation = output.investigation_results
    if not investigation:
        return ["Other"]

    # PEP-related
    if investigation.pep_classification:
        pep = investigation.pep_classification
        if pep.detected_level.value != "NOT_PEP":
            codes.append("Bribery/Gratuity")

    # Sanctions match
    for sr in [investigation.individual_sanctions, investigation.entity_sanctions]:
        if sr and sr.disposition.value in ("POTENTIAL_MATCH", "CONFIRMED_MATCH"):
            codes.append("Terrorist Financing")

    # Adverse media categories
    for am in [investigation.individual_adverse_media, investigation.business_adverse_media]:
        if am and am.categories:
            cat_set = {c.lower() for c in am.categories}
            if cat_set & {"fraud", "financial_fraud"}:
                codes.append("Wire Fraud")
            if cat_set & {"money_laundering", "laundering"}:
                codes.append("Money Laundering")
            if cat_set & {"tax_evasion", "tax"}:
                codes.append("Tax Evasion")
            if cat_set & {"corruption", "bribery"}:
                codes.append("Bribery/Gratuity")

    # Misrepresentation
    if investigation.misrepresentation_detection:
        misrep = investigation.misrepresentation_detection
        if misrep.get("misrepresentations"):
            codes.append("Identity Theft/Fraud")

    if not codes:
        codes.append("Other")

    return list(dict.fromkeys(codes))  # Deduplicate, preserve order


def _condense_narrative(text: str, max_chars: int = 404) -> str:
    """Condense narrative text to fit FINTRAC STR Part G field limit.

    Truncates at a word boundary and appends a continuation note.
    """
    if not text:
        return ""
    # Strip markdown-style bullet prefixes for cleaner output
    lines = text.strip().splitlines()
    clean_lines = [line.lstrip("- ").strip() for line in lines if line.strip()]
    joined = " ".join(clean_lines)

    suffix = "... [see attached narrative]"
    if len(joined) <= max_chars:
        return joined

    # Truncate at word boundary
    cutoff = max_chars - len(suffix)
    truncated = joined[:cutoff].rsplit(" ", 1)[0]
    return truncated + suffix


# ---------------------------------------------------------------------------
# FinCEN SAR
# ---------------------------------------------------------------------------

def prefill_fincen_sar(output: KYCOutput, sar_narrative: dict | None = None) -> dict:
    """Map investigation data to FinCEN SAR Form 111 structure.

    Args:
        output: KYCOutput instance.
        sar_narrative: Optional pre-generated SAR narrative from generate_sar_narrative().

    Returns:
        Dict matching FinCEN SAR Form 111 sections.
    """
    cd = output.client_data or {}
    is_individual = output.client_type.value == "individual"
    reporting_entity = _get_reporting_entity()
    activity_start, activity_end = _extract_activity_dates(output)

    # Part I — Subject Information
    part_i: dict[str, Any] = {
        "subject_type": "individual" if is_individual else "entity",
    }

    if is_individual:
        first, middle, last = _split_name(cd.get("full_name", ""), cultural_hint=cd.get("citizenship"))
        part_i.update({
            "last_name": last,
            "first_name": first,
            "middle_name": middle,
            "dob": cd.get("date_of_birth", ""),
            "ssn_tin": "",  # Never auto-fill full SSN — security
            "address": _format_address(cd.get("address")),
            "identification_type": "Other",
            "identification_number": f"***{cd['sin_last4']}" if cd.get("sin_last4") else "",
            "occupation": "",
            "phone": "",
            "email": "",
        })
        emp = cd.get("employment")
        if isinstance(emp, dict):
            part_i["occupation"] = emp.get("occupation", "")
    else:
        part_i.update({
            "entity_name": cd.get("legal_name", ""),
            "dba_name": cd.get("operating_name", ""),
            "ein": cd.get("business_number", ""),
            "incorporation_state": cd.get("incorporation_jurisdiction", ""),
            "address": _format_address(cd.get("address")),
            "entity_type": cd.get("entity_type", ""),
            "industry": cd.get("industry", ""),
        })

    # Part II — Suspicious Activity Information
    part_ii: dict[str, Any] = {
        "date_range_start": activity_start,
        "date_range_end": activity_end,
        "activity_type_codes": _map_activity_type_codes(output),
        "amount_involved": "Unknown — KYC investigation (no transaction data)",
        "cumulative_amount": "",
    }

    # Part III — Financial Institution Where Activity Occurred
    part_iii = {
        "institution_name": reporting_entity["institution_name"],
        "rssd_number": reporting_entity["rssd_number"],
        "ein": reporting_entity["ein"],
        "address": reporting_entity["address"],
        "city": reporting_entity["city"],
        "state": reporting_entity["state"],
        "zip": reporting_entity["zip"],
        "country": reporting_entity["country"],
        "type_of_institution": os.environ.get("REPORTING_ENTITY_TYPE", "Depository institution"),
        "primary_regulator": os.environ.get("REPORTING_ENTITY_REGULATOR", "Federal Reserve"),
    }

    # Part IV — Filing Institution Contact Information
    part_iv = {
        "institution_name": reporting_entity["institution_name"],
        "ein": reporting_entity["ein"],
        "address": reporting_entity["address"],
        "city": reporting_entity["city"],
        "state": reporting_entity["state"],
        "zip": reporting_entity["zip"],
        "contact_name": reporting_entity["contact_name"],
        "contact_phone": reporting_entity["contact_phone"],
        "filing_type": "Initial",
    }

    # Part V — Suspicious Activity Narrative
    part_v: dict[str, Any] = {
        "narrative_text": "",
        "word_count": 0,
    }
    if sar_narrative:
        part_v["narrative_text"] = sar_narrative.get("narrative_text", "")
        part_v["word_count"] = sar_narrative.get("word_count", 0)

    filing_notes = [
        "This is an AUTO-GENERATED pre-fill. All fields must be reviewed by a compliance officer.",
        "SSN/TIN fields intentionally left blank for security — fill manually.",
        "Transaction amounts are not available from KYC investigation alone.",
        "Verify all dates and amounts against core banking/trading systems.",
    ]
    if reporting_entity.get("_has_placeholders"):
        fields = ", ".join(reporting_entity["_placeholder_fields"])
        filing_notes.insert(0,
            f"INCOMPLETE: {len(reporting_entity['_placeholder_fields'])} institution field(s) need manual entry: "
            f"{fields}. Set REPORTING_ENTITY_* environment variables to auto-fill."
        )

    return {
        "form": "FinCEN SAR Form 111",
        "generated_at": datetime.now().isoformat(),
        "client_id": output.client_id,
        "part_i_subject_information": part_i,
        "part_ii_suspicious_activity": part_ii,
        "part_iii_financial_institution": part_iii,
        "part_iv_filing_institution": part_iv,
        "part_v_narrative": part_v,
        "filing_notes": filing_notes,
    }


# ---------------------------------------------------------------------------
# FINTRAC STR
# ---------------------------------------------------------------------------

def prefill_fintrac_str(output: KYCOutput, sar_narrative: dict | None = None) -> dict:
    """Map investigation data to FINTRAC STR schema.

    Args:
        output: KYCOutput instance.
        sar_narrative: Optional pre-generated SAR narrative.

    Returns:
        Dict matching FINTRAC STR JSON schema structure.
    """
    cd = output.client_data or {}
    is_individual = output.client_type.value == "individual"
    reporting_entity = _get_reporting_entity()

    # Part A — Report Information
    part_a = {
        "report_type": "STR",
        "submission_type": "new",
        "reporting_entity_number": reporting_entity["fintrac_number"],
        "reporting_entity_name": reporting_entity["institution_name"],
        "reporting_entity_type": os.environ.get("REPORTING_ENTITY_TYPE", "Securities dealer"),
        "contact_person": reporting_entity["contact_name"],
        "contact_phone": reporting_entity["contact_phone"],
        "date_of_report": datetime.now().strftime("%Y-%m-%d"),
    }

    # Part B — Transaction Information (placeholder — KYC doesn't have transaction data)
    part_b = {
        "transactions": [],
        "note": "No transaction data available from KYC investigation. Complete from transaction monitoring system.",
    }

    # Part C — Account Information
    part_c = {
        "accounts": [],
        "note": "Account details to be filled from core banking system.",
    }
    for acct in cd.get("account_requests", []):
        if isinstance(acct, dict):
            part_c["accounts"].append({
                "account_type": acct.get("account_type", ""),
                "account_number": "[TO BE FILLED]",
                "status": "Active",
            })

    # Part D — Starting Action (placeholder)
    part_d = {
        "starting_actions": [],
        "note": "Transaction details to be completed from monitoring system.",
    }

    # Part E/F — Entity/Individual Information
    if is_individual:
        part_ef = {
            "type": "individual",
            "last_name": "",
            "first_name": "",
            "other_names": "",
            "date_of_birth": cd.get("date_of_birth", ""),
            "country_of_citizenship": cd.get("citizenship", ""),
            "country_of_residence": cd.get("country_of_residence", ""),
            "address": _format_address(cd.get("address")),
            "occupation": "",
            "employer": "",
            "identification": [],
        }
        first, middle, last = _split_name(cd.get("full_name", ""), cultural_hint=cd.get("citizenship"))
        part_ef["last_name"] = last
        part_ef["first_name"] = first
        if middle:
            part_ef["other_names"] = middle
        emp = cd.get("employment")
        if isinstance(emp, dict):
            part_ef["occupation"] = emp.get("occupation", "")
            part_ef["employer"] = emp.get("employer", "")
    else:
        part_ef = {
            "type": "entity",
            "entity_name": cd.get("legal_name", ""),
            "operating_name": cd.get("operating_name", ""),
            "entity_type": cd.get("entity_type", ""),
            "registration_number": cd.get("business_number", ""),
            "registration_jurisdiction": cd.get("incorporation_jurisdiction", ""),
            "address": _format_address(cd.get("address")),
            "industry": cd.get("industry", ""),
            "beneficial_owners": [],
        }
        for bo in cd.get("beneficial_owners", []):
            if isinstance(bo, dict):
                part_ef["beneficial_owners"].append({
                    "name": bo.get("full_name", ""),
                    "ownership_percentage": bo.get("ownership_percentage", 0),
                    "citizenship": bo.get("citizenship", ""),
                })

    # Part G — Description/Details of Suspicion
    part_g: dict[str, Any] = {
        "narrative_text": "",
        "condensed_narrative": "",
        "grounds_for_suspicion": [],
        "indicators_of_suspicious_activity": [],
        "action_taken": "Filing STR with FINTRAC",
    }

    if sar_narrative:
        full_narrative = sar_narrative.get("narrative_text", "")
        part_g["narrative_text"] = full_narrative
        part_g["indicators_of_suspicious_activity"] = sar_narrative.get("risk_indicators", [])

        # Generate condensed narrative for STR Part G field (404-char limit)
        why_section = sar_narrative.get("five_ws", {}).get("why", "")
        condensed = _condense_narrative(why_section, max_chars=404)
        part_g["condensed_narrative"] = condensed

    # Add SAR risk indicators from investigation
    investigation = output.investigation_results
    if investigation and investigation.sar_risk_assessment:
        grounds = investigation.sar_risk_assessment.get("triggers", [])
        if grounds:
            part_g["grounds_for_suspicion"] = grounds

    filing_notes = [
        "This is an AUTO-GENERATED pre-fill. All fields must be reviewed before submission to FINTRAC.",
        "Transaction details (Parts B/D) must be completed from the transaction monitoring system.",
        "Account numbers must be filled from the core banking system.",
        "Submit within 3 business days of determination of reasonable grounds for suspicion.",
        "Part G condensed_narrative is truncated to 404 characters for the structured STR field. "
        "Full narrative attached as supplementary documentation per FINTRAC guidance.",
    ]
    if reporting_entity.get("_has_placeholders"):
        fields = ", ".join(reporting_entity["_placeholder_fields"])
        filing_notes.insert(0,
            f"INCOMPLETE: {len(reporting_entity['_placeholder_fields'])} institution field(s) need manual entry: "
            f"{fields}. Set REPORTING_ENTITY_* environment variables to auto-fill."
        )

    return {
        "form": "FINTRAC STR",
        "schema_version": "1.0",
        "generated_at": datetime.now().isoformat(),
        "client_id": output.client_id,
        "part_a_report_info": part_a,
        "part_b_transactions": part_b,
        "part_c_accounts": part_c,
        "part_d_starting_actions": part_d,
        "part_ef_subject_info": part_ef,
        "part_g_details_of_suspicion": part_g,
        "filing_notes": filing_notes,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_address(addr: Any) -> str:
    """Format an address dict or model to a single string."""
    if addr is None:
        return ""
    if isinstance(addr, str):
        return addr
    if isinstance(addr, dict):
        parts = [
            addr.get("street", ""),
            addr.get("city", ""),
            addr.get("province_state", ""),
            addr.get("postal_code", ""),
            addr.get("country", ""),
        ]
        return ", ".join(p for p in parts if p)
    # Pydantic model
    if hasattr(addr, "street"):
        parts = [
            getattr(addr, "street", "") or "",
            getattr(addr, "city", "") or "",
            getattr(addr, "province_state", "") or "",
            getattr(addr, "postal_code", "") or "",
            getattr(addr, "country", "") or "",
        ]
        return ", ".join(p for p in parts if p)
    return str(addr)
