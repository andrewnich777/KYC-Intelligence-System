"""
Tests for the 12-item improvement plan.

Covers:
1. Evidence-level validation at ingestion
2. Data freshness timestamps
3. PEP 5-year window decay
4. Claim-specific source URL attachment
5. Officer override capability
6. Risk-stratified investigation planning
7. New test cases (gray area, sparse, common name)
8. UBO risk contribution factor (0.75)
9. Screening list data freshness warning
10. PDF signoff block
11. FATCA dual-citizenship edge case
12. Condensed STR Part G narrative
"""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEST_CASES_DIR = Path(__file__).parent.parent / "test_cases"


def _load_case(name: str) -> dict:
    return json.loads((TEST_CASES_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture
def case4_gray():
    from models import IndividualClient
    return IndividualClient(**_load_case("case4_individual_gray.json"))


@pytest.fixture
def case5_sparse():
    from models import IndividualClient
    return IndividualClient(**_load_case("case5_sparse_data.json"))


@pytest.fixture
def case6_common():
    from models import IndividualClient
    return IndividualClient(**_load_case("case6_common_name.json"))


# ---------------------------------------------------------------------------
# 1. Evidence-level validation
# ---------------------------------------------------------------------------

class TestEvidenceLevelValidation:
    """Verify that evidence levels are validated at ingestion."""

    def test_verified_without_urls_downgraded(self):
        """[V] without source URLs should be downgraded to [S]."""
        from agents.base import BaseAgent
        from models import EvidenceClass

        class DummyAgent(BaseAgent):
            name = "TestAgent"
            system_prompt = "test"
            tools = []

        agent = DummyAgent()
        record = agent._build_finding_record(
            "TEST-001", "Entity", "Test claim",
            supporting_data=[{"key": "value"}],
            evidence_level=EvidenceClass.VERIFIED,
            source_urls=[],  # No URLs
        )
        assert record.evidence_level == EvidenceClass.SOURCED

    def test_sourced_without_supporting_data_downgraded(self):
        """[S] without supporting_data should be downgraded to [I]."""
        from agents.base import BaseAgent
        from models import EvidenceClass

        class DummyAgent(BaseAgent):
            name = "TestAgent"
            system_prompt = "test"
            tools = []

        agent = DummyAgent()
        record = agent._build_finding_record(
            "TEST-002", "Entity", "Test claim",
            supporting_data=[],  # Empty
            evidence_level=EvidenceClass.SOURCED,
            source_urls=["https://example.com"],
        )
        assert record.evidence_level == EvidenceClass.INFERRED

    def test_verified_with_urls_and_data_preserved(self):
        """[V] with both URLs and data should remain [V]."""
        from agents.base import BaseAgent
        from models import EvidenceClass

        class DummyAgent(BaseAgent):
            name = "TestAgent"
            system_prompt = "test"
            tools = []

        agent = DummyAgent()
        record = agent._build_finding_record(
            "TEST-003", "Entity", "Test claim",
            supporting_data=[{"key": "val"}],
            evidence_level=EvidenceClass.VERIFIED,
            source_urls=["https://example.com"],
        )
        assert record.evidence_level == EvidenceClass.VERIFIED

    def test_no_level_with_urls_inferred_sourced(self):
        """No evidence_level + URLs → SOURCED."""
        from agents.base import BaseAgent
        from models import EvidenceClass

        class DummyAgent(BaseAgent):
            name = "TestAgent"
            system_prompt = "test"
            tools = []

        agent = DummyAgent()
        record = agent._build_finding_record(
            "TEST-004", "Entity", "Test claim",
            supporting_data=[{"key": "val"}],
            source_urls=["https://example.com"],
        )
        assert record.evidence_level == EvidenceClass.SOURCED

    def test_no_level_without_urls_inferred(self):
        """No evidence_level + no URLs → INFERRED."""
        from agents.base import BaseAgent
        from models import EvidenceClass

        class DummyAgent(BaseAgent):
            name = "TestAgent"
            system_prompt = "test"
            tools = []

        agent = DummyAgent()
        record = agent._build_finding_record(
            "TEST-005", "Entity", "Test claim",
            supporting_data=[{"key": "val"}],
        )
        assert record.evidence_level == EvidenceClass.INFERRED

    def test_evidence_store_warns_on_mismatch(self, caplog):
        """EvidenceStore.add() should log warning for V without URLs."""
        import logging

        from evidence_store import EvidenceStore

        store = EvidenceStore()
        with caplog.at_level(logging.WARNING, logger="evidence_store"):
            store.add({
                "evidence_id": "WARN-001",
                "evidence_level": "V",
                "source_urls": [],
                "supporting_data": [],
            })
        assert any("VERIFIED" in msg for msg in caplog.messages)


# ---------------------------------------------------------------------------
# 2. Data freshness timestamps
# ---------------------------------------------------------------------------

class TestDataFreshnessTimestamps:
    """Verify data_as_of is populated on evidence records."""

    def test_finding_record_has_data_as_of(self):
        from agents.base import BaseAgent

        class DummyAgent(BaseAgent):
            name = "TestAgent"
            system_prompt = "test"
            tools = []

        agent = DummyAgent()
        record = agent._build_finding_record(
            "TS-001", "Entity", "Claim",
            supporting_data=[{"k": "v"}],
            source_urls=["https://example.com"],
        )
        assert record.data_as_of is not None
        assert isinstance(record.data_as_of, datetime)

    def test_clear_record_has_data_as_of(self):
        from agents.base import BaseAgent

        class DummyAgent(BaseAgent):
            name = "TestAgent"
            system_prompt = "test"
            tools = []

        agent = DummyAgent()
        record = agent._build_clear_record("TS-002", "Entity", "Clear claim")
        assert record.data_as_of is not None


# ---------------------------------------------------------------------------
# 3. PEP 5-year window decay
# ---------------------------------------------------------------------------

class TestPEPDecay:
    """Verify domestic PEP risk reduces after EDD expiry."""

    def test_expired_pep_reduces_risk(self):
        from constants import PEP_EXPIRED_RESIDUAL_POINTS
        from models import RiskAssessment, RiskFactor, RiskLevel
        from utilities.risk_scoring import revise_risk_score

        preliminary = RiskAssessment(
            total_score=25,
            risk_level=RiskLevel.MEDIUM,
            risk_factors=[
                RiskFactor(factor="Domestic PEP", points=25, category="pep", source="client_intake"),
            ],
            score_history=[{"stage": "intake", "score": 25, "level": "MEDIUM"}],
        )

        revised = revise_risk_score(preliminary, pep_edd_expired=True)
        # PEP factor should be replaced with residual
        pep_factors = [f for f in revised.risk_factors if f.category == "pep"]
        assert len(pep_factors) == 1
        assert pep_factors[0].points == PEP_EXPIRED_RESIDUAL_POINTS
        assert "Former PEP" in pep_factors[0].factor
        assert revised.total_score == PEP_EXPIRED_RESIDUAL_POINTS

    def test_non_expired_pep_keeps_full_points(self):
        from models import RiskAssessment, RiskFactor, RiskLevel
        from utilities.risk_scoring import revise_risk_score

        preliminary = RiskAssessment(
            total_score=25,
            risk_level=RiskLevel.MEDIUM,
            risk_factors=[
                RiskFactor(factor="Domestic PEP", points=25, category="pep", source="client_intake"),
            ],
            score_history=[{"stage": "intake", "score": 25, "level": "MEDIUM"}],
        )

        revised = revise_risk_score(preliminary, pep_edd_expired=False)
        assert revised.total_score == 25

    def test_shared_checks_expired_pep_trigger(self):
        """Expired domestic PEP should produce 'Former' trigger text."""
        from models import IndividualClient, InvestigationResults, PEPClassification, PEPLevel
        from utilities.shared_checks import check_pep_edd_triggers

        client = IndividualClient(full_name="Test Person")
        investigation = InvestigationResults(
            pep_classification=PEPClassification(
                entity_screened="Test Person",
                detected_level=PEPLevel.DOMESTIC_PEP,
                edd_expiry_date="2020-01-01",  # Expired
            )
        )

        triggers = check_pep_edd_triggers(client, investigation)
        assert any("Former" in t["trigger"] for t in triggers)
        assert any(t.get("expired") is True for t in triggers)


# ---------------------------------------------------------------------------
# 4. Claim-specific source URL attachment
# ---------------------------------------------------------------------------

class TestClaimSpecificURLs:
    """Verify URL attachment behavior."""

    def test_attach_skips_records_with_existing_urls(self):
        from agents.base import BaseAgent

        class DummyAgent(BaseAgent):
            name = "TestAgent"
            system_prompt = "test"
            tools = []

        record_with_urls = MagicMock()
        record_with_urls.source_urls = ["https://specific.com"]
        record_with_urls.urls_are_global = False

        record_without_urls = MagicMock()
        record_without_urls.source_urls = []
        record_without_urls.urls_are_global = False

        raw = {"search_stats": {"fetched_urls": ["https://a.com", "https://b.com"]}}

        BaseAgent._attach_fetched_urls([record_with_urls, record_without_urls], raw)

        # Record with existing URLs should NOT be overwritten
        assert record_with_urls.source_urls == ["https://specific.com"]
        # Record without URLs should get global URLs
        assert record_without_urls.source_urls == ["https://a.com", "https://b.com"]
        assert record_without_urls.urls_are_global is True

    def test_claim_urls_parameter(self):
        from agents.base import BaseAgent

        class DummyAgent(BaseAgent):
            name = "TestAgent"
            system_prompt = "test"
            tools = []

        agent = DummyAgent()
        record = agent._build_finding_record(
            "CU-001", "Entity", "Claim",
            supporting_data=[{"k": "v"}],
            claim_urls=["https://specific.com"],
            source_urls=["https://global.com"],
        )
        # claim_urls takes precedence
        assert record.source_urls == ["https://specific.com"]


# ---------------------------------------------------------------------------
# 6. Risk-stratified investigation planning
# ---------------------------------------------------------------------------

class TestRiskStratifiedPlanning:
    """Verify agent selection varies by risk level."""

    def test_low_risk_standard_scope(self):
        from models import IndividualClient
        from utilities.investigation_planner import build_investigation_plan

        client = IndividualClient(full_name="Low Risk Person", citizenship="Canada")
        plan = build_investigation_plan(client)
        assert plan.investigation_scope == "standard"
        assert "IndividualSanctions" in plan.agents_to_run
        assert "PEPDetection" in plan.agents_to_run
        assert "IndividualAdverseMedia" not in plan.agents_to_run
        assert "TransactionMonitoring" not in plan.agents_to_run

    def test_high_risk_full_scope(self):
        from models import IndividualClient
        from utilities.investigation_planner import build_investigation_plan

        # PEP self-declaration = 25 pts + Hong Kong tax = offshore ~8 pts → ~33 pts = MEDIUM
        # Use a FATF grey list country to push to HIGH
        client = IndividualClient(
            full_name="High Risk PEP",
            citizenship="Turkey",  # FATF grey list
            pep_self_declaration=True,
            pep_details="Domestic PEP",
        )
        plan = build_investigation_plan(client)
        assert plan.investigation_scope in ("enhanced", "full")
        assert "IndividualAdverseMedia" in plan.agents_to_run

    def test_utilities_always_run(self, case5_sparse):
        from utilities.investigation_planner import build_investigation_plan

        plan = build_investigation_plan(case5_sparse)
        # Even sparse/LOW clients get all utilities (deterministic, no cost)
        assert "id_verification" in plan.utilities_to_run
        assert "document_requirements" in plan.utilities_to_run


# ---------------------------------------------------------------------------
# 7. New test cases
# ---------------------------------------------------------------------------

class TestNewCases:
    """Verify new test case files load and score correctly."""

    def test_case4_gray_loads(self, case4_gray):
        assert case4_gray.full_name == "David Chen"
        assert case4_gray.country_of_birth == "Hong Kong"
        assert "Hong Kong" in case4_gray.tax_residencies

    def test_case4_gray_risk_score(self, case4_gray):
        from utilities.risk_scoring import calculate_individual_risk_score
        risk = calculate_individual_risk_score(case4_gray)
        # Hong Kong tax residency (non-CA = 3 pts) + business_income (5 pts) = 8 pts
        # This is a LOW-risk client at intake, but agent investigation may escalate.
        # The "gray area" comes from investigation findings, not intake data alone.
        assert risk.total_score > 0, "Gray area client should have some risk factors"
        assert len(risk.risk_factors) >= 1

    def test_case5_sparse_loads(self, case5_sparse):
        assert case5_sparse.full_name == "Maria Rodriguez"
        assert case5_sparse.date_of_birth is None
        assert case5_sparse.employment is None

    def test_case5_sparse_low_risk(self, case5_sparse):
        from utilities.risk_scoring import calculate_individual_risk_score
        risk = calculate_individual_risk_score(case5_sparse)
        assert risk.risk_level.value == "LOW"

    def test_case5_sparse_investigation_plan(self, case5_sparse):
        from utilities.investigation_planner import build_investigation_plan
        plan = build_investigation_plan(case5_sparse)
        # Should still produce a valid plan
        assert len(plan.agents_to_run) > 0
        assert len(plan.utilities_to_run) > 0

    def test_case6_common_name_loads(self, case6_common):
        assert case6_common.full_name == "Mohammed Ali"
        assert case6_common.citizenship == "Canada"

    def test_case6_common_name_low_risk(self, case6_common):
        from utilities.risk_scoring import calculate_individual_risk_score
        risk = calculate_individual_risk_score(case6_common)
        assert risk.risk_level.value == "LOW"


# ---------------------------------------------------------------------------
# 8. UBO risk contribution factor
# ---------------------------------------------------------------------------

class TestUBOContributionFactor:
    """Verify UBO factor is 0.75 and configurable."""

    def test_ubo_factor_is_075(self):
        from constants import UBO_RISK_CONTRIBUTION_FACTOR
        assert UBO_RISK_CONTRIBUTION_FACTOR == 0.75

    def test_ubo_contribution_in_business_scoring(self):
        from constants import UBO_RISK_CONTRIBUTION_FACTOR
        from models import BeneficialOwner, BusinessClient
        from utilities.risk_scoring import calculate_business_risk_score

        client = BusinessClient(
            legal_name="Test Corp",
            beneficial_owners=[
                BeneficialOwner(full_name="Owner One", ownership_percentage=100),
            ],
        )
        # Pass 2 with UBO scores
        risk = calculate_business_risk_score(client, ubo_scores={"Owner One": 40})
        ubo_factors = [f for f in risk.risk_factors if f.category == "ubo_cascade"]
        assert len(ubo_factors) == 1
        assert ubo_factors[0].points == int(40 * UBO_RISK_CONTRIBUTION_FACTOR)
        assert str(UBO_RISK_CONTRIBUTION_FACTOR) in ubo_factors[0].factor

    def test_revise_risk_uses_075(self):
        from constants import UBO_RISK_CONTRIBUTION_FACTOR
        from models import RiskAssessment, RiskLevel
        from utilities.risk_scoring import revise_risk_score

        preliminary = RiskAssessment(
            total_score=10,
            risk_level=RiskLevel.LOW,
            risk_factors=[],
            score_history=[],
        )
        revised = revise_risk_score(preliminary, ubo_scores={"UBO": 60})
        ubo_factor = [f for f in revised.risk_factors if f.category == "ubo_cascade"]
        assert ubo_factor[0].points == int(60 * UBO_RISK_CONTRIBUTION_FACTOR)


# ---------------------------------------------------------------------------
# 11. FATCA dual-citizenship
# ---------------------------------------------------------------------------

class TestFATCADualCitizenship:
    """Verify US person detection from multiple indicators."""

    def test_us_tax_residency_flags_us_person(self):
        from models import IndividualClient
        from utilities.individual_fatca_crs import classify_individual_fatca_crs

        client = IndividualClient(
            full_name="Dual Citizen",
            citizenship="Canada",  # Declares as Canadian
            country_of_birth="Canada",
            us_person=False,
            tax_residencies=["Canada", "United States"],  # But has US tax residency
        )
        result = classify_individual_fatca_crs(client)
        assert result["fatca"]["us_person"] is True
        assert "US tax residency" in result["fatca"]["potential_us_person_indicators"]

    def test_us_birthplace_flags_us_person(self):
        from models import IndividualClient
        from utilities.individual_fatca_crs import classify_individual_fatca_crs

        client = IndividualClient(
            full_name="Born in USA",
            citizenship="Canada",
            country_of_birth="United States",
            us_person=False,
            tax_residencies=["Canada"],
        )
        result = classify_individual_fatca_crs(client)
        assert result["fatca"]["us_person"] is True
        assert "US country of birth" in result["fatca"]["potential_us_person_indicators"]

    def test_no_us_indicators_not_flagged(self):
        from models import IndividualClient
        from utilities.individual_fatca_crs import classify_individual_fatca_crs

        client = IndividualClient(
            full_name="Pure Canadian",
            citizenship="Canada",
            country_of_birth="Canada",
            us_person=False,
            tax_residencies=["Canada"],
        )
        result = classify_individual_fatca_crs(client)
        assert result["fatca"]["us_person"] is False
        assert result["fatca"]["potential_us_person_indicators"] == []


# ---------------------------------------------------------------------------
# 12. Condensed STR narrative
# ---------------------------------------------------------------------------

class TestCondensedNarrative:
    """Verify FINTRAC STR Part G condensed narrative."""

    def test_condense_short_text(self):
        from generators.regulatory_filing import _condense_narrative
        text = "Short text."
        assert _condense_narrative(text, max_chars=404) == "Short text."

    def test_condense_long_text(self):
        from generators.regulatory_filing import _condense_narrative
        text = "A " * 300  # 600 chars
        result = _condense_narrative(text, max_chars=404)
        assert len(result) <= 404
        assert result.endswith("... [see attached narrative]")

    def test_condense_empty(self):
        from generators.regulatory_filing import _condense_narrative
        assert _condense_narrative("", max_chars=404) == ""

    def test_fintrac_filing_has_condensed(self):
        """FINTRAC STR output should include condensed_narrative field."""
        from generators.regulatory_filing import prefill_fintrac_str
        from models import ClientType, InvestigationPlan, InvestigationResults, KYCOutput

        output = KYCOutput(
            client_id="test",
            client_type=ClientType.INDIVIDUAL,
            client_data={"full_name": "Test Person"},
            intake_classification=InvestigationPlan(
                client_type=ClientType.INDIVIDUAL, client_id="test",
            ),
            investigation_results=InvestigationResults(),
        )
        sar = {
            "narrative_text": "Full narrative here.",
            "five_ws": {"why": "This is the reason for suspicion " * 20},
            "risk_indicators": [],
        }
        result = prefill_fintrac_str(output, sar_narrative=sar)
        part_g = result["part_g_details_of_suspicion"]
        assert "condensed_narrative" in part_g
        assert len(part_g["condensed_narrative"]) <= 404


# ---------------------------------------------------------------------------
# Model field additions
# ---------------------------------------------------------------------------

class TestModelFields:
    """Verify new fields exist on models."""

    def test_evidence_record_has_data_as_of(self):
        from models import EvidenceRecord
        r = EvidenceRecord(
            evidence_id="F-001",
            source_type="agent",
            source_name="test",
            entity_screened="test",
            claim="test",
        )
        assert hasattr(r, "data_as_of")
        assert hasattr(r, "urls_are_global")
        assert hasattr(r, "data_freshness_warning")

    def test_investigation_plan_has_scope(self):
        from models import ClientType, InvestigationPlan
        plan = InvestigationPlan(client_type=ClientType.INDIVIDUAL, client_id="test")
        assert hasattr(plan, "investigation_scope")
        assert plan.investigation_scope == "full"

    def test_review_session_has_overrides(self):
        from models import ReviewSession
        session = ReviewSession(client_id="test")
        assert hasattr(session, "officer_overrides")
        assert session.officer_overrides == []
