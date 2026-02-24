"""Tests for transaction monitoring agent models and SAR risk utility."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import (
    AdverseMediaLevel,
    AdverseMediaResult,
    AMLTypology,
    BusinessClient,
    DispositionStatus,
    IndividualClient,
    InvestigationResults,
    PEPClassification,
    PEPLevel,
    SanctionsResult,
    TransactionMonitoringResult,
)
from utilities.sar_risk_assessment import assess_sar_risk


class TestAMLTypologyModel:
    def test_basic_creation(self):
        t = AMLTypology(
            typology_name="Trade-Based ML",
            description="Over/under-invoicing of goods",
            relevance="HIGH",
        )
        assert t.typology_name == "Trade-Based ML"
        assert t.relevance == "HIGH"
        assert t.indicators == []

    def test_with_indicators(self):
        t = AMLTypology(
            typology_name="Structuring",
            description="Breaking transactions to avoid reporting",
            relevance="MEDIUM",
            indicators=["Multiple sub-threshold deposits", "Round amounts"],
            monitoring_recommendation="Flag deposits just under $10K",
        )
        assert len(t.indicators) == 2
        assert t.monitoring_recommendation != ""


class TestTransactionMonitoringResult:
    def test_defaults(self):
        tmr = TransactionMonitoringResult(entity_screened="Test Corp")
        assert tmr.entity_screened == "Test Corp"
        assert tmr.industry_typologies == []
        assert tmr.geographic_typologies == []
        assert tmr.recommended_monitoring_frequency == "standard"
        assert tmr.sar_risk_indicators == []

    def test_with_typologies(self):
        tmr = TransactionMonitoringResult(
            entity_screened="Test Corp",
            industry_typologies=[
                AMLTypology(
                    typology_name="Trade-Based ML",
                    description="Import/export ML",
                    relevance="HIGH",
                ),
            ],
            geographic_typologies=[
                AMLTypology(
                    typology_name="Shell Company Layering",
                    description="Offshore shell companies",
                    relevance="MEDIUM",
                ),
            ],
            recommended_monitoring_frequency="enhanced",
            sar_risk_indicators=["Unusual transaction patterns"],
        )
        assert len(tmr.industry_typologies) == 1
        assert len(tmr.geographic_typologies) == 1
        assert tmr.recommended_monitoring_frequency == "enhanced"


class TestSARRiskAssessment:
    def test_low_risk_clear(self):
        """No findings → LOW SAR risk."""
        client = IndividualClient(full_name="Jane Doe")
        investigation = InvestigationResults()
        result = assess_sar_risk(client, investigation)
        assert result["sar_risk_level"] == "LOW"
        assert len(result["triggers"]) == 0
        assert "evidence" in result

    def test_confirmed_sanctions_critical(self):
        """Confirmed sanctions match → HIGH/CRITICAL SAR risk."""
        client = IndividualClient(full_name="Test Person")
        investigation = InvestigationResults(
            individual_sanctions=SanctionsResult(
                entity_screened="Test Person",
                disposition=DispositionStatus.CONFIRMED_MATCH,
                screening_sources=["OFAC SDN"],
                matches=[{"list_name": "OFAC SDN", "matched_name": "Test Person"}],
            ),
        )
        result = assess_sar_risk(client, investigation)
        assert result["sar_risk_level"] in ("HIGH", "CRITICAL")
        assert len(result["triggers"]) > 0
        assert any("sanctions" in t.lower() for t in result["triggers"])

    def test_adverse_media_crime_categories(self):
        """Adverse media with crime categories → elevated SAR risk."""
        client = IndividualClient(full_name="Test Person")
        investigation = InvestigationResults(
            individual_adverse_media=AdverseMediaResult(
                entity_screened="Test Person",
                overall_level=AdverseMediaLevel.HIGH_RISK,
                categories=["fraud", "money_laundering"],
            ),
        )
        result = assess_sar_risk(client, investigation)
        assert result["sar_risk_level"] in ("MEDIUM", "HIGH", "CRITICAL")
        assert any("adverse" in t.lower() for t in result["triggers"])

    def test_misrepresentation_elevates_risk(self):
        """Material misrepresentation detected → elevated SAR risk."""
        client = IndividualClient(full_name="Test Person")
        investigation = InvestigationResults(
            misrepresentation_detection={
                "misrepresentations": [
                    {
                        "field": "pep_self_declaration",
                        "declared_value": "False",
                        "found_value": "FOREIGN_PEP",
                        "severity": "CRITICAL",
                    },
                ],
                "has_material_misrepresentation": True,
                "str_consideration_triggered": True,
            },
        )
        result = assess_sar_risk(client, investigation)
        assert result["sar_risk_level"] in ("HIGH", "CRITICAL")
        assert any("misrepresentation" in t.lower() for t in result["triggers"])

    def test_multiple_factors_compound(self):
        """Multiple risk factors compound → CRITICAL."""
        client = IndividualClient(full_name="Test Person", annual_income=50000, net_worth=5000000)
        investigation = InvestigationResults(
            individual_sanctions=SanctionsResult(
                entity_screened="Test Person",
                disposition=DispositionStatus.POTENTIAL_MATCH,
                screening_sources=["OFAC"],
            ),
            individual_adverse_media=AdverseMediaResult(
                entity_screened="Test Person",
                overall_level=AdverseMediaLevel.HIGH_RISK,
                categories=["fraud", "money_laundering"],
            ),
            pep_classification=PEPClassification(
                entity_screened="Test Person",
                detected_level=PEPLevel.FOREIGN_PEP,
            ),
        )
        result = assess_sar_risk(client, investigation)
        assert result["sar_risk_level"] == "CRITICAL"
        assert result["risk_score"] >= 60
        assert len(result["draft_narrative_elements"]) > 0

    def test_business_transaction_volume_anomaly(self):
        """Business with high transaction/revenue ratio → trigger."""
        client = BusinessClient(
            legal_name="Test Corp",
            annual_revenue=100000,
            expected_transaction_volume=500000,
        )
        investigation = InvestigationResults()
        result = assess_sar_risk(client, investigation)
        assert any("pass-through" in t.lower() for t in result["triggers"])

    def test_ubo_sanctions_concern(self):
        """UBO with sanctions concern → trigger."""
        client = BusinessClient(legal_name="Test Corp")
        investigation = InvestigationResults(
            ubo_screening={
                "Viktor Petrov": {
                    "sanctions": {"disposition": "POTENTIAL_MATCH"},
                    "pep": {"detected_level": "NOT_PEP"},
                    "adverse_media": {"overall_level": "CLEAR"},
                },
            },
        )
        result = assess_sar_risk(client, investigation)
        assert any("ubo" in t.lower() for t in result["triggers"])

    def test_evidence_always_present(self):
        """Result should always include evidence records."""
        client = IndividualClient(full_name="Test")
        investigation = InvestigationResults()
        result = assess_sar_risk(client, investigation)
        assert "evidence" in result
        assert len(result["evidence"]) > 0

    def test_filing_timeline(self):
        """CRITICAL risk should have immediate filing timeline."""
        client = IndividualClient(full_name="Test Person")
        investigation = InvestigationResults(
            individual_sanctions=SanctionsResult(
                entity_screened="Test Person",
                disposition=DispositionStatus.CONFIRMED_MATCH,
                screening_sources=["OFAC SDN"],
            ),
            individual_adverse_media=AdverseMediaResult(
                entity_screened="Test Person",
                overall_level=AdverseMediaLevel.HIGH_RISK,
                categories=["money_laundering", "fraud"],
            ),
        )
        result = assess_sar_risk(client, investigation)
        if result["sar_risk_level"] == "CRITICAL":
            assert "immediate" in result["filing_timeline"].lower()
