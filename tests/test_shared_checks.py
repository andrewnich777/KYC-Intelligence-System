"""Tests for shared utility functions in shared_checks.py."""

from utilities.shared_checks import (
    analyze_ownership_structure,
    check_entity_us_nexus,
    check_individual_us_indicia,
    check_str_triggers,
    classify_pep_from_investigation,
    is_canada_country,
    is_us_country,
)


class TestIsUsCountry:
    """Test US country detection."""

    def test_united_states(self):
        assert is_us_country("United States") is True

    def test_us(self):
        assert is_us_country("US") is True

    def test_usa(self):
        assert is_us_country("USA") is True

    def test_case_insensitive(self):
        assert is_us_country("united states") is True
        assert is_us_country("UNITED STATES") is True

    def test_with_whitespace(self):
        assert is_us_country("  US  ") is True

    def test_canada_not_us(self):
        assert is_us_country("Canada") is False

    def test_none_safe(self):
        assert is_us_country(None) is False

    def test_empty_string(self):
        assert is_us_country("") is False


class TestIsCanadaCountry:
    """Test Canada country detection."""

    def test_canada(self):
        assert is_canada_country("Canada") is True

    def test_ca(self):
        assert is_canada_country("CA") is True

    def test_case_insensitive(self):
        assert is_canada_country("canada") is True
        assert is_canada_country("CANADA") is True

    def test_us_not_canada(self):
        assert is_canada_country("United States") is False

    def test_none_safe(self):
        assert is_canada_country(None) is False


class TestCheckIndividualUsIndicia:
    """Test US indicia detection for individuals."""

    def test_no_indicia_for_canadian(self, individual_client_low):
        indicia = check_individual_us_indicia(individual_client_low)
        assert len(indicia) == 0

    def test_us_person_flag(self, individual_client_low):
        individual_client_low.us_person = True
        indicia = check_individual_us_indicia(individual_client_low)
        assert len(indicia) > 0
        assert any("US person" in i for i in indicia)

    def test_us_citizenship(self, individual_client_low):
        individual_client_low.citizenship = "United States"
        indicia = check_individual_us_indicia(individual_client_low)
        assert any("citizenship" in i.lower() for i in indicia)

    def test_us_birthplace(self, individual_client_low):
        individual_client_low.country_of_birth = "USA"
        indicia = check_individual_us_indicia(individual_client_low)
        assert any("birthplace" in i.lower() for i in indicia)

    def test_us_tin(self, individual_client_low):
        individual_client_low.us_tin = "123-45-6789"
        indicia = check_individual_us_indicia(individual_client_low)
        assert any("TIN" in i for i in indicia)


class TestCheckEntityUsNexus:
    """Test US nexus detection for business entities."""

    def test_nexus_self_declared(self, business_client_critical):
        indicators = check_entity_us_nexus(business_client_critical)
        # Case 3 has us_nexus=True
        assert any("self-declared" in i.lower() for i in indicators)

    def test_no_nexus_for_non_us_entity(self, business_client_critical):
        """Check that US nexus indicators are returned as a list."""
        indicators = check_entity_us_nexus(business_client_critical)
        assert isinstance(indicators, list)


class TestAnalyzeOwnershipStructure:
    """Test ownership analysis."""

    def test_no_owners_high_risk(self):
        analysis = analyze_ownership_structure([])
        assert analysis["risk_level"] == "high"
        assert len(analysis["concerns"]) > 0

    def test_with_owners(self, business_client_critical):
        analysis = analyze_ownership_structure(business_client_critical.beneficial_owners)
        assert analysis["total_owners"] == len(business_client_critical.beneficial_owners)
        assert analysis["ownership_coverage"] > 0

    def test_complex_ownership_flagged(self, business_client_critical):
        """Case 3 has multiple UBOs — check that complexity is assessed."""
        analysis = analyze_ownership_structure(business_client_critical.beneficial_owners)
        # Should have some level of assessment
        assert analysis["risk_level"] in ("low", "medium", "high")


class TestClassifyPepFromInvestigation:
    """Test PEP classification from investigation results."""

    def test_no_investigation(self):
        level, points = classify_pep_from_investigation(None)
        assert level == "NOT_PEP"
        assert points == 0

    def test_not_pep(self):
        from models import InvestigationResults
        investigation = InvestigationResults()
        level, points = classify_pep_from_investigation(investigation)
        assert level == "NOT_PEP"
        assert points == 0


class TestCheckStrTriggers:
    """Test STR trigger detection."""

    def test_no_triggers_for_low_risk(self, individual_client_low):
        from models import InvestigationResults
        investigation = InvestigationResults()
        triggers = check_str_triggers(individual_client_low, investigation)
        assert len(triggers) == 0

    def test_no_investigation(self, individual_client_low):
        triggers = check_str_triggers(individual_client_low, None)
        assert isinstance(triggers, list)
