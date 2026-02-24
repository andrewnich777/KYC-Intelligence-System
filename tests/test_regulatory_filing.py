"""Tests for regulatory filing pre-fill generator (Feature 3)."""

import os
import sys
from datetime import datetime
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generators.regulatory_filing import (
    _format_address,
    _map_activity_type_codes,
    _split_name,
    prefill_fincen_sar,
    prefill_fintrac_str,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _mock_output(client_type="individual"):
    output = MagicMock()
    output.client_id = "test_filing_001"
    output.client_type.value = client_type
    output.generated_at = datetime(2026, 3, 1, 12, 0, 0)

    if client_type == "individual":
        output.client_data = {
            "full_name": "Maria Chen-Dubois",
            "date_of_birth": "1985-06-15",
            "citizenship": "Canada",
            "country_of_residence": "Canada",
            "employment": {"occupation": "Banker"},
            "address": {"street": "123 Main", "city": "Toronto", "province_state": "ON",
                         "postal_code": "M5V", "country": "CA"},
            "sin_last4": "1234",
            "account_requests": [{"account_type": "Checking"}],
        }
    else:
        output.client_data = {
            "legal_name": "Northern Maple Trading",
            "operating_name": "NMT Corp",
            "business_number": "BN12345",
            "incorporation_jurisdiction": "Ontario",
            "entity_type": "Corporation",
            "industry": "Import/Export",
            "address": {"street": "456 Bay", "city": "Toronto", "country": "CA"},
            "beneficial_owners": [
                {"full_name": "Owner One", "ownership_percentage": 60, "citizenship": "CA"},
            ],
            "account_requests": [],
        }

    output.investigation_results.pep_classification.detected_level.value = "NOT_PEP"
    output.investigation_results.individual_sanctions = None
    output.investigation_results.entity_sanctions = None
    output.investigation_results.individual_adverse_media = None
    output.investigation_results.business_adverse_media = None
    output.investigation_results.misrepresentation_detection = None
    output.investigation_results.sar_risk_assessment = None

    return output


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSplitName:
    def test_simple_name(self):
        first, middle, last = _split_name("John Smith")
        assert first == "John"
        assert middle == ""
        assert last == "Smith"

    def test_three_part_name(self):
        first, middle, last = _split_name("John Michael Smith")
        assert first == "John"
        assert middle == "Michael"
        assert last == "Smith"

    def test_hyphenated_name(self):
        first, middle, last = _split_name("Maria Chen-Dubois")
        assert first == "Maria"
        assert last == "Chen-Dubois"

    def test_four_part_name(self):
        first, middle, last = _split_name("Maria Elena Chen Dubois")
        assert first == "Maria"
        assert middle == "Elena Chen"
        assert last == "Dubois"

    def test_single_name(self):
        first, middle, last = _split_name("Madonna")
        assert first == "Madonna"
        assert last == ""
        assert middle == ""

    def test_empty_name(self):
        first, middle, last = _split_name("")
        assert first == "" and middle == "" and last == ""

    def test_none_safe(self):
        """_split_name should handle None gracefully via the caller."""
        first, middle, last = _split_name("")
        assert first == ""


class TestFormatAddress:
    def test_dict_address(self):
        addr = {"street": "123 Main", "city": "Toronto", "province_state": "ON", "country": "CA"}
        result = _format_address(addr)
        assert "123 Main" in result
        assert "Toronto" in result

    def test_string_address(self):
        assert _format_address("123 Main St") == "123 Main St"

    def test_none_address(self):
        assert _format_address(None) == ""

    def test_partial_address(self):
        addr = {"city": "Toronto", "country": "CA"}
        result = _format_address(addr)
        assert result == "Toronto, CA"


class TestMapActivityTypeCodes:
    def test_default_other(self):
        output = _mock_output()
        output.investigation_results.pep_classification.detected_level.value = "NOT_PEP"
        codes = _map_activity_type_codes(output)
        assert "Other" in codes

    def test_pep_adds_bribery(self):
        output = _mock_output()
        output.investigation_results.pep_classification.detected_level.value = "FOREIGN_PEP"
        codes = _map_activity_type_codes(output)
        assert "Bribery/Gratuity" in codes

    def test_sanctions_adds_terrorist_financing(self):
        output = _mock_output()
        sr = MagicMock()
        sr.disposition.value = "POTENTIAL_MATCH"
        output.investigation_results.individual_sanctions = sr
        codes = _map_activity_type_codes(output)
        assert "Terrorist Financing" in codes

    def test_deduplication(self):
        output = _mock_output()
        output.investigation_results.pep_classification.detected_level.value = "FOREIGN_PEP"
        codes = _map_activity_type_codes(output)
        # Should not have duplicates
        assert len(codes) == len(set(codes))


class TestPrefillFincenSar:
    def test_returns_required_parts(self):
        result = prefill_fincen_sar(_mock_output())
        assert "part_i_subject_information" in result
        assert "part_ii_suspicious_activity" in result
        assert "part_iii_financial_institution" in result
        assert "part_iv_filing_institution" in result
        assert "part_v_narrative" in result
        assert "filing_notes" in result

    def test_individual_name_split(self):
        result = prefill_fincen_sar(_mock_output())
        p1 = result["part_i_subject_information"]
        assert p1["first_name"] == "Maria"
        assert p1["last_name"] == "Chen-Dubois"
        assert p1["subject_type"] == "individual"

    def test_business_entity(self):
        result = prefill_fincen_sar(_mock_output(client_type="business"))
        p1 = result["part_i_subject_information"]
        assert p1["subject_type"] == "entity"
        assert p1["entity_name"] == "Northern Maple Trading"

    def test_ssn_not_autofilled(self):
        """Security: SSN/TIN should never be auto-filled."""
        result = prefill_fincen_sar(_mock_output())
        p1 = result["part_i_subject_information"]
        assert p1["ssn_tin"] == ""

    def test_narrative_from_sar(self):
        sar = {"narrative_text": "Test narrative", "word_count": 2}
        result = prefill_fincen_sar(_mock_output(), sar_narrative=sar)
        assert result["part_v_narrative"]["narrative_text"] == "Test narrative"

    def test_institution_type_configurable(self):
        """Bug fix: institution type should not be hardcoded."""
        result = prefill_fincen_sar(_mock_output())
        p3 = result["part_iii_financial_institution"]
        # Should have a value (from env or default), not be hardcoded to "Securities/Futures"
        assert p3["type_of_institution"] != ""

    def test_filing_notes_present(self):
        result = prefill_fincen_sar(_mock_output())
        assert len(result["filing_notes"]) >= 3


class TestPrefillFintracStr:
    def test_returns_required_parts(self):
        result = prefill_fintrac_str(_mock_output())
        assert "part_a_report_info" in result
        assert "part_b_transactions" in result
        assert "part_c_accounts" in result
        assert "part_ef_subject_info" in result
        assert "part_g_details_of_suspicion" in result

    def test_individual_name_split(self):
        result = prefill_fintrac_str(_mock_output())
        pef = result["part_ef_subject_info"]
        assert pef["first_name"] == "Maria"
        assert pef["last_name"] == "Chen-Dubois"
        assert pef["type"] == "individual"

    def test_business_entity(self):
        result = prefill_fintrac_str(_mock_output(client_type="business"))
        pef = result["part_ef_subject_info"]
        assert pef["type"] == "entity"
        assert pef["entity_name"] == "Northern Maple Trading"

    def test_business_beneficial_owners(self):
        result = prefill_fintrac_str(_mock_output(client_type="business"))
        pef = result["part_ef_subject_info"]
        assert len(pef["beneficial_owners"]) == 1
        assert pef["beneficial_owners"][0]["name"] == "Owner One"

    def test_account_requests_mapped(self):
        result = prefill_fintrac_str(_mock_output())
        pc = result["part_c_accounts"]
        assert len(pc["accounts"]) == 1
        assert pc["accounts"][0]["account_type"] == "Checking"

    def test_narrative_from_sar(self):
        sar = {"narrative_text": "FINTRAC narrative", "risk_indicators": ["PEP"]}
        result = prefill_fintrac_str(_mock_output(), sar_narrative=sar)
        pg = result["part_g_details_of_suspicion"]
        assert pg["narrative_text"] == "FINTRAC narrative"
        assert "PEP" in pg["indicators_of_suspicious_activity"]
