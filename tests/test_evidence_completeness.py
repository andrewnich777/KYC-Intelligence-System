"""
Tests for evidence completeness and URL passthrough.

WS5: URL extraction, evidence level corrections, and missing records.
"""

from models import DispositionStatus, EvidenceClass


class TestAdverseMediaURLExtraction:
    """Articles' URLs should be extracted into evidence source_urls."""

    def test_article_url_extracted(self):
        from agents.adverse_media_base import AdverseMediaParserMixin
        from agents.base import BaseAgent

        class MockAgent(AdverseMediaParserMixin, BaseAgent):
            @property
            def name(self): return "TestAdvMedia"
            @property
            def system_prompt(self): return ""
            @property
            def tools(self): return []

        agent = MockAgent.__new__(MockAgent)
        agent._fetched_urls = ["https://fallback.example.com"]
        agent._search_queries = []
        result = {
            "json": {
                "entity_screened": "Test Corp",
                "overall_level": "HIGH_RISK",
                "articles_found": [
                    {"title": "Fraud case", "url": "https://news.example.com/fraud"},
                    {"title": "Money laundering", "source_url": "https://news.example.com/ml"},
                ],
                "categories": ["fraud"],
            },
            "text": "",
        }
        amr = agent._parse_adverse_media_result(result, "Test Corp", "adv_test", "Adverse media")
        # First article should have its specific URL
        assert "https://news.example.com/fraud" in amr.evidence_records[0].source_urls
        # Second article should have its specific URL
        assert "https://news.example.com/ml" in amr.evidence_records[1].source_urls


class TestPEPFamilyAssociationRecords:
    """Family associations should get evidence records."""

    def test_family_association_evidence_built(self):
        from agents.pep_detection import PEPDetectionAgent
        agent = PEPDetectionAgent.__new__(PEPDetectionAgent)
        agent._fetched_urls = []
        agent._search_queries = []
        result = {
            "json": {
                "entity_screened": "Jane Doe",
                "detected_level": "PEP_FAMILY",
                "positions_found": [],
                "family_associations": [
                    {"name": "John Doe", "relationship": "spouse"},
                ],
            },
            "text": "",
        }
        pep = agent._parse_result(result, "Jane Doe", False)
        family_records = [
            r for r in pep.evidence_records
            if "family" in (getattr(r, 'evidence_id', '') or '').lower()
        ]
        assert len(family_records) >= 1
        assert "John Doe" in family_records[0].claim


class TestEntitySanctionsOFAC50Record:
    """OFAC 50% rule should generate an evidence record."""

    def test_ofac_50_generates_evidence(self):
        from agents.entity_sanctions import EntitySanctionsAgent
        agent = EntitySanctionsAgent.__new__(EntitySanctionsAgent)
        agent._fetched_urls = []
        agent._search_queries = []
        result = {
            "json": {
                "entity_screened": "Test Corp",
                "ofac_50_percent_rule_applicable": True,
                "matches": [{"matched_name": "Test Corp"}],
                "screening_sources": ["CSL"],
            },
            "text": "",
        }
        sr = agent._parse_result(result, "Test Corp", beneficial_owners=None)
        ofac50_records = [
            r for r in sr.evidence_records
            if "ofac" in (getattr(r, 'evidence_id', '') or '').lower() and "50" in (getattr(r, 'evidence_id', '') or '')
        ]
        assert len(ofac50_records) >= 1


class TestEntityVerificationUBORecord:
    """UBO structure verification should get an evidence record."""

    def test_ubo_verified_gets_record(self):
        from agents.entity_verification import EntityVerificationAgent
        agent = EntityVerificationAgent.__new__(EntityVerificationAgent)
        agent._fetched_urls = []
        agent._search_queries = []
        result = {
            "json": {
                "entity_name": "Test Corp",
                "verified_registration": True,
                "ubo_structure_verified": True,
                "registry_sources": ["Corporations Canada"],
                "registration_details": {},
                "discrepancies": [],
            },
            "text": "",
        }
        ev = agent._parse_result(result, "Test Corp")
        ubo_records = [
            r for r in ev.evidence_records
            if "ubo" in (getattr(r, 'evidence_id', '') or '').lower()
        ]
        assert len(ubo_records) >= 1
        assert ubo_records[0].disposition == DispositionStatus.CLEAR

    def test_ubo_unverified_gets_pending_record(self):
        from agents.entity_verification import EntityVerificationAgent
        agent = EntityVerificationAgent.__new__(EntityVerificationAgent)
        agent._fetched_urls = []
        agent._search_queries = []
        result = {
            "json": {
                "entity_name": "Test Corp",
                "verified_registration": False,
                "ubo_structure_verified": False,
                "registry_sources": [],
                "registration_details": {},
                "discrepancies": ["Name mismatch"],
            },
            "text": "",
        }
        ev = agent._parse_result(result, "Test Corp")
        ubo_records = [
            r for r in ev.evidence_records
            if "ubo" in (getattr(r, 'evidence_id', '') or '').lower()
        ]
        assert len(ubo_records) >= 1
        assert ubo_records[0].disposition == DispositionStatus.PENDING_REVIEW


class TestJurisdictionEvidenceLevel:
    """FATF records should use SOURCED (not VERIFIED) evidence level."""

    def test_fatf_records_are_sourced(self):
        from agents.jurisdiction_risk import JurisdictionRiskAgent
        agent = JurisdictionRiskAgent.__new__(JurisdictionRiskAgent)
        agent._fetched_urls = ["https://fatf.org"]
        agent._search_queries = []
        result = {
            "json": {
                "jurisdictions_assessed": ["Turkey"],
                "fatf_grey_list": ["Turkey"],
                "fatf_black_list": [],
                "sanctions_programs": [],
                "overall_jurisdiction_risk": "MEDIUM",
            },
            "text": "",
        }
        jr = agent._parse_result(result, ["Turkey"])
        fatf_records = [
            r for r in jr.evidence_records
            if "grey" in (getattr(r, 'evidence_id', '') or '')
        ]
        assert len(fatf_records) >= 1
        assert fatf_records[0].evidence_level == EvidenceClass.SOURCED
