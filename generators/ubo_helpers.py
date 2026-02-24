"""
Shared UBO field extraction helpers for brief generators.
"""

from constants import FAILED_SENTINEL_KEY

# Lookup for known enum values that .title() mangles (acronyms, multi-word)
_DISPLAY_NAMES = {
    "DOMESTIC_PEP": "Domestic PEP",
    "FOREIGN_PEP": "Foreign PEP",
    "PEP_FAMILY": "PEP Family",
    "PEP_ASSOCIATE": "PEP Associate",
    "HIO": "HIO",
    "POTENTIAL_MATCH": "Potential Match",
    "CONFIRMED_MATCH": "Confirmed Match",
    "FALSE_POSITIVE": "False Positive",
    "PENDING_REVIEW": "Pending Review",
    "MATERIAL_CONCERN": "Material Concern",
    "HIGH_RISK": "High Risk",
    "LOW_CONCERN": "Low Concern",
}


def extract_ubo_field(ubo_data: dict, screening_type: str, field: str, default: str = "Pending") -> str:
    """Extract a human-readable status from UBO screening data.

    Args:
        ubo_data: Dict with keys like "sanctions", "pep", "adverse_media",
                  each mapping to a result dict.
        screening_type: Which screening result to look up (e.g. "sanctions").
        field: The field within the screening result (e.g. "disposition").
        default: Value to return when data is missing.
    """
    if not ubo_data:
        return default
    result = ubo_data.get(screening_type)
    if not result or not isinstance(result, dict):
        return default
    # Handle failed screening sentinels — show "Error" instead of misleading "Clear"
    if result.get(FAILED_SENTINEL_KEY):
        return "Error"
    value = result.get(field, default)
    if value in ("CLEAR", "NOT_PEP"):
        return "Clear"
    return _DISPLAY_NAMES.get(value, str(value).replace("_", " ").title())
