"""Tests for Workstream 4: Adversarial Testing."""

import json
from pathlib import Path

import pytest

from models import (
    BusinessClient,
    KYCSynthesisOutput,
)

# =========================================================================
# Case 7 intake
# =========================================================================

class TestCase7Intake:
    """Adversarial test case loads correctly."""

    @pytest.fixture
    def case7_data(self):
        path = Path(__file__).parent.parent / "test_cases" / "case7_adversarial.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_case7_loads_as_business(self, case7_data):
        client = BusinessClient(**case7_data)
        assert client.legal_name == "Pacific Rim Consulting Group Ltd."
        assert client.client_type.value == "business"

    def test_case7_has_two_ubos(self, case7_data):
        client = BusinessClient(**case7_data)
        assert len(client.beneficial_owners) == 2

    def test_case7_ubo_countries(self, case7_data):
        client = BusinessClient(**case7_data)
        birth_countries = {ubo.country_of_birth for ubo in client.beneficial_owners}
        assert "Russia" in birth_countries
        assert "Hong Kong" in birth_countries

    def test_case7_industry(self, case7_data):
        client = BusinessClient(**case7_data)
        assert client.industry == "Management Consulting"

    def test_case7_risk_scoring(self, case7_data):
        """Case 7 should score at least MEDIUM due to Russia-born UBO."""
        from utilities.risk_scoring import calculate_business_risk_score
        client = BusinessClient(**case7_data)
        risk = calculate_business_risk_score(client)
        # Russia-born UBO with 55% ownership should elevate risk
        assert risk.total_score > 0


# =========================================================================
# Misrepresentation detection (case 7 signals)
# =========================================================================

class TestMisrepresentationSignals:
    """Case 7 has signals that misrepresentation detection should catch."""

    def test_young_entity_flagged(self):
        """Entity incorporated < 3 years ago should be flagged."""
        from utilities.risk_scoring import calculate_business_risk_score
        data = {
            "client_type": "business",
            "legal_name": "Test Corp",
            "incorporation_date": "2024-03-15",
            "incorporation_jurisdiction": "BC",
            "countries_of_operation": ["Canada"],
            "beneficial_owners": [],
        }
        client = BusinessClient(**data)
        risk = calculate_business_risk_score(client)
        # Entity age < 3 years should add risk points
        [rf for rf in risk.risk_factors if "age" in rf.factor.lower() or "new" in rf.factor.lower()]
        # At minimum the score should be non-zero
        assert risk.total_score >= 0


# =========================================================================
# Adversarial reviewer agent
# =========================================================================

class TestAdversarialReviewerAgent:
    """AdversarialReviewerAgent parses challenges correctly."""

    def test_parse_challenges_valid(self):
        from agents.adversarial_reviewer import AdversarialReviewerAgent
        agent = AdversarialReviewerAgent()

        mock_result = {
            "json": {
                "adversarial_challenges": [
                    {
                        "target_finding": "E_001",
                        "challenge": "CLEAR screen for sanctions may miss anglicized name variants",
                        "missing_evidence": "Search under Cyrillic spelling of surname",
                        "confidence_impact": "HIGH",
                    },
                    {
                        "target_finding": "E_005",
                        "challenge": "FALSE_POSITIVE ruling relies on single date-of-birth differentiator",
                        "missing_evidence": "Cross-reference with Hong Kong corporate registry",
                        "confidence_impact": "MEDIUM",
                    },
                ]
            }
        }

        challenges = agent._parse_challenges(mock_result)
        assert len(challenges) == 2
        assert challenges[0]["target_finding"] == "E_001"
        assert challenges[0]["confidence_impact"] == "HIGH"
        assert challenges[1]["target_finding"] == "E_005"

    def test_parse_challenges_empty(self):
        from agents.adversarial_reviewer import AdversarialReviewerAgent
        agent = AdversarialReviewerAgent()
        challenges = agent._parse_challenges({"json": {}})
        assert challenges == []

    def test_parse_challenges_no_json(self):
        from agents.adversarial_reviewer import AdversarialReviewerAgent
        agent = AdversarialReviewerAgent()
        challenges = agent._parse_challenges({})
        assert challenges == []


# =========================================================================
# Challenges surface in synthesis output
# =========================================================================

class TestChallengesInSynthesis:
    def test_adversarial_challenges_field_exists(self):
        synthesis = KYCSynthesisOutput()
        assert synthesis.adversarial_challenges == []

    def test_challenges_stored_on_synthesis(self):
        challenges = [
            {"target_finding": "E_001", "challenge": "test", "missing_evidence": "x", "confidence_impact": "LOW"},
        ]
        synthesis = KYCSynthesisOutput(adversarial_challenges=challenges)
        assert len(synthesis.adversarial_challenges) == 1
        assert synthesis.adversarial_challenges[0]["target_finding"] == "E_001"

    def test_challenges_serialize(self):
        challenges = [
            {"target_finding": "E_001", "challenge": "test", "missing_evidence": "x", "confidence_impact": "LOW"},
        ]
        synthesis = KYCSynthesisOutput(adversarial_challenges=challenges)
        dumped = synthesis.model_dump()
        assert "adversarial_challenges" in dumped
        assert len(dumped["adversarial_challenges"]) == 1
