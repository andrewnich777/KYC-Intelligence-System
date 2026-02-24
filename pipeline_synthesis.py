"""
Synthesis mixin for KYC Pipeline.

Handles Stage 3: Cross-referencing findings and producing synthesis output.
"""

import json

from constants import FAILED_SENTINEL_KEY, SYNTHESIS_MAX_TOKENS, SYNTHESIS_MIN_TOKENS, SYNTHESIS_TOKENS_PER_RECORD
from logger import get_logger
from models import (
    BusinessClient,
    IndividualClient,
    InvestigationPlan,
    InvestigationResults,
    KYCSynthesisOutput,
    OnboardingDecision,
)
from utilities.risk_scoring import revise_risk_score

logger = get_logger(__name__)


class SynthesisMixin:
    """Stage 3 synthesis execution."""

    @staticmethod
    def _build_investigation_summary(investigation: InvestigationResults) -> str:
        """Build a readable summary of all investigation results (utilities + agents).

        This gives synthesis and review access to the FULL data, not just
        evidence store summaries.
        """
        sections = []

        # Utility results (stored as dicts)
        utility_fields = {
            "id_verification": "ID Verification",
            "suitability_assessment": "Suitability Assessment",
            "fatca_crs": "FATCA/CRS Assessment",
            "edd_requirements": "EDD Requirements",
            "compliance_actions": "Compliance Actions",
            "document_requirements": "Document Requirements",
            "business_risk_assessment": "Business Risk Assessment",
            "misrepresentation_detection": "Misrepresentation Detection",
            "sar_risk_assessment": "SAR Risk Assessment",
        }
        for field_name, display_name in utility_fields.items():
            data = getattr(investigation, field_name, None)
            if data is None:
                continue
            # Strip evidence key (already in evidence store) to avoid duplication
            display_data = {k: v for k, v in data.items() if k != "evidence"}
            sections.append(f"### {display_name}\n```json\n{json.dumps(display_data, indent=2, default=str)}\n```")

        # Agent results (Pydantic models)
        agent_fields = {
            "individual_sanctions": "Individual Sanctions Screening",
            "pep_classification": "PEP Classification",
            "individual_adverse_media": "Individual Adverse Media",
            "entity_verification": "Entity Verification",
            "entity_sanctions": "Entity Sanctions Screening",
            "business_adverse_media": "Business Adverse Media",
            "jurisdiction_risk": "Jurisdiction Risk Assessment",
            "transaction_monitoring": "Transaction Monitoring",
        }
        for field_name, display_name in agent_fields.items():
            result = getattr(investigation, field_name, None)
            if result is None:
                continue
            # Serialize Pydantic model, excluding verbose evidence_records (already in store)
            result_dict = result.model_dump(mode="json", exclude={"evidence_records"})
            sections.append(f"### {display_name}\n```json\n{json.dumps(result_dict, indent=2, default=str)}\n```")

        # UBO screening
        if investigation.ubo_screening:
            sections.append(f"### UBO Screening\n```json\n{json.dumps(investigation.ubo_screening, indent=2, default=str)}\n```")

        if not sections:
            return ""
        return "## Full Investigation Results\n\n" + "\n\n".join(sections)

    @staticmethod
    def _build_search_query_summary(investigation: InvestigationResults) -> str:
        """Build a readable summary of all search queries executed by agents."""
        agent_fields = {
            "IndividualSanctions": "individual_sanctions",
            "PEPDetection": "pep_classification",
            "IndividualAdverseMedia": "individual_adverse_media",
            "EntityVerification": "entity_verification",
            "EntitySanctions": "entity_sanctions",
            "BusinessAdverseMedia": "business_adverse_media",
            "JurisdictionRisk": "jurisdiction_risk",
            "TransactionMonitoring": "transaction_monitoring",
        }
        sections = []
        for agent_name, field_name in agent_fields.items():
            result = getattr(investigation, field_name, None)
            if result is None:
                continue
            queries = getattr(result, "search_queries_executed", [])
            if not queries:
                continue
            lines = [f"### {agent_name}"]
            for i, q in enumerate(queries, 1):
                lines.append(f"  {i}. {q}")
            sections.append("\n".join(lines))
        if not sections:
            return ""
        return "## Search Queries Executed by Agents\n\n" + "\n\n".join(sections)

    async def _run_adversarial_review(self, synthesis: KYCSynthesisOutput, client, plan: InvestigationPlan) -> None:
        """Run adversarial reviewer on synthesis output for HIGH/CRITICAL risk cases."""
        try:
            from agents.adversarial_reviewer import AdversarialReviewerAgent
            reviewer = AdversarialReviewerAgent()

            # Build client summary
            if isinstance(client, IndividualClient):
                client_summary = f"Individual: {client.full_name}, {client.citizenship}"
            else:
                client_summary = f"Business: {client.legal_name}, {client.industry}"

            es_list = self.evidence_store.to_list() if hasattr(self.evidence_store, 'to_list') else list(self.evidence_store)
            challenges = await reviewer.review(
                synthesis_output=synthesis.model_dump(mode="json"),
                evidence_store=es_list,
                client_summary=client_summary,
            )

            if challenges:
                synthesis.adversarial_challenges = challenges
                self.log(f"  [yellow]Adversarial review: {len(challenges)} challenge(s) raised[/yellow]")
            else:
                self.log("  [dim]Adversarial review: no challenges raised[/dim]")

        except Exception as e:
            self.log(f"  [yellow]Adversarial review skipped: {e}[/yellow]")
            logger.warning(f"Adversarial review failed: {e}")

    async def _run_synthesis(self, client, plan: InvestigationPlan,
                             investigation: InvestigationResults) -> KYCSynthesisOutput | None:
        """Stage 3: Synthesize all findings."""
        try:
            # Build client summary
            if isinstance(client, IndividualClient):
                client_summary = (
                    f"Individual: {client.full_name}\n"
                    f"Citizenship: {client.citizenship}\n"
                    f"Residence: {client.country_of_residence}\n"
                    f"PEP Self-Declaration: {client.pep_self_declaration}\n"
                    f"US Person: {client.us_person}\n"
                )
            else:
                ubo_lines = [f"  - {ubo.full_name} ({ubo.ownership_percentage}%)" for ubo in client.beneficial_owners]
                client_summary = (
                    f"Business: {client.legal_name}\n"
                    f"Industry: {client.industry}\n"
                    f"Countries: {', '.join(client.countries_of_operation)}\n"
                    f"US Nexus: {client.us_nexus}\n"
                    f"Beneficial Owners:\n" + "\n".join(ubo_lines) + "\n"
                )

            # Check PEP EDD expiry (domestic PEP 5-year decay per PCMLTFA)
            pep_edd_expired = False
            if investigation.pep_classification and investigation.pep_classification.edd_expiry_date:
                try:
                    from datetime import datetime
                    expiry = datetime.strptime(
                        investigation.pep_classification.edd_expiry_date[:10], "%Y-%m-%d"
                    )
                    pep_edd_expired = expiry < datetime.now()
                except (ValueError, TypeError):
                    pass

            # Revise risk score with UBO cascade results (business clients)
            revised_risk = plan.preliminary_risk
            if isinstance(client, BusinessClient) and investigation.ubo_screening:
                ubo_scores = {}
                for ubo_name, ubo_data in investigation.ubo_screening.items():
                    # Calculate individual risk score for each UBO
                    score = 0
                    sanctions = ubo_data.get("sanctions", {})
                    if sanctions and sanctions.get(FAILED_SENTINEL_KEY):
                        score += 15  # Conservative: failed screening gets partial risk weight
                    elif sanctions and sanctions.get("disposition") != "CLEAR":
                        score += 30
                    pep = ubo_data.get("pep", {})
                    if pep and pep.get(FAILED_SENTINEL_KEY):
                        score += 15  # Conservative: failed screening gets partial risk weight
                    elif pep and pep.get("detected_level", "NOT_PEP") != "NOT_PEP":
                        score += 25
                    adverse = ubo_data.get("adverse_media", {})
                    if adverse and adverse.get(FAILED_SENTINEL_KEY):
                        score += 10  # Conservative: failed screening gets partial risk weight
                    elif adverse and adverse.get("overall_level", "CLEAR") != "CLEAR":
                        score += 15
                    ubo_scores[ubo_name] = score

                synthesis_factors = []
                revised_risk = revise_risk_score(
                    plan.preliminary_risk,
                    ubo_scores=ubo_scores,
                    synthesis_factors=synthesis_factors,
                    pep_edd_expired=pep_edd_expired,
                )
            elif pep_edd_expired:
                # Individual client with expired PEP — revise without UBO scores
                revised_risk = revise_risk_score(
                    plan.preliminary_risk,
                    pep_edd_expired=True,
                )

            # Build supplementary context for synthesis
            search_query_summary = self._build_search_query_summary(investigation)
            investigation_summary = self._build_investigation_summary(investigation)

            # Scale token budget with evidence complexity (floor guarantees room for decision points)
            self.synthesis_agent.max_tokens = max(
                SYNTHESIS_MIN_TOKENS,
                min(SYNTHESIS_MAX_TOKENS, len(self.evidence_store) * SYNTHESIS_TOKENS_PER_RECORD),
            )

            # Run synthesis agent
            synthesis = await self.synthesis_agent.synthesize(
                evidence_store=self.evidence_store,
                risk_assessment=revised_risk.model_dump(mode="json"),
                client_summary=client_summary,
                search_query_summary=search_query_summary,
                investigation_summary=investigation_summary,
            )

            # Update risk assessment on synthesis output
            synthesis.revised_risk_assessment = revised_risk

            # Run adversarial review for HIGH/CRITICAL risk cases
            risk_level = revised_risk.risk_level.value if revised_risk else "LOW"
            if risk_level in ("HIGH", "CRITICAL"):
                self.log("  [yellow]Running adversarial review (high-risk case)...[/yellow]")
                await self._run_adversarial_review(synthesis, client, plan)

            return synthesis

        except Exception as e:
            self.log(f"  [red]Synthesis error: {e}[/red]")
            logger.exception("Synthesis failed")
            return KYCSynthesisOutput(
                recommended_decision=OnboardingDecision.ESCALATE,
                decision_reasoning=f"Synthesis failed: {e} — escalating for manual review",
                items_requiring_review=["All findings require manual review"],
                senior_management_approval_needed=True,
            )
