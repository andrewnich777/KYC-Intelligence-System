"""
Shared coercion helpers for parsing AI-generated JSON into strict Pydantic models.

AI output is unpredictable: strings arrive as dicts, ints as strings, nulls where
strings are expected, field names vary. These helpers form the adapter layer between
raw AI JSON and our typed models.
"""


def coerce_str(value, default: str = "") -> str:
    """Coerce AI output to str. Handles None, int, float."""
    if value is None:
        return default
    return str(value)


def coerce_bool(value, default: bool = False) -> bool:
    """Coerce AI output to bool. Handles str, int, None."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "yes", "1")
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def coerce_int(value, default: int = 0) -> int:
    """Coerce AI output to int. Handles str, float, None."""
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except (ValueError, TypeError):
            return default
    return default


def coerce_list(value) -> list:
    """Coerce AI output to a list. Returns [] for non-list values."""
    if not isinstance(value, list):
        return []
    return value


def coerce_str_list(value) -> list[str]:
    """Coerce AI output to list[str]. Handles list[dict], list[str], or non-list."""
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            for key in ("finding", "description", "summary", "detail",
                        "condition", "item", "text", "reason", "value"):
                if key in item and isinstance(item[key], str):
                    result.append(item[key])
                    break
            else:
                parts = [str(v) for v in item.values() if v and isinstance(v, str)]
                if parts:
                    result.append(" — ".join(parts))
        else:
            result.append(str(item))
    return result


def coerce_dict_values(d: dict) -> dict:
    """Coerce all values in a dict to strings, converting None to ''."""
    return {k: (str(v) if v is not None else "") for k, v in d.items()}


def coerce_contradictions(value) -> list:
    """Coerce AI contradiction dicts, translating field name variants.

    AI may return finding_1/finding_2 or finding_a/finding_b.
    Model expects finding_a/finding_b/agent_a/agent_b/resolution_guidance.
    """
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if not isinstance(item, dict):
            result.append(item)
            continue
        coerced = {
            "finding_a": str(item.get("finding_a") or item.get("finding_1") or ""),
            "finding_b": str(item.get("finding_b") or item.get("finding_2") or ""),
            "agent_a": str(item.get("agent_a") or ""),
            "agent_b": str(item.get("agent_b") or ""),
            "resolution": str(item.get("resolution") or ""),
            "resolution_guidance": str(item.get("resolution_guidance") or item.get("resolution") or ""),
        }
        result.append(coerced)
    return result
