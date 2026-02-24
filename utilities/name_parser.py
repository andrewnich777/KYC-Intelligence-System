"""
Multicultural name parser for KYC screening and regulatory filings.

Parses full names into structured components using cultural heuristics.
Always preserves the original name for display and sanctions matching.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Cultural hint mapping from country to name-order convention
# ---------------------------------------------------------------------------

_FAMILY_FIRST_HINTS = {
    "zh", "cn", "china", "tw", "taiwan", "hk", "hong kong",
    "ja", "jp", "japan",
    "ko", "kr", "korea", "south korea",
    "vn", "vietnam", "hu", "hungary",
}

_ARABIC_PREFIXES = {"al-", "el-", "bin", "ibn", "bint", "abu", "abd"}

_HISPANIC_COUNTRIES = {
    "mx", "mexico", "es", "spain", "co", "colombia", "ar", "argentina",
    "pe", "peru", "cl", "chile", "ve", "venezuela", "ec", "ecuador",
    "gt", "guatemala", "cu", "cuba", "do", "dominican republic",
    "hn", "honduras", "pa", "panama", "cr", "costa rica",
    "uy", "uruguay", "py", "paraguay", "bo", "bolivia",
    "sv", "el salvador", "ni", "nicaragua",
}

_HONORIFICS = {"mr", "mr.", "mrs", "mrs.", "ms", "ms.", "dr", "dr.", "prof", "prof.", "sir", "dame", "hon", "hon."}
_SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "esq", "esq.", "phd", "ph.d.", "md", "m.d."}


@dataclass
class NameComponents:
    """Parsed name components."""
    given_names: list[str] = field(default_factory=list)
    family_name: str = ""
    honorifics: list[str] = field(default_factory=list)
    suffixes: list[str] = field(default_factory=list)
    original: str = ""

    @property
    def first_name(self) -> str:
        return self.given_names[0] if self.given_names else ""

    @property
    def middle_names(self) -> str:
        return " ".join(self.given_names[1:]) if len(self.given_names) > 1 else ""


def _detect_convention(name: str, cultural_hint: str | None) -> str:
    """Detect naming convention from hint or name content."""
    if cultural_hint:
        hint_lower = cultural_hint.lower().strip()
        if hint_lower in _FAMILY_FIRST_HINTS:
            return "east_asian"
        if hint_lower in _HISPANIC_COUNTRIES:
            return "hispanic"
        # Check for Arabic-culture countries
        arabic_countries = {
            "sa", "saudi arabia", "ae", "uae", "united arab emirates",
            "eg", "egypt", "iq", "iraq", "sy", "syria", "lb", "lebanon",
            "jo", "jordan", "kw", "kuwait", "bh", "bahrain", "om", "oman",
            "qa", "qatar", "ye", "yemen", "ly", "libya", "tn", "tunisia",
            "dz", "algeria", "ma", "morocco", "sd", "sudan", "ps", "palestine",
        }
        if hint_lower in arabic_countries:
            return "arabic"

    # Check for CJK characters
    if re.search(r'[\u4e00-\u9fff\u3400-\u4dbf\uac00-\ud7af\u3040-\u309f\u30a0-\u30ff]', name):
        return "east_asian"

    # Check for Arabic name prefixes
    name_lower = name.lower()
    if any(f" {prefix}" in f" {name_lower}" for prefix in _ARABIC_PREFIXES):
        return "arabic"

    return "western"


def parse_name(full_name: str, cultural_hint: str | None = None) -> NameComponents:
    """Parse a full name into structured components.

    Args:
        full_name: The complete name string.
        cultural_hint: Country code or name (e.g. "zh", "China", "Mexico")
            to guide name-order interpretation.  Inferred from citizenship
            or country_of_birth when available.

    Returns:
        NameComponents with given_names, family_name, honorifics, suffixes,
        and the original string preserved.
    """
    result = NameComponents(original=full_name)

    if not full_name or not full_name.strip():
        return result

    parts = full_name.strip().split()

    # Strip honorifics and suffixes
    clean_parts: list[str] = []
    for part in parts:
        if part.lower().rstrip(".") in {h.rstrip(".") for h in _HONORIFICS}:
            result.honorifics.append(part)
        elif part.lower().rstrip(".") in {s.rstrip(".") for s in _SUFFIXES}:
            result.suffixes.append(part)
        else:
            clean_parts.append(part)

    if not clean_parts:
        return result

    convention = _detect_convention(full_name, cultural_hint)

    if convention == "east_asian":
        # Family name first: "Chen Wei Ming" → family="Chen", given=["Wei", "Ming"]
        result.family_name = clean_parts[0]
        result.given_names = clean_parts[1:]

    elif convention == "arabic":
        # Compound family names with al-/el- prefix
        # "Mohammed bin Salman al-Rashid" → given=["Mohammed"], family="al-Rashid"
        # Find the last al-/el- prefixed segment (skip connectors like bin/ibn)
        _connectors = {"bin", "ibn", "bint", "abu", "abd"}
        family_start = None
        for i, part in enumerate(clean_parts):
            if part.lower().startswith(("al-", "el-")) and part.lower() not in _connectors:
                family_start = i
                break

        if family_start is not None:
            # Given names = everything before the first connector
            # "Mohammed bin Salman al-Rashid" → given=["Mohammed"] (bin Salman is patronymic)
            given = []
            for part in clean_parts[:family_start]:
                if part.lower() in _connectors:
                    break
                given.append(part)
            result.given_names = given
            result.family_name = " ".join(clean_parts[family_start:])
        else:
            # No al-/el- prefix found — check for connector-based structure
            # e.g. "Ahmed bin Hassan" → given=["Ahmed"], family="Hassan"
            connector_idx = None
            for i, part in enumerate(clean_parts):
                if part.lower() in _connectors and i > 0:
                    connector_idx = i
                    break

            if connector_idx is not None:
                result.given_names = clean_parts[:connector_idx]
                # Family = everything after connector
                result.family_name = " ".join(clean_parts[connector_idx + 1:])
            else:
                # Fallback to western convention
                result.given_names = clean_parts[:-1] if len(clean_parts) > 1 else []
                result.family_name = clean_parts[-1]

    elif convention == "hispanic":
        # Two family names (paternal + maternal): "Carlos Garcia Lopez"
        if len(clean_parts) >= 3:
            result.given_names = clean_parts[:-2]
            result.family_name = " ".join(clean_parts[-2:])
        elif len(clean_parts) == 2:
            result.given_names = [clean_parts[0]]
            result.family_name = clean_parts[1]
        else:
            result.family_name = clean_parts[0]

    else:  # western
        # "Sarah Jane Thompson" → given=["Sarah", "Jane"], family="Thompson"
        if len(clean_parts) == 1:
            result.family_name = clean_parts[0]
        else:
            result.given_names = clean_parts[:-1]
            result.family_name = clean_parts[-1]

    return result
