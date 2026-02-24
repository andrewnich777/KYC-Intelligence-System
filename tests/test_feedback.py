"""Tests for Workstream 6: Feedback Loop."""

import json
import tempfile
from pathlib import Path

import pytest

from utilities.feedback_tracker import (
    compute_accuracy_metrics,
    compute_calibration,
    record_outcome,
    record_post_onboarding_event,
)

# =========================================================================
# Outcome recording
# =========================================================================

class TestOutcomeRecording:
    def test_record_outcome_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            record_outcome("client_1", "APPROVE", officer="Officer A", output_dir=tmpdir)
            path = Path(tmpdir) / "_analytics" / "outcomes.jsonl"
            assert path.exists()
            lines = path.read_text().strip().splitlines()
            assert len(lines) == 1
            entry = json.loads(lines[0])
            assert entry["client_id"] == "client_1"
            assert entry["decision"] == "APPROVE"
            assert entry["officer"] == "Officer A"
            assert entry["type"] == "decision"

    def test_record_multiple_outcomes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            record_outcome("c1", "APPROVE", output_dir=tmpdir)
            record_outcome("c2", "DECLINE", output_dir=tmpdir)
            record_outcome("c3", "ESCALATE", output_dir=tmpdir)
            path = Path(tmpdir) / "_analytics" / "outcomes.jsonl"
            lines = path.read_text().strip().splitlines()
            assert len(lines) == 3

    def test_record_post_onboarding_event(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            record_post_onboarding_event("c1", "sar_filed", "SAR for suspicious wire", output_dir=tmpdir)
            path = Path(tmpdir) / "_analytics" / "outcomes.jsonl"
            entry = json.loads(path.read_text().strip())
            assert entry["type"] == "post_onboarding"
            assert entry["event_type"] == "sar_filed"
            assert entry["client_id"] == "c1"


# =========================================================================
# Accuracy metrics
# =========================================================================

class TestAccuracyMetrics:
    def _seed_outcomes(self, tmpdir):
        record_outcome("c1", "APPROVE", output_dir=tmpdir)
        record_outcome("c2", "APPROVE", output_dir=tmpdir)
        record_outcome("c3", "ESCALATE", output_dir=tmpdir)
        record_outcome("c4", "DECLINE", output_dir=tmpdir)
        record_outcome("c5", "CONDITIONAL", output_dir=tmpdir)
        record_post_onboarding_event("c1", "no_issues", output_dir=tmpdir)
        record_post_onboarding_event("c2", "sar_filed", output_dir=tmpdir)
        record_post_onboarding_event("c3", "no_issues", output_dir=tmpdir)

    def test_computes_correctly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._seed_outcomes(tmpdir)
            m = compute_accuracy_metrics(lookback_days=1, output_dir=tmpdir)
            assert m.total_cases == 5
            assert m.approvals == 2
            assert m.escalations == 1
            assert m.declines == 1
            assert m.conditionals == 1
            assert m.post_onboarding_sars == 1
            assert m.post_onboarding_no_issues == 2

    def test_approval_rate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._seed_outcomes(tmpdir)
            m = compute_accuracy_metrics(lookback_days=1, output_dir=tmpdir)
            assert m.approval_rate == pytest.approx(0.4)

    def test_false_negative_rate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._seed_outcomes(tmpdir)
            m = compute_accuracy_metrics(lookback_days=1, output_dir=tmpdir)
            # 1 SAR out of 2 approvals = 50%
            assert m.false_negative_rate == pytest.approx(0.5)

    def test_empty_returns_zeros(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            m = compute_accuracy_metrics(output_dir=tmpdir)
            assert m.total_cases == 0
            assert m.approval_rate == 0.0


# =========================================================================
# Calibration report
# =========================================================================

class TestCalibrationReport:
    def test_insufficient_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            record_outcome("c1", "APPROVE", output_dir=tmpdir)
            cal = compute_calibration(lookback_days=1, output_dir=tmpdir)
            assert any("Insufficient" in s for s in cal.suggestions)

    def test_high_false_negative_flagged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(10):
                record_outcome(f"c{i}", "APPROVE", output_dir=tmpdir)
            # 2 SARs from 10 approved = 20% false negative
            record_post_onboarding_event("c0", "sar_filed", output_dir=tmpdir)
            record_post_onboarding_event("c1", "sar_filed", output_dir=tmpdir)

            cal = compute_calibration(lookback_days=1, output_dir=tmpdir)
            assert any("tightening" in s.lower() for s in cal.suggestions)

    def test_calibration_normal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(10):
                record_outcome(f"c{i}", "APPROVE", output_dir=tmpdir)
            for i in range(10):
                record_post_onboarding_event(f"c{i}", "no_issues", output_dir=tmpdir)

            cal = compute_calibration(lookback_days=1, output_dir=tmpdir)
            assert any("normal" in s.lower() for s in cal.suggestions)
