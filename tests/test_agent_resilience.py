"""Tests for agent resilience (Phase D) — degraded status tracking."""

from models import ClientType, InvestigationPlan, InvestigationResults, KYCOutput


class TestDegradedTracking:
    def test_investigation_defaults_not_degraded(self):
        results = InvestigationResults()
        assert results.is_degraded is False
        assert results.failed_agents == []

    def test_marking_degraded(self):
        results = InvestigationResults()
        results.failed_agents.append("IndividualSanctions")
        results.is_degraded = True
        assert results.is_degraded is True
        assert "IndividualSanctions" in results.failed_agents

    def test_degraded_propagates_to_output(self):
        results = InvestigationResults()
        results.is_degraded = True
        results.failed_agents = ["TestAgent"]

        output = KYCOutput(
            client_id="test",
            client_type=ClientType.INDIVIDUAL,
            client_data={},
            intake_classification=InvestigationPlan(
                client_type=ClientType.INDIVIDUAL, client_id="test"
            ),
            investigation_results=results,
            is_degraded=results.is_degraded,
        )
        assert output.is_degraded is True

    def test_confidence_capped_when_degraded(self):
        from utilities.review_intelligence import _assess_confidence

        evidence = [
            {"evidence_id": "e1", "evidence_level": "V", "source_name": "Agent1"},
            {"evidence_id": "e2", "evidence_level": "V", "source_name": "Agent1"},
            {"evidence_id": "e3", "evidence_level": "S", "source_name": "Agent2"},
        ]

        # Without failed agents — should be grade A (100% V+S)
        result_ok = _assess_confidence(evidence)
        assert result_ok.overall_confidence_grade in ("A", "B")

        # With failed agents — should be capped at C
        result_degraded = _assess_confidence(evidence, failed_agents=["FailedAgent"])
        assert result_degraded.overall_confidence_grade == "C"
        assert result_degraded.degraded is True

    def test_confidence_already_low_not_changed(self):
        from utilities.review_intelligence import _assess_confidence

        evidence = [
            {"evidence_id": "e1", "evidence_level": "I", "source_name": "Agent1"},
            {"evidence_id": "e2", "evidence_level": "U", "source_name": "Agent1"},
        ]

        result = _assess_confidence(evidence, failed_agents=["FailedAgent"])
        # Already D or F, should not be changed to C
        assert result.overall_confidence_grade in ("D", "F")
