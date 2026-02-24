"""
Decision outcome tracking and risk calibration.

Records post-decision outcomes (SAR filed, escalation, no issues) and
computes accuracy metrics for risk model calibration.  All data stored
as append-only JSONL under ``results/_analytics/``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

_OUTCOMES_FILE = "outcomes.jsonl"
_ANALYTICS_DIR = "_analytics"


def _outcomes_path(output_dir: str | Path = "results") -> Path:
    return Path(output_dir) / _ANALYTICS_DIR / _OUTCOMES_FILE


# =========================================================================
# Recording
# =========================================================================

def record_outcome(
    client_id: str,
    decision: str,
    officer: str = "",
    timestamp: str | None = None,
    output_dir: str | Path = "results",
    risk_level: str | None = None,
    risk_score: int | float | None = None,
) -> None:
    """Append an onboarding decision outcome to the JSONL log."""
    path = _outcomes_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "type": "decision",
        "client_id": client_id,
        "decision": decision,
        "officer": officer,
        "timestamp": timestamp or datetime.now(UTC).isoformat(),
    }
    if risk_level is not None:
        entry["risk_level"] = risk_level
    if risk_score is not None:
        entry["risk_score"] = risk_score
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def record_post_onboarding_event(
    client_id: str,
    event_type: str,
    details: str = "",
    output_dir: str | Path = "results",
) -> None:
    """Record a post-onboarding event (SAR filed, escalation, no_issues, etc.)."""
    path = _outcomes_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "type": "post_onboarding",
        "client_id": client_id,
        "event_type": event_type,
        "details": details,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# =========================================================================
# Metrics
# =========================================================================

@dataclass
class FeedbackMetrics:
    """Aggregate accuracy metrics computed from outcome data."""
    total_cases: int = 0
    approvals: int = 0
    escalations: int = 0
    declines: int = 0
    conditionals: int = 0
    post_onboarding_sars: int = 0
    post_onboarding_no_issues: int = 0

    @property
    def approval_rate(self) -> float:
        return self.approvals / self.total_cases if self.total_cases else 0.0

    @property
    def escalation_rate(self) -> float:
        return self.escalations / self.total_cases if self.total_cases else 0.0

    @property
    def false_negative_rate(self) -> float:
        """Approved clients that later generated SARs."""
        if self.approvals == 0:
            return 0.0
        return self.post_onboarding_sars / self.approvals

    @property
    def false_positive_rate(self) -> float:
        """Escalated/declined clients where no issues emerged."""
        blocked = self.escalations + self.declines
        if blocked == 0:
            return 0.0
        return self.post_onboarding_no_issues / blocked


def compute_accuracy_metrics(
    lookback_days: int = 90,
    output_dir: str | Path = "results",
) -> FeedbackMetrics:
    """Compute accuracy metrics from the outcome log."""
    path = _outcomes_path(output_dir)
    if not path.exists():
        return FeedbackMetrics()

    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    metrics = FeedbackMetrics()

    # Track per-client decisions
    client_decisions: dict[str, str] = {}

    for line in path.read_text(encoding="utf-8").strip().splitlines():
        try:
            entry = json.loads(line)
        except Exception:
            continue

        ts = entry.get("timestamp", "")
        try:
            entry_time = datetime.fromisoformat(ts)
            if entry_time < cutoff:
                continue
        except (ValueError, TypeError):
            continue  # Skip entries with unparseable timestamps

        if entry["type"] == "decision":
            cid = entry["client_id"]
            decision = entry.get("decision", "").upper()
            client_decisions[cid] = decision
            metrics.total_cases += 1
            if decision == "APPROVE":
                metrics.approvals += 1
            elif decision == "ESCALATE":
                metrics.escalations += 1
            elif decision == "DECLINE":
                metrics.declines += 1
            elif decision == "CONDITIONAL":
                metrics.conditionals += 1

        elif entry["type"] == "post_onboarding":
            event = entry.get("event_type", "").lower()
            if event in ("sar_filed", "sar"):
                metrics.post_onboarding_sars += 1
            elif event in ("no_issues", "clean"):
                metrics.post_onboarding_no_issues += 1

    return metrics


# =========================================================================
# Calibration
# =========================================================================

@dataclass
class CalibrationReport:
    """Risk calibration analysis."""
    total_cases: int = 0
    suggestions: list[str] = field(default_factory=list)


def compute_calibration(
    lookback_days: int = 90,
    output_dir: str | Path = "results",
) -> CalibrationReport:
    """Compare predicted risk vs actual outcomes to identify calibration drift."""
    metrics = compute_accuracy_metrics(lookback_days=lookback_days, output_dir=output_dir)
    report = CalibrationReport(total_cases=metrics.total_cases)

    if metrics.total_cases < 5:
        report.suggestions.append(
            "Insufficient data for calibration — need at least 5 completed cases"
        )
        return report

    if metrics.false_negative_rate > 0.05:
        report.suggestions.append(
            f"False negative rate {metrics.false_negative_rate:.0%} — "
            f"approved clients generating SARs. Consider tightening approval thresholds."
        )

    if metrics.false_positive_rate > 0.50:
        report.suggestions.append(
            f"False positive rate {metrics.false_positive_rate:.0%} — "
            f"over half of blocked clients had no issues. "
            f"Consider relaxing escalation criteria."
        )

    if metrics.escalation_rate > 0.40:
        report.suggestions.append(
            f"Escalation rate {metrics.escalation_rate:.0%} is high — "
            f"review risk scoring thresholds to reduce officer burden."
        )

    if not report.suggestions:
        report.suggestions.append("Risk calibration within normal parameters.")

    return report
