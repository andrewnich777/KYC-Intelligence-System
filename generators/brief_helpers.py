"""
Shared helpers for brief generators.

Provides the common header timestamp, footer tagline, and UBO screening
table used across all four brief generators.
"""

from datetime import UTC, datetime

from generators.markdown_utils import esc as _esc
from generators.ubo_helpers import extract_ubo_field as _extract_ubo_field


def render_brief_header(title: str, client_id: str) -> list[str]:
    """Return the standard brief header lines (title + timestamp)."""
    now = datetime.now(UTC).strftime("%B %d, %Y at %I:%M %p UTC")
    return [
        f"# {title}: {client_id}",
        f"*Generated: {now}*",
        "",
    ]


def render_brief_footer() -> list[str]:
    """Return the standard brief footer lines."""
    return [
        "---",
        "*AI investigates. Rules classify. Humans decide.*",
    ]


def render_ubo_screening_table(ubo_screening: dict) -> list[str]:
    """Render the standard UBO cascade screening summary table.

    Columns: Owner | % | Sanctions | PEP | Adverse Media
    """
    if not ubo_screening:
        return []
    lines = [
        "| Owner | % | Sanctions | PEP | Adverse Media |",
        "|-------|---|-----------|-----|---------------|",
    ]
    for ubo_name, ubo_data in ubo_screening.items():
        pct = ubo_data.get("ownership_percentage", "?") if isinstance(ubo_data, dict) else "?"
        sanctions_disp = _extract_ubo_field(ubo_data, "sanctions", "disposition", "Pending")
        pep_level = _extract_ubo_field(ubo_data, "pep", "detected_level", "Pending")
        media_level = _extract_ubo_field(ubo_data, "adverse_media", "overall_level", "Pending")
        lines.append(
            f"| {_esc(ubo_name)} | {pct} | {_esc(sanctions_disp)} | {_esc(pep_level)} | {_esc(media_level)} |"
        )
    lines.append("")
    return lines
