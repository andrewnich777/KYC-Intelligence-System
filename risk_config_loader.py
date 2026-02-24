"""
Risk configuration loader.

Reads an optional YAML file to override risk-related constants at startup.
Non-overridable constants (complex types like US_TERMS, CANADA_TERMS) are
protected. Type mismatches are rejected with error logging.
"""

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Constants that must not be overridden (complex types, term sets)
_NON_OVERRIDABLE = frozenset({"US_TERMS", "CANADA_TERMS"})

# Default config path (next to this file)
_DEFAULT_CONFIG_PATH = Path(__file__).parent / "risk_config.yaml"


def load_risk_config(path: Path | str | None = None) -> dict[str, Any]:
    """Read a YAML risk config file and return its contents as a dict.

    Returns an empty dict if the file doesn't exist or YAML is not installed.
    """
    config_path = Path(path) if path else _DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return {}

    try:
        import yaml
    except ImportError:
        logger.debug("PyYAML not installed — skipping risk config loading")
        return {}

    try:
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.error("Failed to parse risk config %s: %s", config_path, e)
        return {}


def apply_risk_config_overrides(path: Path | str | None = None) -> int:
    """Load risk config YAML and patch constants.py with valid overrides.

    Returns the number of constants successfully overridden.
    """
    import constants

    overrides = load_risk_config(path)
    if not overrides:
        return 0

    applied = 0
    for name, value in overrides.items():
        # Check non-overridable
        if name in _NON_OVERRIDABLE:
            logger.error("Cannot override protected constant: %s", name)
            continue

        # Check if name exists in constants module
        if not hasattr(constants, name):
            logger.warning("Unknown constant in risk config: %s (ignored)", name)
            continue

        # Type-check against current value (allow int/float coercion)
        current = getattr(constants, name)
        if isinstance(current, (int, float)) and isinstance(value, (int, float)):
            value = type(current)(value)
        elif not isinstance(value, type(current)):
            logger.error(
                "Type mismatch for %s: expected %s, got %s (value: %r)",
                name,
                type(current).__name__,
                type(value).__name__,
                value,
            )
            continue

        setattr(constants, name, value)
        logger.info("Risk config override: %s = %r", name, value)
        applied += 1

    return applied
