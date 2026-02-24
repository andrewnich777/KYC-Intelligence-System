"""
Tests for conservative defaults on failed agents and no-JSON fallback paths.

WS2: Ensures failures don't silently clear subjects.
"""

from models import (
    AdverseMediaLevel,
    AdverseMediaResult,
    JurisdictionRiskResult,
    PEPClassification,
    PEPLevel,
    RiskLevel,
)

# =========================================================================
# Failed factory methods — conservative defaults
# =========================================================================

class TestFailedFactoryDefaults:
    """Failed factories should use conservative, not optimistic, defaults."""

    def test_pep_failed_requires_edd(self):
        """Failed PEP check should require EDD as precaution."""
        result = PEPClassification.failed("John Doe", "timeout error")
        assert result.detected_level == PEPLevel.NOT_PEP
        assert result.edd_required is True  # Conservative: was False

    def test_adverse_media_failed_not_clear(self):
        """Failed adverse media should NOT be CLEAR."""
        result = AdverseMediaResult.failed("John Doe", "timeout error")
        assert result.overall_level == AdverseMediaLevel.LOW_CONCERN  # Was CLEAR
        assert result.overall_level != AdverseMediaLevel.CLEAR

    def test_jurisdiction_risk_failed_not_low(self):
        """Failed jurisdiction risk should NOT be LOW."""
        result = JurisdictionRiskResult.failed("test", "timeout error")
        assert result.overall_jurisdiction_risk == RiskLevel.MEDIUM  # Was LOW
        assert result.overall_jurisdiction_risk != RiskLevel.LOW


# =========================================================================
# No-JSON fallback — text signal checking
# =========================================================================

class TestNoJsonFallbackPEP:
    """PEP agent no-JSON path checks text for clear signals."""

    def test_clear_signal_in_text(self):
        """If agent prose says 'not a pep', treat as clear."""
        from agents.pep_detection import PEPDetectionAgent
        from models import DispositionStatus
        agent = PEPDetectionAgent.__new__(PEPDetectionAgent)
        agent._fetched_urls = []
        agent._search_queries = []
        result = {"json": {}, "text": "The individual is not a PEP based on research."}
        pep = agent._parse_result(result, "Jane Smith", False)
        assert pep.detected_level == PEPLevel.NOT_PEP
        assert pep.edd_required is False
        assert pep.evidence_records[0].disposition == DispositionStatus.CLEAR

    def test_no_clear_signal_in_text(self):
        """If agent prose is ambiguous, flag for review."""
        from agents.pep_detection import PEPDetectionAgent
        from models import DispositionStatus
        agent = PEPDetectionAgent.__new__(PEPDetectionAgent)
        agent._fetched_urls = []
        agent._search_queries = []
        result = {"json": {}, "text": "Unable to complete the search."}
        pep = agent._parse_result(result, "Jane Smith", False)
        assert pep.edd_required is True
        assert pep.evidence_records[0].disposition == DispositionStatus.PENDING_REVIEW


class TestNoJsonFallbackAdverseMedia:
    """Adverse media no-JSON path checks text for clear signals."""

    def test_clear_signal_in_text(self):
        """If agent prose says 'no adverse media', treat as CLEAR."""
        from agents.adverse_media_base import AdverseMediaParserMixin
        from agents.base import BaseAgent
        from models import DispositionStatus

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
        result = {"json": {}, "text": "No adverse media found for this individual."}
        amr = agent._parse_adverse_media_result(result, "Test Entity", "adv_test", "Adverse media")
        assert amr.overall_level == AdverseMediaLevel.CLEAR
        assert amr.evidence_records[0].disposition == DispositionStatus.CLEAR

    def test_no_clear_signal_in_text(self):
        """If agent prose is ambiguous, flag LOW_CONCERN."""
        from agents.adverse_media_base import AdverseMediaParserMixin
        from agents.base import BaseAgent
        from models import DispositionStatus

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
        result = {"json": {}, "text": "Search returned mixed results."}
        amr = agent._parse_adverse_media_result(result, "Test Entity", "adv_test", "Adverse media")
        assert amr.overall_level == AdverseMediaLevel.LOW_CONCERN
        assert amr.evidence_records[0].disposition == DispositionStatus.PENDING_REVIEW


class TestNoJsonFallbackJurisdiction:
    """Jurisdiction risk no-JSON path checks text for clear signals."""

    def test_clear_signal_in_text(self):
        from agents.jurisdiction_risk import JurisdictionRiskAgent
        from models import DispositionStatus
        agent = JurisdictionRiskAgent.__new__(JurisdictionRiskAgent)
        agent._fetched_urls = []
        agent._search_queries = []
        result = {"json": {}, "text": "All jurisdictions are low risk."}
        jr = agent._parse_result(result, ["Canada"])
        assert jr.overall_jurisdiction_risk == RiskLevel.LOW
        assert jr.evidence_records[0].disposition == DispositionStatus.CLEAR

    def test_no_clear_signal_in_text(self):
        from agents.jurisdiction_risk import JurisdictionRiskAgent
        from models import DispositionStatus
        agent = JurisdictionRiskAgent.__new__(JurisdictionRiskAgent)
        agent._fetched_urls = []
        agent._search_queries = []
        result = {"json": {}, "text": "Unable to assess jurisdiction risk."}
        jr = agent._parse_result(result, ["Canada"])
        assert jr.overall_jurisdiction_risk == RiskLevel.MEDIUM
        assert jr.evidence_records[0].disposition == DispositionStatus.PENDING_REVIEW


class TestBroadClearMatching:
    """Sanctions agents should not match bare 'clear' substring."""

    def test_word_unclear_does_not_match(self):
        """'unclear' contains 'clear' but should not trigger clear disposition."""
        # The fix replaces "clear" with "cleared" and "no sanctions"
        clear_signals = ["no match", "no result", "not found", "no sanctioned",
                         "cleared", "no sanctions", "no hits", "does not appear"]
        text = "the situation is unclear and requires further investigation"
        text_lower = text.lower()
        is_clear = any(s in text_lower for s in clear_signals)
        assert is_clear is False

    def test_nuclear_does_not_match(self):
        """'nuclear' contains 'clear' but should not trigger clear disposition."""
        clear_signals = ["no match", "no result", "not found", "no sanctioned",
                         "cleared", "no sanctions", "no hits", "does not appear"]
        text = "Nuclear proliferation concerns identified"
        text_lower = text.lower()
        is_clear = any(s in text_lower for s in clear_signals)
        assert is_clear is False

    def test_cleared_does_match(self):
        """'cleared' should trigger clear disposition."""
        clear_signals = ["no match", "no result", "not found", "no sanctioned",
                         "cleared", "no sanctions", "no hits", "does not appear"]
        text = "The individual has been cleared from all sanctions lists"
        text_lower = text.lower()
        is_clear = any(s in text_lower for s in clear_signals)
        assert is_clear is True
