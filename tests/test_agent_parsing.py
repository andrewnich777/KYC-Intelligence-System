"""Tests for agent response extraction and data coercion edge cases.

Covers the multi-pattern JSON extraction in BaseAgent._extract_response()
and various data coercion utilities used throughout the pipeline.
"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.base import BaseAgent, _safe_parse_enum

# ---------------------------------------------------------------------------
# Helpers — build a minimal concrete agent for testing extraction
# ---------------------------------------------------------------------------

class _DummyAgent(BaseAgent):
    @property
    def name(self):
        return "TestAgent"

    @property
    def system_prompt(self):
        return "test"

    @property
    def tools(self):
        return []


def _make_response(text: str):
    """Build a mock Anthropic response with the given text content."""
    block = MagicMock()
    block.text = text
    block.type = "text"
    response = MagicMock()
    response.content = [block]
    response.usage.input_tokens = 10
    response.usage.output_tokens = 20
    return response


# ---------------------------------------------------------------------------
# JSON Extraction Tests
# ---------------------------------------------------------------------------

class TestExtractResponseJsonBlock:
    """Test the multi-pattern JSON extraction in _extract_response."""

    def setup_method(self):
        self.agent = _DummyAgent(api_key="test-key")

    def test_standard_json_code_block(self):
        """Standard ```json ... ``` extraction works."""
        text = 'Here is the result:\n```json\n{"status": "ok", "count": 5}\n```\nDone.'
        resp = _make_response(text)
        result = self.agent._extract_response(resp, [])
        assert result["json"] == {"status": "ok", "count": 5}

    def test_untagged_code_block(self):
        """``` ... ``` code block without 'json' tag containing JSON."""
        text = 'Result:\n```\n{"disposition": "CLEAR"}\n```'
        resp = _make_response(text)
        result = self.agent._extract_response(resp, [])
        assert result["json"] == {"disposition": "CLEAR"}

    def test_bare_json_object(self):
        """Bare JSON object in response text without code fences."""
        text = 'The analysis found: {"risk_level": "HIGH", "score": 45} in the data.'
        resp = _make_response(text)
        result = self.agent._extract_response(resp, [])
        assert result["json"]["risk_level"] == "HIGH"

    def test_entire_response_as_json(self):
        """Response that is entirely a JSON string."""
        text = '{"entity": "test", "matches": []}'
        resp = _make_response(text)
        result = self.agent._extract_response(resp, [])
        assert result["json"]["entity"] == "test"

    def test_no_json_in_response(self):
        """Response without any JSON returns None for json_data."""
        text = "I could not find any matches for this entity."
        resp = _make_response(text)
        result = self.agent._extract_response(resp, [])
        assert result["json"] is None

    def test_malformed_json_returns_none(self):
        """Malformed JSON in code block returns None, doesn't crash."""
        text = '```json\n{"broken": true, missing_quote}\n```'
        resp = _make_response(text)
        result = self.agent._extract_response(resp, [])
        assert result["json"] is None

    def test_json_array_in_code_block(self):
        """JSON array in code block is extracted correctly."""
        text = '```json\n[{"id": 1}, {"id": 2}]\n```'
        resp = _make_response(text)
        result = self.agent._extract_response(resp, [])
        assert isinstance(result["json"], list)
        assert len(result["json"]) == 2

    def test_text_content_preserved(self):
        """Text content is always returned regardless of JSON extraction."""
        text = "Some analysis text\n```json\n{}\n```"
        resp = _make_response(text)
        result = self.agent._extract_response(resp, [])
        assert "Some analysis text" in result["text"]

    def test_warning_logged_on_failure(self):
        """Warning is logged when all JSON extraction patterns fail."""
        text = "No JSON here at all, just plain text."
        resp = _make_response(text)
        with patch("agents.base.logger") as mock_logger:
            result = self.agent._extract_response(resp, [])
            assert result["json"] is None
            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            assert "Could not extract JSON" in call_args[0][0]


