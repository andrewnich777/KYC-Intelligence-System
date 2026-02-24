"""Tests for Workstream 5: Cost & Scale Modeling."""

import json
import tempfile
from pathlib import Path

from config import get_tool_limit_for_agent
from pipeline_metrics import (
    AgentMetric,
    BatchMetrics,
    CostThresholds,
    PipelineMetrics,
    check_cost,
)

# =========================================================================
# Adaptive token budgets
# =========================================================================

class TestAdaptiveTokenBudgets:
    def test_default_returns_base_limit(self):
        limit = get_tool_limit_for_agent("IndividualSanctions")
        assert limit == 20

    def test_low_risk_no_change(self):
        limit = get_tool_limit_for_agent("IndividualSanctions", risk_level="LOW")
        assert limit == 20

    def test_medium_risk_no_change(self):
        limit = get_tool_limit_for_agent("IndividualSanctions", risk_level="MEDIUM")
        assert limit == 20

    def test_high_risk_50_percent_increase(self):
        limit = get_tool_limit_for_agent("IndividualSanctions", risk_level="HIGH")
        assert limit == 30  # 20 * 1.5

    def test_critical_risk_double(self):
        limit = get_tool_limit_for_agent("IndividualSanctions", risk_level="CRITICAL")
        assert limit == 40  # 20 * 2.0

    def test_unknown_agent_uses_default(self):
        limit = get_tool_limit_for_agent("UnknownAgent", risk_level="HIGH")
        assert limit == 18  # 12 * 1.5

    def test_none_risk_level(self):
        limit = get_tool_limit_for_agent("PEPDetection", risk_level=None)
        assert limit == 12  # Base limit


# =========================================================================
# Cost threshold warnings
# =========================================================================

class TestCostThresholds:
    def _make_metrics(self, cost: float) -> PipelineMetrics:
        """Create metrics with a specific cost via mocked agent tokens."""
        # Use Sonnet pricing: $3/$15 per 1M tokens
        # To get a specific cost, we need: cost = (input/1M)*3 + (output/1M)*15
        # Simplify: set output tokens so (output/1M)*15 = cost
        output_tokens = int(cost / 15.0 * 1_000_000)
        return PipelineMetrics(
            agents=[AgentMetric(name="test", model="claude-sonnet-4-6",
                                output_tokens=output_tokens)]
        )

    def test_under_warn_no_warnings(self):
        metrics = self._make_metrics(0.50)
        warnings = check_cost(metrics)
        assert len(warnings) == 0

    def test_at_warn_threshold(self):
        metrics = self._make_metrics(1.50)
        thresholds = CostThresholds(per_case_warn=1.00, per_case_max=5.00)
        warnings = check_cost(metrics, thresholds)
        assert len(warnings) == 1
        assert "warning" in warnings[0].lower()

    def test_exceeds_max(self):
        metrics = self._make_metrics(6.00)
        thresholds = CostThresholds(per_case_warn=1.00, per_case_max=5.00)
        warnings = check_cost(metrics, thresholds)
        assert len(warnings) == 1
        assert "EXCEEDS" in warnings[0]


# =========================================================================
# Batch cost aggregation
# =========================================================================

class TestBatchMetrics:
    def test_append_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            metrics = PipelineMetrics(
                agents=[AgentMetric(name="test", model="claude-sonnet-4-6",
                                    input_tokens=10000, output_tokens=5000)]
            )
            BatchMetrics.append_run(output_dir, "client_1", metrics)
            BatchMetrics.append_run(output_dir, "client_2", metrics)

            entries = BatchMetrics.load(output_dir, lookback_days=1)
            assert len(entries) == 2
            assert entries[0]["client_id"] == "client_1"
            assert entries[1]["client_id"] == "client_2"

    def test_summary_computes_correctly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            metrics = PipelineMetrics(
                agents=[AgentMetric(name="test", model="claude-sonnet-4-6",
                                    input_tokens=100000, output_tokens=50000)]
            )
            BatchMetrics.append_run(output_dir, "c1", metrics)
            BatchMetrics.append_run(output_dir, "c2", metrics)

            summary = BatchMetrics.summary(output_dir, lookback_days=1)
            assert summary["cases"] == 2
            assert summary["total_cost"] > 0
            assert summary["avg_cost"] > 0
            assert summary["projected_monthly"] > 0

    def test_empty_log_returns_zeros(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = BatchMetrics.summary(Path(tmpdir), lookback_days=1)
            assert summary["cases"] == 0
            assert summary["total_cost"] == 0.0

    def test_jsonl_format(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            metrics = PipelineMetrics(
                agents=[AgentMetric(name="test", model="claude-sonnet-4-6",
                                    input_tokens=1000, output_tokens=500)]
            )
            BatchMetrics.append_run(output_dir, "test_client", metrics)
            log_path = output_dir / "_analytics" / "cost_log.jsonl"
            assert log_path.exists()
            lines = log_path.read_text(encoding="utf-8").strip().splitlines()
            assert len(lines) == 1
            entry = json.loads(lines[0])
            assert "client_id" in entry
            assert "cost_usd" in entry
            assert "timestamp" in entry
