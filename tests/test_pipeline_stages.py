"""Unit tests for pipeline stage modules.

Covers: checkpoint serialization, dispatch tables, config hardening,
evidence store edge cases, and risk scoring guards.
"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evidence_store import EvidenceStore
from models import (
    IndividualClient,
    InvestigationResults,
    RiskAssessment,
    RiskFactor,
    RiskLevel,
)

# ---------------------------------------------------------------------------
# Dispatch table tests
# ---------------------------------------------------------------------------

class TestDispatchTables:
    """Verify dispatch tables cover all expected agents and utilities."""

    def test_all_individual_agents_in_dispatch(self):
        from dispatch import AGENT_DISPATCH
        individual_agents = [
            "IndividualSanctions", "PEPDetection", "IndividualAdverseMedia",
        ]
        for agent in individual_agents:
            assert agent in AGENT_DISPATCH, f"{agent} missing from AGENT_DISPATCH"

    def test_all_business_agents_in_dispatch(self):
        from dispatch import AGENT_DISPATCH
        business_agents = [
            "EntityVerification", "EntitySanctions", "BusinessAdverseMedia",
        ]
        for agent in business_agents:
            assert agent in AGENT_DISPATCH, f"{agent} missing from AGENT_DISPATCH"

    def test_common_agents_in_dispatch(self):
        from dispatch import AGENT_DISPATCH
        common_agents = ["JurisdictionRisk", "TransactionMonitoring"]
        for agent in common_agents:
            assert agent in AGENT_DISPATCH, f"{agent} missing from AGENT_DISPATCH"

    def test_agent_result_field_covers_all_dispatch_entries(self):
        from dispatch import AGENT_DISPATCH, AGENT_RESULT_FIELD
        for agent_name in AGENT_DISPATCH:
            assert agent_name in AGENT_RESULT_FIELD, (
                f"{agent_name} in AGENT_DISPATCH but not in AGENT_RESULT_FIELD"
            )

    def test_dispatch_kwargs_functions_callable(self):
        from dispatch import AGENT_DISPATCH
        for name, (_attr, kwargs_fn) in AGENT_DISPATCH.items():
            assert callable(kwargs_fn), f"{name} kwargs function is not callable"

    def test_individual_sanctions_kwargs_extraction(self):
        from dispatch import AGENT_DISPATCH
        client = MagicMock(spec=IndividualClient)
        client.full_name = "Test Person"
        client.date_of_birth = "1990-01-01"
        client.citizenship = "Canada"
        plan = MagicMock()
        _, kwargs_fn = AGENT_DISPATCH["IndividualSanctions"]
        result = kwargs_fn(client, plan)
        assert result["full_name"] == "Test Person"
        assert result["date_of_birth"] == "1990-01-01"
        assert result["citizenship"] == "Canada"

    def test_jurisdiction_risk_returns_positional_arg(self):
        from dispatch import AGENT_DISPATCH
        client = MagicMock(spec=IndividualClient)
        client.citizenship = "Russia"
        client.country_of_residence = "Canada"
        client.country_of_birth = "Russia"
        client.tax_residencies = []
        plan = MagicMock()
        _, kwargs_fn = AGENT_DISPATCH["JurisdictionRisk"]
        result = kwargs_fn(client, plan)
        assert "_positional_arg" in result
        assert isinstance(result["_positional_arg"], list)
        assert "Russia" in result["_positional_arg"]


# ---------------------------------------------------------------------------
# Checkpoint serialization tests
# ---------------------------------------------------------------------------

class TestCheckpointSerialization:
    """Verify checkpoint serialize/deserialize round-trip."""

    def test_serialize_empty_investigation(self):
        from pipeline_checkpoint import CheckpointMixin
        mixin = CheckpointMixin()
        results = InvestigationResults()
        data = mixin._serialize_investigation(results)
        assert data["failed_agents"] == []
        assert data["is_degraded"] is False

    def test_deserialize_empty_investigation(self):
        from pipeline_checkpoint import CheckpointMixin
        mixin = CheckpointMixin()
        data = {
            "failed_agents": ["SomeAgent"],
            "is_degraded": True,
            "ubo_screening": {},
        }
        results = mixin._deserialize_investigation(data)
        assert results.failed_agents == ["SomeAgent"]
        assert results.is_degraded is True

    def test_serialize_deserialize_roundtrip(self):
        from pipeline_checkpoint import CheckpointMixin
        mixin = CheckpointMixin()
        results = InvestigationResults()
        results.failed_agents = ["TestAgent"]
        results.is_degraded = True
        data = mixin._serialize_investigation(results)
        restored = mixin._deserialize_investigation(data)
        assert restored.failed_agents == ["TestAgent"]
        assert restored.is_degraded is True


# ---------------------------------------------------------------------------
# Config hardening tests
# ---------------------------------------------------------------------------

class TestConfigHardening:
    """Test config resilience against malformed environment variables."""

    def test_malformed_max_retries_uses_default(self):
        with patch.dict(os.environ, {"MAX_RETRIES": "not_a_number"}, clear=False):
            import importlib

            import config as config_module
            importlib.reload(config_module)
            cfg = config_module.Config()
            assert cfg.max_retries == 5  # default

    def test_malformed_initial_backoff_uses_default(self):
        with patch.dict(os.environ, {"INITIAL_BACKOFF": "abc"}, clear=False):
            import importlib

            import config as config_module
            importlib.reload(config_module)
            cfg = config_module.Config()
            assert cfg.initial_backoff == 30  # default

    def test_malformed_agent_delay_uses_default(self):
        with patch.dict(os.environ, {"AGENT_DELAY": ""}, clear=False):
            import importlib

            import config as config_module
            importlib.reload(config_module)
            cfg = config_module.Config()
            assert cfg.agent_delay == 0  # default

    def test_float_env_var_truncates_to_int(self):
        with patch.dict(os.environ, {"MAX_RETRIES": "3"}, clear=False):
            import importlib

            import config as config_module
            importlib.reload(config_module)
            cfg = config_module.Config()
            assert cfg.max_retries == 3

    def test_tool_limit_scaling_by_risk(self):
        from config import get_tool_limit_for_agent
        base = get_tool_limit_for_agent("IndividualSanctions")  # 20
        assert get_tool_limit_for_agent("IndividualSanctions", "LOW") == base
        assert get_tool_limit_for_agent("IndividualSanctions", "HIGH") == int(base * 1.5)
        assert get_tool_limit_for_agent("IndividualSanctions", "CRITICAL") == base * 2


# ---------------------------------------------------------------------------
# Evidence store edge case tests
# ---------------------------------------------------------------------------

class TestEvidenceStoreEdgeCases:
    """Test EvidenceStore beyond basic dedup."""

    def test_remove_by_source_case_insensitive(self):
        store = EvidenceStore()
        store.append({"evidence_id": "E-001", "source_name": "PEPDetection", "claim": "Test"})
        store.append({"evidence_id": "E-002", "source_name": "pepdetection", "claim": "Test2"})
        removed = store.remove_by_source("PEPDETECTION")
        assert removed == 2
        assert len(store) == 0

    def test_remove_by_source_restores_dedup(self):
        store = EvidenceStore()
        store.append({"evidence_id": "E-001", "source_name": "Agent1", "claim": "C1"})
        store.remove_by_source("Agent1")
        # E-001 should be addable again after removal
        added = store.add({"evidence_id": "E-001", "source_name": "Agent1", "claim": "C1 updated"})
        assert added is True
        assert len(store) == 1

    def test_conflicts_detection(self):
        store = EvidenceStore()
        store.append({"evidence_id": "E-001", "entity_screened": "John Doe",
                       "disposition": "CLEAR", "source_name": "Agent1"})
        store.append({"evidence_id": "E-002", "entity_screened": "John Doe",
                       "disposition": "POTENTIAL_MATCH", "source_name": "Agent2"})
        conflicts = store.conflicts()
        assert len(conflicts) == 1
        clear_rec, match_rec = conflicts[0]
        assert clear_rec["disposition"] == "CLEAR"
        assert match_rec["disposition"] == "POTENTIAL_MATCH"

    def test_query_by_entity_case_insensitive(self):
        store = EvidenceStore()
        store.append({"evidence_id": "E-001", "entity_screened": "John Doe", "claim": "C1"})
        results = store.query(entity="JOHN DOE")
        assert len(results) == 1

    def test_by_disposition_groups(self):
        store = EvidenceStore()
        store.append({"evidence_id": "E-001", "disposition": "CLEAR"})
        store.append({"evidence_id": "E-002", "disposition": "CLEAR"})
        store.append({"evidence_id": "E-003", "disposition": "POTENTIAL_MATCH"})
        groups = store.by_disposition()
        assert len(groups["CLEAR"]) == 2
        assert len(groups["POTENTIAL_MATCH"]) == 1

    def test_evidence_level_downgrade_v_without_urls(self):
        store = EvidenceStore()
        record = {"evidence_id": "E-001", "evidence_level": "V", "source_urls": [],
                   "supporting_data": [{"x": 1}]}
        store.add(record)
        assert store[0]["evidence_level"] == "S"

    def test_evidence_level_downgrade_s_without_data(self):
        store = EvidenceStore()
        record = {"evidence_id": "E-001", "evidence_level": "S",
                   "source_urls": ["http://example.com"], "supporting_data": []}
        store.add(record)
        assert store[0]["evidence_level"] == "I"

    def test_no_evidence_id_warning_still_adds(self):
        store = EvidenceStore()
        store.append({"claim": "No ID record", "source_name": "Test"})
        assert len(store) == 1


# ---------------------------------------------------------------------------
# Risk scoring guard tests
# ---------------------------------------------------------------------------

class TestRiskScoringGuards:
    """Test risk scoring edge cases and guards."""

    def test_revise_risk_score_with_none_factors(self):
        """Guard: risk_factors set to None after construction (e.g. corrupted checkpoint)."""
        from utilities.risk_scoring import revise_risk_score
        preliminary = RiskAssessment(
            total_score=10,
            risk_level=RiskLevel.LOW,
            risk_factors=[],
            is_preliminary=True,
            score_history=[{"stage": "intake", "score": 10, "level": "LOW"}],
        )
        # Simulate corruption: force None past Pydantic validation
        object.__setattr__(preliminary, 'risk_factors', None)
        result = revise_risk_score(preliminary)
        assert result.total_score == 0  # No factors
        assert result.is_preliminary is False

    def test_revise_risk_score_with_ubo_cascade(self):
        from constants import UBO_RISK_CONTRIBUTION_FACTOR
        from utilities.risk_scoring import revise_risk_score
        preliminary = RiskAssessment(
            total_score=20,
            risk_level=RiskLevel.MEDIUM,
            risk_factors=[RiskFactor(factor="Test", points=20, category="test", source="intake")],
            is_preliminary=True,
            score_history=[{"stage": "intake", "score": 20, "level": "MEDIUM"}],
        )
        ubo_scores = {"Jane Doe": 50}
        result = revise_risk_score(preliminary, ubo_scores=ubo_scores)
        expected_ubo = int(50 * UBO_RISK_CONTRIBUTION_FACTOR)
        assert result.total_score == 20 + expected_ubo

    def test_pep_expired_replaces_pep_factor(self):
        from constants import PEP_EXPIRED_RESIDUAL_POINTS
        from utilities.risk_scoring import revise_risk_score
        preliminary = RiskAssessment(
            total_score=25,
            risk_level=RiskLevel.MEDIUM,
            risk_factors=[RiskFactor(factor="Domestic PEP", points=25, category="pep", source="intake")],
            is_preliminary=True,
            score_history=[],
        )
        result = revise_risk_score(preliminary, pep_edd_expired=True)
        pep_factors = [f for f in result.risk_factors if f.category == "pep"]
        assert len(pep_factors) == 1
        assert pep_factors[0].points == PEP_EXPIRED_RESIDUAL_POINTS
        assert "Former PEP" in pep_factors[0].factor

    def test_pep_expired_no_effect_without_pep_factors(self):
        from utilities.risk_scoring import revise_risk_score
        preliminary = RiskAssessment(
            total_score=15,
            risk_level=RiskLevel.LOW,
            risk_factors=[RiskFactor(factor="Other risk", points=15, category="other", source="intake")],
            is_preliminary=True,
            score_history=[],
        )
        result = revise_risk_score(preliminary, pep_edd_expired=True)
        assert result.total_score == 15  # No change — no PEP to replace

    def test_score_to_risk_level_boundaries(self):
        from utilities.risk_scoring import _score_to_risk_level
        assert _score_to_risk_level(0) == RiskLevel.LOW
        assert _score_to_risk_level(15) == RiskLevel.LOW
        assert _score_to_risk_level(16) == RiskLevel.MEDIUM
        assert _score_to_risk_level(35) == RiskLevel.MEDIUM
        assert _score_to_risk_level(36) == RiskLevel.HIGH
        assert _score_to_risk_level(60) == RiskLevel.HIGH
        assert _score_to_risk_level(61) == RiskLevel.CRITICAL
        assert _score_to_risk_level(100) == RiskLevel.CRITICAL
