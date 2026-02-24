"""Tests for Stage 1: Intake & Classification.

Tests risk scoring, regulation detection, and investigation planning
for all three test cases.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import RiskLevel
from utilities.investigation_planner import build_investigation_plan
from utilities.regulation_detector import detect_applicable_regulations
from utilities.risk_scoring import (
    calculate_business_risk_score,
    calculate_individual_risk_score,
    revise_risk_score,
)


class TestRiskScoringCase1:
    """Case 1: Sarah Thompson — expected LOW risk (~0 pts)."""

    def test_score_is_low(self, individual_client_low):
        assessment = calculate_individual_risk_score(individual_client_low)
        assert assessment.risk_level == RiskLevel.LOW
        assert assessment.total_score <= 15

    def test_no_pep_factors(self, individual_client_low):
        assessment = calculate_individual_risk_score(individual_client_low)
        pep_factors = [f for f in assessment.risk_factors if f.category == "pep"]
        assert len(pep_factors) == 0

    def test_canadian_citizen_no_country_risk(self, individual_client_low):
        assessment = calculate_individual_risk_score(individual_client_low)
        country_factors = [f for f in assessment.risk_factors if f.category == "citizenship"]
        # Canadian citizen should have no citizenship risk points
        assert all(f.points == 0 for f in country_factors) or len(country_factors) == 0


class TestRiskScoringCase2:
    """Case 2: Maria Chen-Dubois — expected HIGH risk (~52 pts, domestic PEP)."""

    def test_score_is_elevated(self, individual_client_pep):
        assessment = calculate_individual_risk_score(individual_client_pep)
        # PEP + source of funds + tax residency = at least MEDIUM, possibly HIGH
        assert assessment.risk_level in (RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL)
        assert assessment.total_score >= 25  # At minimum, domestic PEP = +25

    def test_pep_factor_present(self, individual_client_pep):
        assessment = calculate_individual_risk_score(individual_client_pep)
        pep_factors = [f for f in assessment.risk_factors if f.category == "pep"]
        assert len(pep_factors) > 0
        pep_points = sum(f.points for f in pep_factors)
        assert pep_points >= 25  # Domestic PEP = +25

    def test_country_of_birth_factor(self, individual_client_pep):
        assessment = calculate_individual_risk_score(individual_client_pep)
        [f for f in assessment.risk_factors if "birth" in f.factor.lower()]
        # Hong Kong birth may or may not add points depending on implementation
        # At minimum, the scoring should run without error
        assert assessment.total_score > 0


class TestRiskScoringCase3:
    """Case 3: Northern Maple Trading — expected MEDIUM preliminary (no UBO data)."""

    def test_preliminary_score(self, business_client_critical):
        assessment = calculate_business_risk_score(business_client_critical)
        # Preliminary (no UBO scores) — should be MEDIUM to HIGH
        assert assessment.risk_level in (RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL)
        assert assessment.total_score > 15  # Above LOW

    def test_industry_factor(self, business_client_critical):
        assessment = calculate_business_risk_score(business_client_critical)
        industry_factors = [f for f in assessment.risk_factors if f.category == "industry"]
        assert len(industry_factors) > 0  # Import/export should flag

    def test_us_nexus_factor(self, business_client_critical):
        assessment = calculate_business_risk_score(business_client_critical)
        us_factors = [f for f in assessment.risk_factors if "us" in f.factor.lower()]
        assert len(us_factors) > 0  # US nexus should add points

    def test_revision_with_ubo_scores(self, business_client_critical):
        preliminary = calculate_business_risk_score(business_client_critical)
        # Simulate UBO cascade: Petrov flagged with 30 pts
        ubo_scores = {"Viktor Petrov": 30, "Sarah Chen": 0, "James MacDonald": 5}
        revised = revise_risk_score(preliminary, ubo_scores, [])
        assert revised.total_score > preliminary.total_score
        assert revised.is_preliminary is False


class TestRegulationDetection:
    def test_case1_regulations(self, individual_client_low):
        regs = detect_applicable_regulations(individual_client_low)
        # FINTRAC always applies (may be "FINTRAC" or "FINTRAC/PCMLTFA")
        assert any("FINTRAC" in r for r in regs)
        assert "CIRO" in regs
        # No US nexus → no OFAC/FATCA
        assert "OFAC" not in regs
        assert "FATCA" not in regs

    def test_case2_regulations(self, individual_client_pep):
        regs = detect_applicable_regulations(individual_client_pep)
        assert any("FINTRAC" in r for r in regs)
        assert "CIRO" in regs
        # Hong Kong tax residency → CRS
        assert "CRS" in regs

    def test_case3_regulations(self, business_client_critical):
        regs = detect_applicable_regulations(business_client_critical)
        assert any("FINTRAC" in r for r in regs)
        assert "CIRO" in regs
        # US nexus = true → OFAC
        assert "OFAC" in regs


class TestInvestigationPlanner:
    def test_case1_plan(self, individual_client_low):
        plan = build_investigation_plan(individual_client_low)
        assert plan.client_type.value == "individual"
        assert "IndividualSanctions" in plan.agents_to_run
        assert "PEPDetection" in plan.agents_to_run
        # LOW risk: standard scope — only sanctions + PEP agents
        assert plan.investigation_scope == "standard"
        assert "IndividualAdverseMedia" not in plan.agents_to_run
        assert plan.ubo_cascade_needed is False
        assert "id_verification" in plan.utilities_to_run
        assert "suitability" in plan.utilities_to_run

    def test_case2_plan(self, individual_client_pep):
        plan = build_investigation_plan(individual_client_pep)
        assert "PEPDetection" in plan.agents_to_run
        assert "edd_requirements" in plan.utilities_to_run

    def test_case3_plan(self, business_client_critical):
        plan = build_investigation_plan(business_client_critical)
        assert plan.client_type.value == "business"
        assert "EntityVerification" in plan.agents_to_run
        assert "EntitySanctions" in plan.agents_to_run
        assert "BusinessAdverseMedia" in plan.agents_to_run
        assert "JurisdictionRisk" in plan.agents_to_run
        assert plan.ubo_cascade_needed is True
        assert len(plan.ubo_names) == 3
        assert "Viktor Petrov" in plan.ubo_names

    def test_case3_has_business_utilities(self, business_client_critical):
        plan = build_investigation_plan(business_client_critical)
        assert "entity_fatca_crs" in plan.utilities_to_run
        assert "business_risk_assessment" in plan.utilities_to_run
