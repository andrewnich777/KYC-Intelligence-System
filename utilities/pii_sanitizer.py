"""
PII sanitizer for log output and debug display.

Provides regex-based redaction of common PII patterns (SIN, DOB, email, phone)
and model-aware field masking for dicts derived from Pydantic models tagged
with ``pii=True`` in their Field metadata.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Regex patterns for common PII
# ---------------------------------------------------------------------------

_SIN_RE = re.compile(
    r"\b\d{3}[\s\-]?\d{3}[\s\-]?\d{3}\b"
)

_DOB_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b"
)

_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)

_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?1[\s\-]?)?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{4}(?!\d)"
)

REDACTED = "***REDACTED***"


def sanitize(text: str) -> str:
    """Redact common PII patterns from free-text log messages."""
    text = _SIN_RE.sub(REDACTED, text)
    text = _DOB_RE.sub(REDACTED, text)
    text = _EMAIL_RE.sub(REDACTED, text)
    text = _PHONE_RE.sub(REDACTED, text)
    return text


# ---------------------------------------------------------------------------
# Model-aware dict masking
# ---------------------------------------------------------------------------

# Hardcoded fallback — used when model introspection isn't available.
_FALLBACK_PII_FIELDS: set[str] = {
    "full_name",
    "date_of_birth",
    "sin_last4",
    "sin_last_four",
    "us_tin",
    "tax_id",
    "phone",
    "email",
    "employer",
    # Address sub-fields (when flattened)
    "street",
    "postal_code",
}


def _collect_pii_fields() -> set[str]:
    """Introspect Pydantic models for fields tagged ``pii=True``.

    Scans all BaseModel subclasses in :mod:`models` and collects field names
    whose ``json_schema_extra`` includes ``{"pii": True}``.  Falls back to the
    hardcoded set if the import fails or yields nothing.
    """
    try:
        from pydantic import BaseModel

        import models as _models

        tagged: set[str] = set()
        for attr_name in dir(_models):
            cls = getattr(_models, attr_name, None)
            if isinstance(cls, type) and issubclass(cls, BaseModel) and cls is not BaseModel:
                for field_name, field_info in cls.model_fields.items():
                    meta = field_info.json_schema_extra or {}
                    if meta.get("pii"):
                        tagged.add(field_name)
        return tagged if tagged else _FALLBACK_PII_FIELDS
    except Exception:
        return _FALLBACK_PII_FIELDS


PII_FIELD_NAMES: set[str] = _collect_pii_fields()


def _pii_fields_from_model(model_class: type | None) -> set[str]:
    """Extract field names tagged ``pii=True`` from a Pydantic model class."""
    if model_class is None:
        return PII_FIELD_NAMES

    tagged: set[str] = set()
    for name, field_info in model_class.model_fields.items():
        meta = field_info.json_schema_extra or {}
        if meta.get("pii"):
            tagged.add(name)
    return tagged or PII_FIELD_NAMES


def sanitize_dict(d: dict[str, Any], model_class: type | None = None) -> dict[str, Any]:
    """Return a shallow copy of *d* with PII fields replaced by ``***REDACTED***``.

    If *model_class* is provided, only fields whose ``Field()`` metadata
    includes ``pii=True`` are masked.  Otherwise, a default set of known
    PII field names is used.
    """
    pii_fields = _pii_fields_from_model(model_class)
    out: dict[str, Any] = {}
    for key, value in d.items():
        if key in pii_fields and value is not None:
            out[key] = REDACTED
        elif isinstance(value, dict):
            out[key] = sanitize_dict(value, model_class=None)
        elif isinstance(value, list):
            out[key] = [
                sanitize_dict(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            out[key] = value
    return out
