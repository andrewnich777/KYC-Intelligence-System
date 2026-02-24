"""
Tests verifying that consumers read the correct keys from utility return dicts.

WS1: Dictionary key mismatch regression tests.
"""


class TestSARRiskAssessmentKeys:
    """Verify sar_risk_assessment dict uses 'sar_risk_level' not 'risk_level'."""

    def test_sar_risk_level_key(self):
        sar = {"sar_risk_level": "HIGH", "triggers": [{"description": "match"}]}
        assert "sar_risk_level" in sar
        assert "risk_level" not in sar
        assert sar.get("sar_risk_level") == "HIGH"

    def test_triggers_key_not_sar_triggers(self):
        sar = {"sar_risk_level": "LOW", "triggers": []}
        assert "triggers" in sar
        assert "sar_triggers" not in sar

    def test_no_grounds_for_suspicion_key(self):
        """Utility returns 'triggers', not 'grounds_for_suspicion'."""
        sar = {"sar_risk_level": "MEDIUM", "triggers": ["unusual activity"]}
        assert "grounds_for_suspicion" not in sar
        assert sar.get("triggers") == ["unusual activity"]

    def test_no_risk_indicators_key(self):
        """Utility returns 'triggers', not 'risk_indicators'."""
        sar = {"sar_risk_level": "LOW", "triggers": []}
        assert "risk_indicators" not in sar


class TestMisrepresentationDetectionKeys:
    """Verify misrepresentation dict uses 'misrepresentations' not 'findings'."""

    def test_misrepresentations_key(self):
        misrep = {
            "misrepresentations": [{"description": "Address mismatch"}],
            "has_material_misrepresentation": True,
            "str_consideration_triggered": False,
        }
        assert "misrepresentations" in misrep
        assert "findings" not in misrep
        assert "discrepancies" not in misrep


class TestComplianceActionsKeys:
    """Verify compliance_actions dict uses 'actions' not 'required_actions'."""

    def test_actions_key(self):
        ca = {"actions": [{"action_type": "review"}], "reports": [], "timelines": {}}
        assert "actions" in ca
        assert "required_actions" not in ca

    def test_reports_key_not_required_filings(self):
        ca = {"actions": [], "reports": [{"type": "LVCTR", "timeline": "15 days"}]}
        assert "reports" in ca
        assert "required_filings" not in ca

    def test_report_sub_keys(self):
        report = {"type": "LVCTR", "timeline": "15 days", "filing_decision": "REQUIRED"}
        assert "type" in report
        assert "timeline" in report
        assert "filing_decision" in report
        assert "filing_type" not in report
        assert "deadline" not in report


class TestSuitabilityAssessmentKeys:
    """Verify suitability details use correct nested keys."""

    def test_income_assessment_uses_status_not_assessment(self):
        details = {"income_assessment": {"status": "pass", "notes": []}}
        income = details["income_assessment"]
        assert "status" in income
        assert "assessment" not in income

    def test_wealth_income_ratio_nested_in_income(self):
        details = {"income_assessment": {"status": "concern", "wealth_income_ratio": 3.5}}
        assert "wealth_income_ratio" not in details
        assert "wealth_income_ratio" in details["income_assessment"]

    def test_source_of_funds_assessment_key(self):
        details = {"source_of_funds_assessment": {"status": "pass", "notes": []}}
        assert "source_of_funds_assessment" in details
        assert "source_of_funds" not in details


class TestIDVerificationKeys:
    """Verify id_verification dict uses 'concerns' not 'outstanding_items'."""

    def test_concerns_key(self):
        idv = {"method": "document", "status": "verified", "concerns": []}
        assert "concerns" in idv
        assert "outstanding_items" not in idv
