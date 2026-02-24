"""
Tests for bidirectional cross-checks and failed-agent EDD triggers.

WS3: Ensures evidence and AI classifications stay consistent.
"""

from models import (
    AdverseMediaLevel,
    DispositionStatus,
)


class TestPEPBidirectionalCrossCheck:
    """If AI says NOT_PEP but evidence is non-CLEAR, require EDD."""

    def test_not_pep_with_pending_evidence_requires_edd(self):
        from agents.pep_detection import PEPDetectionAgent
        agent = PEPDetectionAgent.__new__(PEPDetectionAgent)
        agent._fetched_urls = []
        agent._search_queries = []
        # Agent returns structured data with NOT_PEP but a finding record
        result = {
            "json": {
                "entity_screened": "Jane Doe",
                "detected_level": "NOT_PEP",
                "positions_found": [
                    {"position": "unknown role", "organization": "unknown org"}
                ],
            },
            "text": "",
        }
        pep = agent._parse_result(result, "Jane Doe", False)
        # The position creates a finding record (non-CLEAR), so even though
        # level is NOT_PEP, evidence-based cross-check should require EDD
        has_non_clear = any(
            getattr(r, 'disposition', DispositionStatus.CLEAR) != DispositionStatus.CLEAR
            for r in pep.evidence_records
        )
        if has_non_clear:
            assert pep.edd_required is True


class TestAdverseMediaBidirectionalCrossCheck:
    """If AI says CLEAR but evidence has non-CLEAR records, elevate."""

    def test_clear_level_with_finding_records_elevates(self):
        from agents.adverse_media_base import AdverseMediaParserMixin
        from agents.base import BaseAgent

        class MockAgent(AdverseMediaParserMixin, BaseAgent):
            @property
            def name(self): return "TestAdvMedia"
            @property
            def system_prompt(self): return ""
            @property
            def tools(self): return []

        agent = MockAgent.__new__(MockAgent)
        agent._fetched_urls = []
        agent._search_queries = []
        # Agent returns structured data with CLEAR level but has articles
        result = {
            "json": {
                "entity_screened": "Test Corp",
                "overall_level": "CLEAR",
                "articles_found": [{"title": "Fraud allegations against Test Corp"}],
                "categories": ["fraud"],
            },
            "text": "",
        }
        amr = agent._parse_adverse_media_result(result, "Test Corp", "adv_test", "Adverse media")
        # Articles create finding records which are non-CLEAR
        # Bidirectional cross-check should elevate from CLEAR to LOW_CONCERN
        has_non_clear = any(
            getattr(r, 'disposition', DispositionStatus.CLEAR) != DispositionStatus.CLEAR
            for r in amr.evidence_records
        )
        if has_non_clear:
            assert amr.overall_level != AdverseMediaLevel.CLEAR


class TestEDDFailedAgentTrigger:
    """Failed PEP agent should trigger EDD."""

    def _make_client(self):
        from unittest.mock import MagicMock

        from models import IndividualClient
        client = MagicMock(spec=IndividualClient)
        client.full_name = "Test User"
        client.citizenship = "Canada"
        client.country_of_residence = "Canada"
        client.country_of_birth = "Canada"
        client.tax_residencies = []
        client.account_requests = []
        client.pep_self_declaration = False
        client.pep_details = None
        client.annual_income = 100000
        return client

    def _make_investigation(self, failed_agents=None):
        from unittest.mock import MagicMock

        from models import InvestigationResults
        investigation = MagicMock(spec=InvestigationResults)
        investigation.failed_agents = failed_agents or []
        investigation.individual_sanctions = None
        investigation.entity_sanctions = None
        investigation.individual_adverse_media = None
        investigation.business_adverse_media = None
        investigation.pep_classification = None
        investigation.ubo_screening = None
        return investigation

    def test_failed_pep_agent_triggers_edd(self):
        from unittest.mock import MagicMock

        from models import RiskAssessment, RiskLevel

        client = self._make_client()
        risk = MagicMock(spec=RiskAssessment)
        risk.total_score = 20
        risk.risk_level = RiskLevel.LOW
        investigation = self._make_investigation(["PEPDetection"])

        from utilities.edd_requirements import assess_edd_requirements
        result = assess_edd_requirements(client, risk, investigation)

        # Should trigger EDD because PEP agent failed
        assert result["edd_required"] is True
        assert any("PEP screening agent failed" in t for t in result["triggers"])

    def test_no_failed_pep_agent_no_trigger(self):
        from unittest.mock import MagicMock

        from models import RiskAssessment, RiskLevel

        client = self._make_client()
        risk = MagicMock(spec=RiskAssessment)
        risk.total_score = 20
        risk.risk_level = RiskLevel.LOW
        investigation = self._make_investigation([])

        from utilities.edd_requirements import assess_edd_requirements
        result = assess_edd_requirements(client, risk, investigation)

        assert not any("PEP screening agent failed" in t for t in result["triggers"])
