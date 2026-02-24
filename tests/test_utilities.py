"""Tests for deterministic utility functions.

Each utility is pure Python with no API calls.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import (
    AMLTypology,
    BusinessClient,
    IndividualClient,
    InvestigationResults,
    RiskAssessment,
    RiskLevel,
    TransactionMonitoringResult,
)


class TestIdVerification:
    def test_individual_verification(self, individual_client_low):
        from utilities.id_verification import assess_id_verification
        result = assess_id_verification(individual_client_low)
        assert isinstance(result, dict)
        assert "method" in result or "requirements" in result
        assert "status" in result

    def test_business_verification(self, business_client_critical):
        from utilities.id_verification import assess_id_verification
        result = assess_id_verification(business_client_critical)
        assert isinstance(result, dict)
        assert "requirements" in result
        # Business should require incorporation documents
        reqs = result.get("requirements", [])
        assert len(reqs) > 0


class TestSuitability:
    def test_case1_suitability(self, individual_client_low):
        from utilities.suitability import assess_suitability
        result = assess_suitability(individual_client_low)
        assert isinstance(result, dict)
        assert "suitable" in result
        # Sarah Thompson should be suitable — stable income, reasonable investment
        assert result["suitable"] is True

    def test_case2_suitability(self, individual_client_pep):
        from utilities.suitability import assess_suitability
        result = assess_suitability(individual_client_pep)
        assert isinstance(result, dict)
        assert "suitable" in result

    def test_business_suitability(self, business_client_critical):
        from utilities.suitability import assess_suitability
        result = assess_suitability(business_client_critical)
        assert isinstance(result, dict)


class TestIndividualFATCACRS:
    def test_case1_no_fatca(self, individual_client_low):
        from utilities.individual_fatca_crs import classify_individual_fatca_crs
        result = classify_individual_fatca_crs(individual_client_low)
        assert isinstance(result, dict)
        assert "fatca" in result
        # Canadian, non-US person → no FATCA reporting
        fatca = result["fatca"]
        assert fatca.get("us_person") is False or fatca.get("reporting_required") is False

    def test_case2_crs_triggered(self, individual_client_pep):
        from utilities.individual_fatca_crs import classify_individual_fatca_crs
        result = classify_individual_fatca_crs(individual_client_pep)
        assert isinstance(result, dict)
        assert "crs" in result
        # Hong Kong tax residency → CRS reporting
        crs = result["crs"]
        crs_jurisdictions = crs.get("reportable_jurisdictions", [])
        assert len(crs_jurisdictions) > 0 or crs.get("reporting_required") is True


class TestEntityFATCACRS:
    def test_case3_entity_classification(self, business_client_critical):
        from utilities.entity_fatca_crs import classify_entity_fatca_crs
        result = classify_entity_fatca_crs(business_client_critical)
        assert isinstance(result, dict)
        assert "entity_classification" in result
        # Trading corp should be Active NFFE or similar
        classification = result["entity_classification"]
        assert classification is not None


class TestEDDRequirements:
    def test_case1_no_edd(self, individual_client_low):
        from utilities.edd_requirements import assess_edd_requirements
        risk = RiskAssessment(total_score=5, risk_level=RiskLevel.LOW)
        result = assess_edd_requirements(individual_client_low, risk)
        assert isinstance(result, dict)
        assert "edd_required" in result
        # LOW risk, no flags → likely no EDD
        assert result["edd_required"] is False

    def test_case2_edd_required(self, individual_client_pep):
        from utilities.edd_requirements import assess_edd_requirements
        risk = RiskAssessment(total_score=52, risk_level=RiskLevel.HIGH)
        result = assess_edd_requirements(individual_client_pep, risk)
        assert isinstance(result, dict)
        assert result["edd_required"] is True
        assert len(result.get("triggers", [])) > 0
        assert len(result.get("measures", [])) > 0

    def test_case3_edd_required(self, business_client_critical):
        from utilities.edd_requirements import assess_edd_requirements
        risk = RiskAssessment(total_score=45, risk_level=RiskLevel.HIGH)
        result = assess_edd_requirements(business_client_critical, risk)
        assert isinstance(result, dict)
        assert result["edd_required"] is True


class TestComplianceActions:
    def test_case1_minimal_actions(self, individual_client_low):
        from utilities.compliance_actions import determine_compliance_actions
        risk = RiskAssessment(total_score=5, risk_level=RiskLevel.LOW)
        result = determine_compliance_actions(individual_client_low, risk)
        assert isinstance(result, dict)
        assert "reports" in result
        assert "actions" in result

    def test_case2_actions(self, individual_client_pep):
        from utilities.compliance_actions import determine_compliance_actions
        risk = RiskAssessment(total_score=52, risk_level=RiskLevel.HIGH)
        result = determine_compliance_actions(individual_client_pep, risk)
        assert isinstance(result, dict)
        # CRS reporting for Hong Kong tax residency
        reports = result.get("reports", [])
        # PEP with Hong Kong tax residency should trigger CRS reporting at minimum
        assert isinstance(reports, list)

    def test_case3_actions(self, business_client_critical):
        from utilities.compliance_actions import determine_compliance_actions
        risk = RiskAssessment(total_score=45, risk_level=RiskLevel.HIGH)
        result = determine_compliance_actions(business_client_critical, risk)
        assert isinstance(result, dict)
        assert "escalations" in result


class TestBusinessRiskAssessment:
    def test_case3_risk_factors(self, business_client_critical):
        from utilities.business_risk_assessment import assess_business_risk_factors
        result = assess_business_risk_factors(business_client_critical)
        assert isinstance(result, dict)
        assert "risk_factors" in result
        assert "ownership_analysis" in result
        assert "operational_analysis" in result
        assert "overall_narrative" in result
        # Should identify high-risk factors
        assert len(result["risk_factors"]) > 0

    def test_narrative_not_empty(self, business_client_critical):
        from utilities.business_risk_assessment import assess_business_risk_factors
        result = assess_business_risk_factors(business_client_critical)
        assert len(result["overall_narrative"]) > 0


class TestDocumentRequirements:
    def test_individual_requirements(self, individual_client_low):
        from utilities.document_requirements import consolidate_document_requirements
        from utilities.investigation_planner import build_investigation_plan
        plan = build_investigation_plan(individual_client_low)
        # Build a minimal investigation with id_verification
        investigation = InvestigationResults()
        investigation.id_verification = {
            "method": "dual_process",
            "status": "pending",
            "requirements": ["Government-issued photo ID", "Proof of address"],
        }
        result = consolidate_document_requirements(individual_client_low, plan, investigation)
        assert isinstance(result, dict)
        assert "requirements" in result
        assert isinstance(result["requirements"], list)
        assert len(result["requirements"]) > 0
        # Each requirement should have document and regulatory_basis keys
        for req in result["requirements"]:
            assert "document" in req
            assert "regulatory_basis" in req

    def test_business_requirements(self, business_client_critical):
        from utilities.document_requirements import consolidate_document_requirements
        from utilities.investigation_planner import build_investigation_plan
        plan = build_investigation_plan(business_client_critical)
        investigation = InvestigationResults()
        investigation.id_verification = {
            "method": "corporate_registry",
            "status": "pending",
            "requirements": [],
        }
        result = consolidate_document_requirements(business_client_critical, plan, investigation)
        assert isinstance(result, dict)
        assert "requirements" in result
        # Business should have entity verification docs
        docs = [r["document"].lower() for r in result["requirements"]]
        assert any("incorporation" in d for d in docs)
        assert "total_required" in result
        assert "total_outstanding" in result


class TestComplianceActionsDateCalc:
    def test_computed_deadline_present(self, individual_client_low):
        from utilities.compliance_actions import determine_compliance_actions
        risk = RiskAssessment(total_score=5, risk_level=RiskLevel.LOW)
        result = determine_compliance_actions(individual_client_low, risk)
        timelines = result.get("timelines", {})
        # risk_review should have computed_deadline
        assert "risk_review" in timelines
        assert "computed_deadline" in timelines["risk_review"]
        # Verify it's a valid date string
        deadline = timelines["risk_review"]["computed_deadline"]
        assert len(deadline) == 10  # YYYY-MM-DD format

    def test_report_deadlines_computed(self, individual_client_pep):
        from utilities.compliance_actions import determine_compliance_actions
        risk = RiskAssessment(total_score=52, risk_level=RiskLevel.HIGH)
        result = determine_compliance_actions(individual_client_pep, risk)
        timelines = result.get("timelines", {})
        # Any report timeline entry should have computed_deadline
        for key, tl in timelines.items():
            if key in ("STR", "TPR", "FATCA", "CRS", "LCTR"):
                assert "computed_deadline" in tl, f"Missing computed_deadline for {key}"


class TestEDDMonitoringSchedule:
    def test_monitoring_schedule_present(self, individual_client_low):
        from utilities.edd_requirements import assess_edd_requirements
        risk = RiskAssessment(total_score=5, risk_level=RiskLevel.LOW)
        result = assess_edd_requirements(individual_client_low, risk)
        assert "monitoring_schedule" in result
        schedule = result["monitoring_schedule"]
        assert "frequency" in schedule
        assert "next_review_date" in schedule
        assert "review_interval_days" in schedule
        # Verify next_review_date is a valid date string
        assert len(schedule["next_review_date"]) == 10

    def test_high_risk_monitoring_frequency(self, individual_client_pep):
        from utilities.edd_requirements import assess_edd_requirements
        risk = RiskAssessment(total_score=52, risk_level=RiskLevel.HIGH)
        result = assess_edd_requirements(individual_client_pep, risk)
        schedule = result["monitoring_schedule"]
        # HIGH risk should be quarterly (90 days)
        assert schedule["frequency"] == "quarterly"
        assert schedule["review_interval_days"] == 90


class TestEntityClassificationWordBoundary:
    """Verify word-boundary matching in entity FATCA/CRS classification (Bug 8 fix)."""

    def _make_client(self, industry="", nature="", biz_type=""):
        """Build a minimal BusinessClient with the given fields."""
        return BusinessClient(
            legal_name="Test Corp",
            business_type=biz_type or "corporation",
            industry=industry,
            nature_of_business=nature,
            incorporation_jurisdiction="Canada",
            annual_revenue=1_000_000,
        )

    def test_bank_matches_fi(self):
        from utilities.entity_fatca_crs import _classify_entity
        client = self._make_client(industry="commercial bank")
        assert _classify_entity(client) == "financial_institution"

    def test_embankment_not_fi(self):
        """'embankment' should NOT match the 'bank' keyword."""
        from utilities.entity_fatca_crs import _classify_entity
        client = self._make_client(industry="embankment construction")
        assert _classify_entity(client) != "financial_institution"

    def test_holding_company_passive(self):
        from utilities.entity_fatca_crs import _classify_entity
        client = self._make_client(nature="holding company")
        assert _classify_entity(client) == "passive_nffe"

    def test_withholding_not_passive(self):
        """'withholding' should NOT match 'holding company'."""
        from utilities.entity_fatca_crs import _classify_entity
        client = self._make_client(nature="withholding tax services")
        assert _classify_entity(client) != "passive_nffe"

    def test_trust_company_matches_fi(self):
        from utilities.entity_fatca_crs import _classify_entity
        client = self._make_client(industry="trust company")
        assert _classify_entity(client) == "financial_institution"

    def test_active_nffe_manufacturing(self):
        from utilities.entity_fatca_crs import _classify_entity
        client = self._make_client(industry="manufacturing")
        assert _classify_entity(client) == "active_nffe"


class TestEDDThresholdsFromConstants:
    """Verify EDD requirements use centralized constants."""

    def test_edd_threshold_matches_constant(self):
        from constants import EDD_RISK_SCORE_THRESHOLD
        assert EDD_RISK_SCORE_THRESHOLD == 36

    def test_edd_triggered_at_threshold(self, individual_client_low):
        """Score exactly at threshold should trigger EDD."""
        from constants import EDD_RISK_SCORE_THRESHOLD
        from utilities.edd_requirements import assess_edd_requirements
        risk = RiskAssessment(
            total_score=EDD_RISK_SCORE_THRESHOLD,
            risk_level=RiskLevel.HIGH,
        )
        result = assess_edd_requirements(individual_client_low, risk)
        assert result["edd_required"] is True

    def test_edd_not_triggered_below_threshold(self, individual_client_low):
        """Score below threshold should not trigger EDD (without other triggers)."""
        from constants import EDD_RISK_SCORE_THRESHOLD
        from utilities.edd_requirements import assess_edd_requirements
        risk = RiskAssessment(
            total_score=EDD_RISK_SCORE_THRESHOLD - 1,
            risk_level=RiskLevel.MEDIUM,
        )
        result = assess_edd_requirements(individual_client_low, risk)
        assert result["edd_required"] is False


class TestReferenceData:
    def test_fatf_lists_populated(self):
        from utilities.reference_data import FATF_BLACK_LIST, FATF_GREY_LIST
        assert len(FATF_GREY_LIST) > 0
        assert len(FATF_BLACK_LIST) > 0

    def test_high_risk_industries(self):
        from utilities.reference_data import HIGH_RISK_INDUSTRIES
        assert len(HIGH_RISK_INDUSTRIES) > 0

    def test_offshore_jurisdictions(self):
        from utilities.reference_data import OFFSHORE_JURISDICTIONS
        assert len(OFFSHORE_JURISDICTIONS) > 0

    def test_source_of_funds_risk(self):
        from utilities.reference_data import SOURCE_OF_FUNDS_RISK
        assert "employment_income" in SOURCE_OF_FUNDS_RISK
        assert SOURCE_OF_FUNDS_RISK["employment_income"] == 0


class TestComplianceActionsEnhanced:
    """Tests for compliance actions with misrepresentation and SAR risk integration."""

    def test_misrepresentation_str_trigger(self):
        """Critical misrepresentation should trigger STR consideration."""
        from utilities.compliance_actions import determine_compliance_actions
        client = IndividualClient(full_name="Test Person")
        risk = RiskAssessment(total_score=30, risk_level=RiskLevel.HIGH)
        investigation = InvestigationResults(
            misrepresentation_detection={
                "misrepresentations": [
                    {"field": "pep", "declared_value": "False",
                     "found_value": "FOREIGN_PEP", "severity": "CRITICAL"},
                ],
                "has_material_misrepresentation": True,
                "str_consideration_triggered": True,
            },
        )
        result = determine_compliance_actions(client, risk, investigation)
        str_reports = [r for r in result["reports"] if r["type"] == "STR"]
        assert len(str_reports) >= 1
        assert any("misrepresentation" in r["trigger"].lower() for r in str_reports)

    def test_sar_risk_str_trigger(self):
        """HIGH SAR risk should trigger STR consideration."""
        from utilities.compliance_actions import determine_compliance_actions
        client = IndividualClient(full_name="Test Person")
        risk = RiskAssessment(total_score=30, risk_level=RiskLevel.HIGH)
        investigation = InvestigationResults(
            sar_risk_assessment={
                "sar_risk_level": "HIGH",
                "triggers": ["Sanctions match", "Adverse media"],
            },
        )
        result = determine_compliance_actions(client, risk, investigation)
        str_reports = [r for r in result["reports"] if r["type"] == "STR"]
        assert len(str_reports) >= 1
        assert any("sar" in r["trigger"].lower() for r in str_reports)

    def test_misrepresentation_escalation(self):
        """Material misrepresentation should create escalation."""
        from utilities.compliance_actions import determine_compliance_actions
        client = IndividualClient(full_name="Test Person")
        risk = RiskAssessment(total_score=30, risk_level=RiskLevel.HIGH)
        investigation = InvestigationResults(
            misrepresentation_detection={
                "misrepresentations": [
                    {"field": "pep", "declared_value": "False",
                     "found_value": "FOREIGN_PEP", "severity": "CRITICAL"},
                ],
                "has_material_misrepresentation": True,
                "str_consideration_triggered": True,
            },
        )
        result = determine_compliance_actions(client, risk, investigation)
        assert any("misrepresentation" in e.lower() for e in result["escalations"])

    def test_transaction_monitoring_actions(self):
        """Transaction monitoring findings should generate monitoring actions."""
        from utilities.compliance_actions import determine_compliance_actions
        client = BusinessClient(legal_name="Test Corp")
        risk = RiskAssessment(total_score=30, risk_level=RiskLevel.HIGH)
        investigation = InvestigationResults(
            transaction_monitoring=TransactionMonitoringResult(
                entity_screened="Test Corp",
                industry_typologies=[
                    AMLTypology(
                        typology_name="Trade-Based ML",
                        description="Import/export ML",
                        relevance="HIGH",
                    ),
                ],
                recommended_monitoring_frequency="enhanced",
            ),
        )
        result = determine_compliance_actions(client, risk, investigation)
        monitoring_actions = [a for a in result["actions"] if "monitoring" in a.lower() and "enhanced" in a.lower()]
        assert len(monitoring_actions) >= 1


class TestReviewIntelligenceEnhanced:
    """Tests for review intelligence with new feature integration."""

    def test_misrepresentation_discussion_point(self):
        """Misrepresentation evidence should generate discussion point."""
        from models import ClientType, InvestigationPlan, KYCSynthesisOutput
        from utilities.review_intelligence import compute_review_intelligence
        evidence_store = [
            {
                "evidence_id": "misrep_test",
                "source_type": "utility",
                "source_name": "misrepresentation_detection",
                "entity_screened": "Test",
                "claim": "Misrepresentation detection: 2 discrepancy(ies) found, 1 material/critical.",
                "evidence_level": "S",
                "disposition": "PENDING_REVIEW",
                "confidence": "HIGH",
            },
        ]
        synthesis = KYCSynthesisOutput()
        plan = InvestigationPlan(client_type=ClientType.INDIVIDUAL, client_id="test")
        investigation = InvestigationResults()
        result = compute_review_intelligence(
            evidence_store, synthesis, plan, investigation,
        )
        misrep_points = [
            dp for dp in result.discussion_points
            if "misrepresentation" in dp.title.lower()
        ]
        assert len(misrep_points) >= 1

    def test_sar_risk_discussion_point(self):
        """SAR risk evidence should generate discussion point."""
        from models import ClientType, InvestigationPlan, KYCSynthesisOutput
        from utilities.review_intelligence import compute_review_intelligence
        evidence_store = [
            {
                "evidence_id": "sar_test",
                "source_type": "utility",
                "source_name": "sar_risk_assessment",
                "entity_screened": "Test",
                "claim": "SAR risk assessment: HIGH (score 45, 3 trigger(s))",
                "evidence_level": "S",
                "disposition": "PENDING_REVIEW",
                "confidence": "HIGH",
                "supporting_data": [
                    {"sar_risk_level": "HIGH"},
                ],
            },
        ]
        synthesis = KYCSynthesisOutput()
        plan = InvestigationPlan(client_type=ClientType.INDIVIDUAL, client_id="test")
        investigation = InvestigationResults()
        result = compute_review_intelligence(
            evidence_store, synthesis, plan, investigation,
        )
        sar_points = [
            dp for dp in result.discussion_points
            if "sar" in dp.title.lower()
        ]
        assert len(sar_points) >= 1

    def test_regulatory_mapping_misrepresentation(self):
        """Misrepresentation evidence should get regulatory tags."""
        from models import ClientType, InvestigationPlan, KYCSynthesisOutput
        from utilities.review_intelligence import compute_review_intelligence
        evidence_store = [
            {
                "evidence_id": "misrep_test",
                "source_type": "utility",
                "source_name": "misrepresentation_detection",
                "entity_screened": "Test",
                "claim": "Critical misrepresentation detected",
                "evidence_level": "S",
                "disposition": "PENDING_REVIEW",
                "confidence": "HIGH",
            },
        ]
        synthesis = KYCSynthesisOutput()
        plan = InvestigationPlan(client_type=ClientType.INDIVIDUAL, client_id="test")
        investigation = InvestigationResults()
        result = compute_review_intelligence(
            evidence_store, synthesis, plan, investigation,
        )
        misrep_mappings = [
            m for m in result.regulatory_mappings
            if m.source_name == "misrepresentation_detection"
        ]
        assert len(misrep_mappings) >= 1
        # Should have FINTRAC tag
        tags = misrep_mappings[0].regulatory_tags
        assert any("FINTRAC" in t.regulation for t in tags)
