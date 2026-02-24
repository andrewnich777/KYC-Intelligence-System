"""Tests for KYC data models."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import (
    AMLTypology,
    BusinessClient,
    ClientType,
    Confidence,
    DispositionStatus,
    EvidenceClass,
    EvidenceRecord,
    IndividualClient,
    InvestigationPlan,
    InvestigationResults,
    KYCOutput,
    OnboardingDecision,
    PEPLevel,
    RiskAssessment,
    RiskFactor,
    RiskLevel,
    SanctionsResult,
    SourceTier,
    TransactionMonitoringResult,
)


class TestEnums:
    def test_risk_levels(self):
        assert RiskLevel.LOW.value == "LOW"
        assert RiskLevel.CRITICAL.value == "CRITICAL"

    def test_disposition_statuses(self):
        assert DispositionStatus.CLEAR.value == "CLEAR"
        assert DispositionStatus.CONFIRMED_MATCH.value == "CONFIRMED_MATCH"

    def test_pep_levels(self):
        assert PEPLevel.NOT_PEP.value == "NOT_PEP"
        assert PEPLevel.FOREIGN_PEP.value == "FOREIGN_PEP"
        assert PEPLevel.DOMESTIC_PEP.value == "DOMESTIC_PEP"
        assert PEPLevel.HIO.value == "HIO"

    def test_onboarding_decisions(self):
        assert OnboardingDecision.APPROVE.value == "APPROVE"
        assert OnboardingDecision.DECLINE.value == "DECLINE"

    def test_evidence_class(self):
        assert EvidenceClass.VERIFIED.value == "V"
        assert EvidenceClass.SOURCED.value == "S"
        assert EvidenceClass.INFERRED.value == "I"
        assert EvidenceClass.UNKNOWN.value == "U"

    def test_confidence_preserved(self):
        assert Confidence.HIGH.value == "HIGH"
        assert Confidence.MEDIUM.value == "MEDIUM"
        assert Confidence.LOW.value == "LOW"

    def test_source_tier_preserved(self):
        assert SourceTier.TIER_0.value == "TIER_0"
        assert SourceTier.TIER_1.value == "TIER_1"
        assert SourceTier.TIER_2.value == "TIER_2"

    def test_source_tier_3_exists(self):
        """Feature 3: TIER_3 enum value exists."""
        assert SourceTier.TIER_3.value == "TIER_3"
        # Backward compat: existing tiers still work
        assert SourceTier("TIER_0") == SourceTier.TIER_0
        assert SourceTier("TIER_3") == SourceTier.TIER_3


class TestIndividualClient:
    def test_minimal(self):
        client = IndividualClient(full_name="Test User")
        assert client.client_type == ClientType.INDIVIDUAL
        assert client.full_name == "Test User"
        assert client.citizenship == "Canada"
        assert client.us_person is False
        assert client.pep_self_declaration is False

    def test_case1_load(self, individual_client_low):
        c = individual_client_low
        assert c.full_name == "Sarah Thompson"
        assert c.citizenship == "Canada"
        assert c.us_person is False
        assert c.employment.employer == "Toronto General Hospital"
        assert c.annual_income == 92000
        assert c.net_worth == 340000
        assert len(c.account_requests) == 1
        assert c.account_requests[0].account_type == "personal_investment"

    def test_case2_load(self, individual_client_pep):
        c = individual_client_pep
        assert c.full_name == "Maria Chen-Dubois"
        assert c.pep_self_declaration is True
        assert c.country_of_birth == "Hong Kong"
        assert "Hong Kong" in c.tax_residencies
        assert c.annual_income == 450000
        assert len(c.account_requests) == 2


class TestBusinessClient:
    def test_minimal(self):
        client = BusinessClient(legal_name="Test Corp")
        assert client.client_type == ClientType.BUSINESS
        assert client.legal_name == "Test Corp"
        assert client.us_nexus is False
        assert len(client.beneficial_owners) == 0

    def test_case3_load(self, business_client_critical):
        c = business_client_critical
        assert c.legal_name == "Northern Maple Trading Corp."
        assert c.us_nexus is True
        assert "Russia" in c.countries_of_operation
        assert len(c.beneficial_owners) == 3
        assert c.beneficial_owners[0].full_name == "Viktor Petrov"
        assert c.beneficial_owners[0].ownership_percentage == 51


class TestRiskAssessment:
    def test_defaults(self):
        ra = RiskAssessment()
        assert ra.total_score == 0
        assert ra.risk_level == RiskLevel.LOW
        assert ra.is_preliminary is True

    def test_with_factors(self):
        ra = RiskAssessment(
            total_score=45,
            risk_level=RiskLevel.HIGH,
            risk_factors=[
                RiskFactor(factor="PEP detected", points=25, category="pep", source="intake"),
            ],
        )
        assert ra.total_score == 45
        assert len(ra.risk_factors) == 1


class TestEvidenceRecord:
    def test_creation(self):
        er = EvidenceRecord(
            evidence_id="E001",
            source_type="agent",
            source_name="IndividualSanctions",
            entity_screened="Test Person",
            claim="No sanctions match found",
            evidence_level=EvidenceClass.VERIFIED,
            disposition=DispositionStatus.CLEAR,
        )
        assert er.evidence_id == "E001"
        assert er.evidence_level == EvidenceClass.VERIFIED
        assert er.confidence == Confidence.MEDIUM  # default


class TestAMLTypologyModel:
    def test_creation(self):
        t = AMLTypology(
            typology_name="Trade-Based ML",
            description="Over/under-invoicing",
            relevance="HIGH",
        )
        assert t.typology_name == "Trade-Based ML"
        assert t.relevance == "HIGH"
        assert t.indicators == []

    def test_defaults(self):
        t = AMLTypology(typology_name="Test", description="Test")
        assert t.relevance == "MEDIUM"
        assert t.monitoring_recommendation == ""


class TestTransactionMonitoringResult:
    def test_defaults(self):
        tmr = TransactionMonitoringResult(entity_screened="Test Corp")
        assert tmr.entity_screened == "Test Corp"
        assert tmr.industry_typologies == []
        assert tmr.geographic_typologies == []
        assert tmr.recommended_monitoring_frequency == "standard"

    def test_with_typologies(self):
        tmr = TransactionMonitoringResult(
            entity_screened="Test Corp",
            industry_typologies=[
                AMLTypology(typology_name="TBML", description="Trade-based ML", relevance="HIGH"),
            ],
            recommended_monitoring_frequency="enhanced",
        )
        assert len(tmr.industry_typologies) == 1
        assert tmr.recommended_monitoring_frequency == "enhanced"


class TestInvestigationResults:
    def test_defaults(self):
        ir = InvestigationResults()
        assert ir.individual_sanctions is None
        assert ir.pep_classification is None
        assert ir.ubo_screening == {}
        assert ir.transaction_monitoring is None
        assert ir.misrepresentation_detection is None
        assert ir.sar_risk_assessment is None

    def test_with_results(self):
        ir = InvestigationResults(
            individual_sanctions=SanctionsResult(
                entity_screened="Test",
                disposition=DispositionStatus.CLEAR,
            ),
        )
        assert ir.individual_sanctions.disposition == DispositionStatus.CLEAR

    def test_new_fields_coexist(self):
        """Verify new fields work alongside existing ones."""
        ir = InvestigationResults(
            misrepresentation_detection={"has_material_misrepresentation": False},
            sar_risk_assessment={"sar_risk_level": "LOW"},
            transaction_monitoring=TransactionMonitoringResult(
                entity_screened="Test",
            ),
        )
        assert ir.misrepresentation_detection["has_material_misrepresentation"] is False
        assert ir.sar_risk_assessment["sar_risk_level"] == "LOW"
        assert ir.transaction_monitoring.entity_screened == "Test"


class TestKYCOutput:
    def test_creation(self):
        output = KYCOutput(
            client_id="test_001",
            client_type=ClientType.INDIVIDUAL,
            client_data={"full_name": "Test"},
            intake_classification=InvestigationPlan(
                client_type=ClientType.INDIVIDUAL,
                client_id="test_001",
            ),
        )
        assert output.client_id == "test_001"
        assert output.final_decision is None