# ---------------------------------------------------------------------------
# Enum Parsing Tests
# ---------------------------------------------------------------------------

class TestSafeParseEnum:
    """Test _safe_parse_enum utility."""

    def test_valid_enum_value(self):
        from models import RiskLevel
        result = _safe_parse_enum(RiskLevel, "high", RiskLevel.LOW)
        assert result == RiskLevel.HIGH

    def test_empty_value_returns_default(self):
        from models import RiskLevel
        result = _safe_parse_enum(RiskLevel, "", RiskLevel.LOW)
        assert result == RiskLevel.LOW

    def test_none_value_returns_default(self):
        from models import RiskLevel
        result = _safe_parse_enum(RiskLevel, None, RiskLevel.LOW)
        assert result == RiskLevel.LOW

    def test_invalid_value_returns_fallback(self):
        from models import RiskLevel
        result = _safe_parse_enum(RiskLevel, "BANANA", RiskLevel.LOW, fallback=RiskLevel.MEDIUM)
        assert result == RiskLevel.MEDIUM

    def test_invalid_value_returns_default_when_no_fallback(self):
        from models import RiskLevel
        result = _safe_parse_enum(RiskLevel, "BANANA", RiskLevel.LOW)
        assert result == RiskLevel.LOW


# ---------------------------------------------------------------------------
# Evidence Level Validation Tests
# ---------------------------------------------------------------------------

class TestEvidenceLevelDowngrade:
    """Test evidence-level validation in BaseAgent._build_finding_record."""

    def setup_method(self):
        self.agent = _DummyAgent(api_key="test-key")

    def test_verified_without_urls_downgraded_to_sourced(self):
        """VERIFIED claim with no URLs → downgraded to SOURCED."""
        from models import EvidenceClass
        record = self.agent._build_finding_record(
            evidence_id="E-TEST-001",
            entity="Test Entity",
            claim="Some verified claim",
            supporting_data=[{"quote": "test"}],
            evidence_level=EvidenceClass.VERIFIED,
            source_urls=[],
        )
        assert record.evidence_level == EvidenceClass.SOURCED

    def test_sourced_without_data_downgraded_to_inferred(self):
        """SOURCED claim with no supporting_data → downgraded to INFERRED."""
        from models import EvidenceClass
        record = self.agent._build_finding_record(
            evidence_id="E-TEST-002",
            entity="Test Entity",
            claim="Some sourced claim",
            supporting_data=[],
            evidence_level=EvidenceClass.SOURCED,
            source_urls=["https://example.com"],
        )
        assert record.evidence_level == EvidenceClass.INFERRED

    def test_verified_with_urls_and_data_stays_verified(self):
        """VERIFIED with both URLs and data → stays VERIFIED."""
        from models import EvidenceClass
        record = self.agent._build_finding_record(
            evidence_id="E-TEST-003",
            entity="Test Entity",
            claim="Properly verified claim",
            supporting_data=[{"quote": "evidence"}],
            evidence_level=EvidenceClass.VERIFIED,
            source_urls=["https://example.com/source"],
        )
        assert record.evidence_level == EvidenceClass.VERIFIED

    def test_no_level_infers_sourced_with_urls(self):
        """No explicit level + URLs → inferred as SOURCED."""
        from models import EvidenceClass
        record = self.agent._build_finding_record(
            evidence_id="E-TEST-004",
            entity="Test Entity",
            claim="Auto-inferred claim",
            supporting_data=[{"data": "yes"}],
            source_urls=["https://example.com"],
        )
        assert record.evidence_level == EvidenceClass.SOURCED

    def test_no_level_infers_inferred_without_urls(self):
        """No explicit level + no URLs → inferred as INFERRED."""
        from models import EvidenceClass
        record = self.agent._build_finding_record(
            evidence_id="E-TEST-005",
            entity="Test Entity",
            claim="No URL claim",
        )
        assert record.evidence_level == EvidenceClass.INFERRED
