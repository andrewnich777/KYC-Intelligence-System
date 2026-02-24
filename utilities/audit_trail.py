"""
Structured audit trail.

Appends timestamped JSONL events to results/{client_id}/audit_trail.jsonl.
Instrumented at pipeline stage boundaries, agent outcomes, and officer actions.
"""

import json
from datetime import UTC, datetime
from pathlib import Path


def log_event(
    output_dir: Path,
    client_id: str,
    event_type: str,
    **details,
) -> None:
    """Append a structured event to the audit trail.

    Args:
        output_dir: Root results directory.
        client_id: Client identifier (subdirectory name).
        event_type: Event category (e.g. stage_start, agent_complete, officer_action).
        **details: Arbitrary key-value pairs logged with the event.
    """
    trail_dir = output_dir / client_id
    trail_dir.mkdir(parents=True, exist_ok=True)
    trail_path = trail_dir / "audit_trail.jsonl"

    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "event": event_type,
        "client_id": client_id,
        **details,
    }
    with open(trail_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")
