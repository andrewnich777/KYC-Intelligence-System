"""Tests for prompt template loading (Phase F)."""


import pytest

from agents.base import _PROMPTS_DIR, load_prompt_template

EXPECTED_TEMPLATES = [
    "individual_sanctions",
    "pep_detection",
    "individual_adverse_media",
    "entity_verification",
    "entity_sanctions",
    "business_adverse_media",
    "jurisdiction_risk",
    "kyc_synthesis",
    "transaction_monitoring",
]


class TestPromptTemplates:
    def test_all_templates_exist(self):
        for name in EXPECTED_TEMPLATES:
            path = _PROMPTS_DIR / f"{name}.txt"
            assert path.exists(), f"Missing template: {name}.txt"

    def test_template_loading(self):
        prompt = load_prompt_template("individual_sanctions")
        assert isinstance(prompt, str)
        assert len(prompt) > 100

    def test_variable_injection(self):
        prompt = load_prompt_template("individual_sanctions")
        # Should contain expanded regulatory context, not the placeholder
        assert "FINTRAC" in prompt
        assert "{KYC_REGULATORY_CONTEXT}" not in prompt

    def test_evidence_rules_injected(self):
        prompt = load_prompt_template("pep_detection")
        assert "Evidence Classification" in prompt
        assert "{KYC_EVIDENCE_RULES}" not in prompt

    def test_output_rules_injected(self):
        prompt = load_prompt_template("entity_verification")
        assert "Output Format" in prompt
        assert "{KYC_OUTPUT_RULES}" not in prompt

    def test_false_positive_rules_injected(self):
        prompt = load_prompt_template("entity_sanctions")
        assert "False Positive" in prompt
        assert "{KYC_FALSE_POSITIVE_RULES}" not in prompt

    def test_missing_template_raises(self):
        with pytest.raises(FileNotFoundError):
            load_prompt_template("nonexistent_template")

    def test_literal_braces_preserved(self):
        """Double braces {{}} in templates should become single braces {} after format."""
        prompt = load_prompt_template("individual_sanctions")
        # Templates contain {{list_name, matched_name, ...}} which should render as {list_name, ...}
        assert "{list_name" in prompt

    def test_icij_in_prompts(self):
        """Verify ICIJ Offshore Leaks is referenced in relevant prompts."""
        icij_templates = [
            "individual_adverse_media",
            "business_adverse_media",
            "entity_verification",
            "individual_sanctions",
            "entity_sanctions",
        ]
        for name in icij_templates:
            prompt = load_prompt_template(name)
            assert "offshoreleaks.icij.org" in prompt or "ICIJ" in prompt, (
                f"Template {name} missing ICIJ reference"
            )

    def test_broader_screening_in_sanctions_prompts(self):
        """Verify EU Consolidated, UK HMT, Interpol in sanctions prompts."""
        for name in ["individual_sanctions", "entity_sanctions"]:
            prompt = load_prompt_template(name)
            assert "EU Consolidated" in prompt, f"{name} missing EU Consolidated"
            assert "UK HMT" in prompt, f"{name} missing UK HMT"
            assert "Interpol" in prompt, f"{name} missing Interpol"

    def test_tier3_in_adverse_media_prompts(self):
        """Verify TIER_3 and named outlets in adverse media prompts."""
        for name in ["individual_adverse_media", "business_adverse_media"]:
            prompt = load_prompt_template(name)
            assert "TIER_3" in prompt, f"{name} missing TIER_3"
            assert "Reuters" in prompt or "Bloomberg" in prompt or "TIER_1" in prompt, (
                f"{name} missing named outlet references"
            )

    def test_all_agents_use_templates(self):
        """Verify each agent class loads from template (not inline f-string)."""
        from agents.business_adverse_media import BusinessAdverseMediaAgent
        from agents.entity_sanctions import EntitySanctionsAgent
        from agents.entity_verification import EntityVerificationAgent
        from agents.individual_adverse_media import IndividualAdverseMediaAgent
        from agents.individual_sanctions import IndividualSanctionsAgent
        from agents.jurisdiction_risk import JurisdictionRiskAgent
        from agents.kyc_synthesis import KYCSynthesisAgent
        from agents.pep_detection import PEPDetectionAgent
        from agents.transaction_monitoring import TransactionMonitoringAgent

        agents = [
            IndividualSanctionsAgent,
            PEPDetectionAgent,
            IndividualAdverseMediaAgent,
            EntityVerificationAgent,
            EntitySanctionsAgent,
            BusinessAdverseMediaAgent,
            JurisdictionRiskAgent,
            TransactionMonitoringAgent,
            KYCSynthesisAgent,
        ]
        for agent_cls in agents:
            # Creating agent requires API key, but system_prompt is a property
            # that just loads a template file — no API call needed
            agent = agent_cls.__new__(agent_cls)
            prompt = agent.system_prompt
            assert len(prompt) > 50, f"{agent_cls.__name__} has empty system prompt"
            assert "FINTRAC" in prompt or "KYC" in prompt or "AML" in prompt, (
                f"{agent_cls.__name__} prompt looks wrong"
            )
