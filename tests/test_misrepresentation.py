"""Tests for misrepresentation detection utility."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import (
    AdverseMediaLevel,
    AdverseMediaResult,
    BeneficialOwner,
    BusinessClient,
    EntityVerification,
    IndividualClient,
    InvestigationResults,
    JurisdictionRiskResult,
    PEPClassification,
    PEPLevel,
)
from utilities.misrepresentation_detector import detect_misrepresentation


class TestMisrepresentationIndividual:
    def test_no_misrepresentation_clear(self):
        """Individual with no investigation findings → no misrepresentations."""
        client = IndividualClient(full_name="Jane Doe")
        investigation = InvestigationResults()
        result = detect_misrepresentation(client, investigation)
        assert result["has_material_misrepresentation"] is False
        assert result["str_consideration_triggered"] is False
        assert len(result["misrepresentations"]) == 0
        assert len(result["evidence"]) == 1
        assert result["evidence"][0]["disposition"] == "CLEAR"

    def test_pep_non_disclosure_foreign(self):
        """Client declared not PEP, investigation found Foreign PEP → CRITICAL."""
        client = IndividualClient(
            full_name="John Smith",
            pep_self_declaration=False,
        )
        investigation = InvestigationResults(
            pep_classification=PEPClassification(
                entity_screened="John Smith",
                detected_level=PEPLevel.FOREIGN_PEP,
                self_declared=False,
            ),
        )
        result = detect_misrepresentation(client, investigation)
        assert result["has_material_misrepresentation"] is True
        assert len(result["misrepresentations"]) >= 1
        pep_misrep = next(
            m for m in result["misrepresentations"] if m["field"] == "pep_self_declaration"
        )
        assert pep_misrep["severity"] == "CRITICAL"

    def test_pep_non_disclosure_domestic(self):
        """Client declared not PEP, investigation found Domestic PEP → MATERIAL."""
        client = IndividualClient(
            full_name="Jane Doe",
            pep_self_declaration=False,
        )
        investigation = InvestigationResults(
            pep_classification=PEPClassification(
                entity_screened="Jane Doe",
                detected_level=PEPLevel.DOMESTIC_PEP,
                self_declared=False,
            ),
        )
        result = detect_misrepresentation(client, investigation)
        assert result["has_material_misrepresentation"] is True
        pep_misrep = next(
            m for m in result["misrepresentations"] if m["field"] == "pep_self_declaration"
        )
        assert pep_misrep["severity"] == "MATERIAL"

    def test_pep_self_declared_no_misrepresentation(self):
        """Client declared PEP and investigation confirms → no misrepresentation."""
        client = IndividualClient(
            full_name="John Smith",
            pep_self_declaration=True,
        )
        investigation = InvestigationResults(
            pep_classification=PEPClassification(
                entity_screened="John Smith",
                detected_level=PEPLevel.FOREIGN_PEP,
                self_declared=True,
            ),
        )
        result = detect_misrepresentation(client, investigation)
        pep_misreps = [m for m in result["misrepresentations"] if m["field"] == "pep_self_declaration"]
        assert len(pep_misreps) == 0

    def test_source_of_funds_concern(self):
        """Adverse media crime categories contradict declared source of funds → MATERIAL."""
        client = IndividualClient(
            full_name="Test Person",
            source_of_funds="employment_income",
        )
        investigation = InvestigationResults(
            individual_adverse_media=AdverseMediaResult(
                entity_screened="Test Person",
                overall_level=AdverseMediaLevel.HIGH_RISK,
                categories=["fraud", "money_laundering"],
            ),
        )
        result = detect_misrepresentation(client, investigation)
        sof_misreps = [m for m in result["misrepresentations"] if m["field"] == "source_of_funds"]
        assert len(sof_misreps) >= 1
        assert sof_misreps[0]["severity"] == "MATERIAL"

    def test_evidence_records_present(self):
        """Result should always include evidence records."""
        client = IndividualClient(full_name="Test")
        investigation = InvestigationResults()
        result = detect_misrepresentation(client, investigation)
        assert "evidence" in result
        assert len(result["evidence"]) > 0


class TestMisrepresentationBusiness:
    def test_no_misrepresentation_clear(self):
        """Business with no investigation findings → no misrepresentations."""
        client = BusinessClient(legal_name="Test Corp")
        investigation = InvestigationResults()
        result = detect_misrepresentation(client, investigation)
        assert result["has_material_misrepresentation"] is False
        assert len(result["misrepresentations"]) == 0

    def test_ubo_discrepancy(self):
        """Entity verification finds ownership discrepancy → MATERIAL."""
        client = BusinessClient(
            legal_name="Test Corp",
            beneficial_owners=[
                BeneficialOwner(full_name="Owner A", ownership_percentage=100),
            ],
        )
        investigation = InvestigationResults(
            entity_verification=EntityVerification(
                entity_name="Test Corp",
                discrepancies=["Undisclosed beneficial owner found in registry records"],
            ),
        )
        result = detect_misrepresentation(client, investigation)
        ubo_misreps = [m for m in result["misrepresentations"] if m["field"] == "beneficial_owners"]
        assert len(ubo_misreps) >= 1
        assert ubo_misreps[0]["severity"] == "MATERIAL"

    def test_undeclared_high_risk_jurisdiction(self):
        """Undeclared FATF black-list jurisdiction → CRITICAL."""
        client = BusinessClient(
            legal_name="Test Corp",
            countries_of_operation=["Canada"],
        )
        investigation = InvestigationResults(
            jurisdiction_risk=JurisdictionRiskResult(
                jurisdictions_assessed=["Canada", "Iran"],
                fatf_black_list=["Iran"],
            ),
        )
        result = detect_misrepresentation(client, investigation)
        assert result["has_material_misrepresentation"] is True
        jurisdiction_misreps = [
            m for m in result["misrepresentations"]
            if m["field"] == "countries_of_operation"
        ]
        assert len(jurisdiction_misreps) >= 1
        assert jurisdiction_misreps[0]["severity"] == "CRITICAL"

    def test_business_adverse_media_crime(self):
        """Adverse media with serious crime categories + intended_use → CRITICAL."""
        client = BusinessClient(
            legal_name="Test Corp",
            intended_use="general business operations",
        )
        investigation = InvestigationResults(
            business_adverse_media=AdverseMediaResult(
                entity_screened="Test Corp",
                overall_level=AdverseMediaLevel.HIGH_RISK,
                categories=["money_laundering", "fraud"],
            ),
        )
        result = detect_misrepresentation(client, investigation)
        use_misreps = [m for m in result["misrepresentations"] if m["field"] == "intended_use"]
        assert len(use_misreps) >= 1
        assert use_misreps[0]["severity"] == "CRITICAL"
        assert result["str_consideration_triggered"] is True


class TestMisrepresentationSeverity:
    def test_severity_levels_exist(self):
        """Verify severity levels are valid strings."""
        valid = {"IMMATERIAL", "NOTABLE", "MATERIAL", "CRITICAL"}
        client = IndividualClient(
            full_name="Test",
            pep_self_declaration=False,
        )
        investigation = InvestigationResults(
            pep_classification=PEPClassification(
                entity_screened="Test",
                detected_level=PEPLevel.FOREIGN_PEP,
            ),
        )
        result = detect_misrepresentation(client, investigation)
        for m in result["misrepresentations"]:
            assert m["severity"] in valid
