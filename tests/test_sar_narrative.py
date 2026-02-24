"""Tests for SAR/STR narrative drafting generator (Feature 2)."""

import os
import sys
from datetime import datetime
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generators.sar_narrative import (
    _build_evidence_appendix,
    _build_quality_notes,
    _build_what_section,
    _build_where_section,
    _build_who_section,
    _extract_client_info,
    _find_evidence_for_claim,
    generate_sar_narrative,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _mock_output(client_type="individual", degraded=False):
    output = MagicMock()
    output.client_id = "test_sar_001"
    output.client_type.value = client_type
    output.client_data = {
        "full_name": "Maria Chen-Dubois",
        "date_of_birth": "1985-06-15",
        "citizenship": "Canada",
        "country_of_residence": "Canada",
        "employment": {"occupation": "Investment Banker", "employer": "TestBank"},
        "address": {"street": "123 Main St", "city": "Toronto", "province_state": "ON",
                     "postal_code": "M5V 2L7", "country": "CA"},
        "sin_last4": "1234",
    }
    output.generated_at = datetime(2026, 3, 1, 12, 0, 0)
    output.duration_seconds = 120.5
    output.is_degraded = degraded
    output.synthesis.key_findings = ["PEP confirmed in Hong Kong", "Adverse media: fraud allegations"]
    output.synthesis.risk_elevations = [
        {"description": "PEP risk elevation", "evidence_id": "E-002"},
    ]
    output.synthesis.revised_risk_assessment.total_score = 67
    output.synthesis.revised_risk_assessment.risk_level.value = "HIGH"
    output.synthesis.revised_risk_assessment.risk_factors = [
        MagicMock(factor="PEP detected", points=20, category="PEP"),
    ]
    output.synthesis.decision_points = []
    output.investigation_results.failed_agents = ["SomeAgent"] if degraded else []
    output.investigation_results.sar_risk_assessment = {
        "triggers": [{"description": "PEP with adverse media", "evidence_id": "E-002"}],
    }
    output.investigation_results.misrepresentation_detection = {
        "misrepresentations": [{"description": "Employment discrepancy", "evidence_id": "E-003"}],
    }
    output.investigation_results.transaction_monitoring = MagicMock()
    output.investigation_results.transaction_monitoring.industry_typologies = []
    output.investigation_results.transaction_monitoring.geographic_typologies = []
    output.investigation_results.transaction_monitoring.sar_risk_indicators = ["Unusual pattern"]
    output.investigation_results.transaction_monitoring.evidence_records = []
    output.investigation_results.jurisdiction_risk = MagicMock()
    output.investigation_results.jurisdiction_risk.jurisdictions_assessed = ["Canada", "Hong Kong"]
    output.investigation_results.jurisdiction_risk.fatf_grey_list = []
    output.investigation_results.jurisdiction_risk.fatf_black_list = []
    output.investigation_results.jurisdiction_risk.evidence_records = []
    output.review_intelligence.confidence.overall_confidence_grade = "B"
    output.review_intelligence.confidence.degraded = False
    output.review_intelligence.confidence.unknown_pct = 5
    output.review_intelligence.contradictions = []
    return output


def _sample_evidence():
    return [
        {
            "evidence_id": "E-001",
            "source_type": "SanctionsScreening",
            "source_name": "OFAC SDN",
            "claim": "No match found on OFAC SDN list",
            "evidence_level": "V",
            "confidence": "HIGH",
            "timestamp": "2026-02-28T14:32:00Z",
            "source_urls": ["https://example.com/ofac"],
        },
        {
            "evidence_id": "E-002",
            "source_type": "PEPDetection",
            "source_name": "UN PEP Database",
            "claim": "PEP confirmed in Hong Kong",
            "evidence_level": "S",
            "confidence": "HIGH",
            "timestamp": "2026-02-28T14:33:00Z",
            "source_urls": ["https://example.com/pep"],
        },
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestExtractClientInfo:
    def test_individual_fields(self):
        output = _mock_output()
        info = _extract_client_info(output)
        assert info["name"] == "Maria Chen-Dubois"
        assert info["is_individual"] is True
        assert info["dob"] == "1985-06-15"
        assert info["citizenship"] == "Canada"
        assert info["occupation"] == "Investment Banker"
        assert "Toronto" in info["address"]

    def test_business_fields(self):
        output = _mock_output(client_type="business")
        output.client_data = {
            "legal_name": "Test Corp",
            "business_number": "BN123",
            "incorporation_jurisdiction": "Ontario",
            "industry": "Finance",
            "entity_type": "Corporation",
        }
        info = _extract_client_info(output)
        assert info["name"] == "Test Corp"
        assert info["is_individual"] is False
        assert info["business_number"] == "BN123"


class TestBuildWhoSection:
    def test_individual_narrative(self):
        info = {
            "name": "Maria Chen-Dubois",
            "is_individual": True,
            "dob": "1985-06-15",
            "citizenship": "Canada",
            "country_of_residence": "Canada",
            "occupation": "Investment Banker",
            "address": "123 Main St, Toronto",
            "sin_last4": "1234",
        }
        result = _build_who_section(info)
        assert "Maria Chen-Dubois" in result
        assert "1985-06-15" in result
        assert "Investment Banker" in result
        assert "***1234" in result

    def test_business_narrative(self):
        info = {
            "name": "Test Corp",
            "is_individual": False,
            "entity_type": "Corporation",
            "incorporation_jurisdiction": "Ontario",
            "industry": "Finance",
            "business_number": "BN123",
            "address": "456 Bay St",
        }
        result = _build_who_section(info)
        assert "Test Corp" in result
        assert "Corporation" in result
        assert "Ontario" in result


class TestBuildWhatSection:
    def test_includes_key_findings(self):
        output = _mock_output()
        evidence_map = {
            "E-002": {"evidence_id": "E-002", "claim": "PEP confirmed in Hong Kong"},
        }
        text, cited = _build_what_section(output, evidence_map)
        assert "PEP confirmed in Hong Kong" in text
        assert "E-002" in cited

    def test_risk_elevations_with_dict(self):
        output = _mock_output()
        text, cited = _build_what_section(output, {})
        assert "Risk elevation: PEP risk elevation" in text
        assert "E-002" in cited

    def test_risk_elevations_with_pydantic_model(self):
        """Bug fix: risk_elevations may be Pydantic models, not dicts."""
        output = _mock_output()
        elev = MagicMock()
        elev.description = "PEP risk factor"
        elev.factor = ""
        elev.evidence_id = "E-005"
        # Make it NOT a dict so isinstance check returns False
        output.synthesis.risk_elevations = [elev]
        text, cited = _build_what_section(output, {})
        assert "PEP risk factor" in text
        assert "E-005" in cited

    def test_empty_findings_high_risk_shows_fallback(self):
        """HIGH risk with empty key_findings falls back to risk factors."""
        output = _mock_output()
        output.synthesis.key_findings = []
        output.synthesis.risk_elevations = []
        text, cited = _build_what_section(output, {})
        # HIGH risk mock has PEP factor — fallback should surface it
        assert "risk indicators" in text.lower()
        assert "PEP detected" in text

    def test_empty_findings_low_risk_shows_no_indicators(self):
        """LOW risk with empty findings → 'no specific suspicious activity'."""
        output = _mock_output()
        output.synthesis.key_findings = []
        output.synthesis.risk_elevations = []
        output.synthesis.revised_risk_assessment.risk_level.value = "LOW"
        output.intake_classification.preliminary_risk.risk_level.value = "LOW"
        text, cited = _build_what_section(output, {})
        assert "No specific suspicious activity" in text


class TestBuildWhereSection:
    def test_includes_jurisdictions(self):
        output = _mock_output()
        text, _ = _build_where_section(output, {})
        assert "Canada" in text
        assert "Hong Kong" in text

    def test_fatf_grey_list_citations(self):
        """Bug fix: FATF grey list should include inline evidence citations."""
        output = _mock_output()
        er = MagicMock()
        er.evidence_id = "E-010"
        output.investigation_results.jurisdiction_risk.fatf_grey_list = ["Myanmar"]
        output.investigation_results.jurisdiction_risk.evidence_records = [er]
        text, cited = _build_where_section(output, {})
        assert "Myanmar" in text
        assert "E-010" in cited
        assert "[E-010]" in text

    def test_fatf_black_list_citations(self):
        """Bug fix: FATF black list should also include inline evidence citations."""
        output = _mock_output()
        er = MagicMock()
        er.evidence_id = "E-011"
        output.investigation_results.jurisdiction_risk.fatf_black_list = ["North Korea"]
        output.investigation_results.jurisdiction_risk.evidence_records = [er]
        text, cited = _build_where_section(output, {})
        assert "North Korea" in text
        assert "E-011" in cited
        assert "[E-011]" in text

    def test_no_duplicate_evidence_ids_grey_and_black(self):
        """Bug fix: When both grey and black list present, evidence IDs should not be duplicated."""
        output = _mock_output()
        er = MagicMock()
        er.evidence_id = "E-010"
        output.investigation_results.jurisdiction_risk.fatf_grey_list = ["Myanmar"]
        output.investigation_results.jurisdiction_risk.fatf_black_list = ["DPRK"]
        output.investigation_results.jurisdiction_risk.evidence_records = [er]
        _, cited = _build_where_section(output, {})
        assert cited.count("E-010") == 1  # Should appear only once


class TestFindEvidenceForClaim:
    def test_exact_match(self):
        evidence_map = {"E-001": {"claim": "No match found"}}
        assert _find_evidence_for_claim("No match found", evidence_map) == "E-001"

    def test_substring_match(self):
        evidence_map = {"E-001": {"claim": "PEP confirmed in Hong Kong legislature"}}
        assert _find_evidence_for_claim("PEP confirmed in Hong Kong", evidence_map) == "E-001"

    def test_no_match(self):
        evidence_map = {"E-001": {"claim": "Something unrelated"}}
        assert _find_evidence_for_claim("PEP detected", evidence_map) == ""


class TestBuildEvidenceAppendix:
    def test_includes_cited_evidence(self):
        evidence_map = {
            "E-001": {
                "source_name": "OFAC",
                "evidence_level": "V",
                "confidence": "HIGH",
                "claim": "No match",
                "source_urls": ["https://example.com"],
                "timestamp": "2026-02-28",
            },
        }
        result = _build_evidence_appendix(["E-001"], evidence_map)
        assert "[E-001]" in result
        assert "OFAC" in result
        assert "https://example.com" in result

    def test_deduplicates_cited_ids(self):
        evidence_map = {"E-001": {"source_name": "OFAC", "evidence_level": "V",
                                   "confidence": "HIGH", "claim": "test", "source_urls": []}}
        result = _build_evidence_appendix(["E-001", "E-001", "E-001"], evidence_map)
        assert result.count("[E-001]") == 1

    def test_skips_missing_ids(self):
        result = _build_evidence_appendix(["E-999"], {})
        assert "E-999" not in result


class TestBuildQualityNotes:
    def test_degraded_investigation(self):
        output = _mock_output(degraded=True)
        notes = _build_quality_notes(output)
        assert any("DEGRADED" in n for n in notes)

    def test_always_has_placeholders(self):
        output = _mock_output()
        notes = _build_quality_notes(output)
        assert any("PRIOR SARs" in n for n in notes)
        assert any("ACCOUNT DETAILS" in n for n in notes)
        assert any("TRANSACTION AMOUNTS" in n for n in notes)


class TestGenerateSarNarrative:
    def test_returns_required_keys(self):
        output = _mock_output()
        result = generate_sar_narrative(output, evidence_store=_sample_evidence())
        assert "narrative_text" in result
        assert "word_count" in result
        assert "five_ws" in result
        assert "evidence_citations" in result
        assert "risk_indicators" in result
        assert "draft_quality_notes" in result

    def test_five_ws_all_present(self):
        output = _mock_output()
        result = generate_sar_narrative(output, evidence_store=_sample_evidence())
        ws = result["five_ws"]
        for key in ("who", "what", "when", "where", "why", "how"):
            assert key in ws
            assert isinstance(ws[key], str)
            assert len(ws[key]) > 0

    def test_word_count_positive(self):
        output = _mock_output()
        result = generate_sar_narrative(output, evidence_store=_sample_evidence())
        assert result["word_count"] > 50

    def test_evidence_citations_present(self):
        output = _mock_output()
        result = generate_sar_narrative(output, evidence_store=_sample_evidence())
        assert len(result["evidence_citations"]) > 0

    def test_narrative_includes_appendix(self):
        output = _mock_output()
        result = generate_sar_narrative(output, evidence_store=_sample_evidence())
        assert "Sources Appendix" in result["narrative_text"]

    def test_narrative_has_sar_header(self):
        output = _mock_output()
        result = generate_sar_narrative(output, evidence_store=_sample_evidence())
        assert "SUSPICIOUS ACTIVITY REPORT" in result["narrative_text"]

    def test_empty_evidence_store(self):
        output = _mock_output()
        result = generate_sar_narrative(output, evidence_store=[])
        assert result["word_count"] > 0

    def test_none_evidence_store(self):
        output = _mock_output()
        result = generate_sar_narrative(output, evidence_store=None)
        assert result["word_count"] > 0
