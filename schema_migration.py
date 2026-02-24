"""
Schema versioning for KYC pipeline outputs.

Checks that loaded data (checkpoints, saved results) matches the current
schema version. Logs warnings on mismatch so operators know when stored
data was produced by a different version.
"""

import logging

logger = logging.getLogger(__name__)

# Bump this when KYCOutput or checkpoint structure changes
SCHEMA_VERSION = "1.0.0"


def check_schema_version(data: dict, source: str = "unknown") -> bool:
    """Check if loaded data matches the current schema version.

    Args:
        data: Dict loaded from a checkpoint or saved result.
        source: Human-readable label for log messages (e.g. "checkpoint").

    Returns:
        True if version matches or no version found (legacy data).
        False if there is a version mismatch.
    """
    stored_version = data.get("schema_version")

    if stored_version is None:
        logger.info(
            "No schema_version in %s — assuming legacy data (pre-%s)",
            source,
            SCHEMA_VERSION,
        )
        return True

    if stored_version != SCHEMA_VERSION:
        logger.warning(
            "Schema version mismatch in %s: stored=%s, current=%s. "
            "Data may need migration.",
            source,
            stored_version,
            SCHEMA_VERSION,
        )
        return False

    return True
