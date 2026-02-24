"""
Tests for jurisdiction risk hardening.

WS4: Deterministic cross-check, evidence records, ID collision fix.
"""

from models import RiskLevel


class TestDeterministicCrossCheck:
    """Reference data cross-check injects countries the AI missed."""

    def test_ofac_country_injected(self):
        """If AI misses Russia as OFAC-sanctioned, reference data injects it."""
        from agents.jurisdiction_risk import JurisdictionRiskAgent
        agent = JurisdictionRiskAgent.__new__(JurisdictionRiskAgent)
        agent._fetched_urls = []
        agent._search_queries = []
        result = {
            "json": {
                "jurisdictions_assessed": ["Russia", "Canada"],
                "fatf_grey_list": [],
                "fatf_black_list": [],
                "sanctions_programs": [],
                "fintrac_directives": [],
                "overall_jurisdiction_risk": "LOW",
            },
            "text": "",
        }
        jr = agent._parse_result(result, ["Russia", "Canada"])
        # Russia should have an OFAC evidence record injected
        ofac_records = [
            r for r in jr.evidence_records
            if "OFAC" in (getattr(r, 'claim', '') or '')
        ]
        assert len(ofac_records) >= 1

    def test_fatf_black_list_injected(self):
        """If AI misses Iran as FATF black list, reference data injects it."""
        from agents.jurisdiction_risk import JurisdictionRiskAgent
        agent = JurisdictionRiskAgent.__new__(JurisdictionRiskAgent)
        agent._fetched_urls = []
        agent._search_queries = []
        result = {
            "json": {
                "jurisdictions_assessed": ["Iran", "Canada"],
                "fatf_grey_list": [],
                "fatf_black_list": [],
                "sanctions_programs": [],
                "overall_jurisdiction_risk": "LOW",
            },
            "text": "",
        }
        jr = agent._parse_result(result, ["Iran", "Canada"])
        assert "Iran" in jr.fatf_black_list

    def test_canada_not_flagged(self):
        """Canada should not be flagged by reference data."""
        from agents.jurisdiction_risk import JurisdictionRiskAgent
        agent = JurisdictionRiskAgent.__new__(JurisdictionRiskAgent)
        agent._fetched_urls = []
        agent._search_queries = []
        result = {
            "json": {
                "jurisdictions_assessed": ["Canada"],
                "fatf_grey_list": [],
                "fatf_black_list": [],
                "sanctions_programs": [],
                "overall_jurisdiction_risk": "LOW",
            },
            "text": "",
        }
        jr = agent._parse_result(result, ["Canada"])
        assert jr.overall_jurisdiction_risk == RiskLevel.LOW


class TestEvidenceIDCollision:
    """Evidence IDs should be unique even for countries with same prefix."""

    def test_different_ids_for_similar_countries(self):
        """South Korea and South Sudan should get different evidence IDs."""
        from agents.jurisdiction_risk import JurisdictionRiskAgent
        agent = JurisdictionRiskAgent.__new__(JurisdictionRiskAgent)
        agent._fetched_urls = []
        agent._search_queries = []
        result = {
            "json": {
                "jurisdictions_assessed": ["South Korea", "South Sudan"],
                "fatf_grey_list": ["South Korea", "South Sudan"],
                "fatf_black_list": [],
                "sanctions_programs": [],
                "overall_jurisdiction_risk": "HIGH",
            },
            "text": "",
        }
        jr = agent._parse_result(result, ["South Korea", "South Sudan"])
        ids = [r.evidence_id for r in jr.evidence_records]
        # All IDs should be unique
        assert len(ids) == len(set(ids))


class TestOFACFINTRACEvidenceRecords:
    """Sanctions programs and FINTRAC directives get evidence records."""

    def test_sanctions_program_gets_evidence(self):
        from agents.jurisdiction_risk import JurisdictionRiskAgent
        agent = JurisdictionRiskAgent.__new__(JurisdictionRiskAgent)
        agent._fetched_urls = []
        agent._search_queries = []
        result = {
            "json": {
                "jurisdictions_assessed": ["Syria"],
                "fatf_grey_list": [],
                "fatf_black_list": [],
                "sanctions_programs": [
                    {"program": "Syria Sanctions", "country": "Syria"}
                ],
                "overall_jurisdiction_risk": "HIGH",
            },
            "text": "",
        }
        jr = agent._parse_result(result, ["Syria"])
        ofac_records = [r for r in jr.evidence_records if "OFAC" in r.claim or "sanctions program" in r.claim]
        assert len(ofac_records) >= 1

    def test_fintrac_directive_gets_evidence(self):
        from agents.jurisdiction_risk import JurisdictionRiskAgent
        agent = JurisdictionRiskAgent.__new__(JurisdictionRiskAgent)
        agent._fetched_urls = []
        agent._search_queries = []
        result = {
            "json": {
                "jurisdictions_assessed": ["Myanmar"],
                "fatf_grey_list": [],
                "fatf_black_list": [],
                "fintrac_directives": ["Transactions with Myanmar"],
                "sanctions_programs": [],
                "overall_jurisdiction_risk": "HIGH",
            },
            "text": "",
        }
        jr = agent._parse_result(result, ["Myanmar"])
        fintrac_records = [r for r in jr.evidence_records if "FINTRAC" in r.claim]
        assert len(fintrac_records) >= 1
