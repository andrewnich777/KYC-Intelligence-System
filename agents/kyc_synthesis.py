"""
KYC Synthesis Agent.
Cross-references all findings, detects contradictions, recommends decision.
Uses Opus 4.6 for complex reasoning.
"""

import json

from agents.base import BaseAgent, load_prompt_template
from logger import get_logger
from models import (
    CounterArgument,
    DecisionOption,
    DecisionPoint,
    KYCEvidenceGraph,
    KYCSynthesisOutput,
    OnboardingDecision,
)
from utilities.ai_coercion import (
    coerce_bool,
    coerce_contradictions,
    coerce_list,
    coerce_str_list,
)

logger = get_logger(__name__)


class KYCSynthesisAgent(BaseAgent):
    """Cross-reference all KYC findings and recommend onboarding decision."""

    @property
    def name(self) -> str:
        return "KYCSynthesis"

    @property
    def system_prompt(self) -> str:
        return load_prompt_template("kyc_synthesis")

    @property
    def tools(self) -> list[str]:
        return []  # Pure reasoning, no tools

    @staticmethod
    def _compute_evidence_graph(evidence_store) -> KYCEvidenceGraph:
        """Deterministically compute evidence graph from the evidence store.

        Uses EvidenceStore.compute_evidence_graph() if available, otherwise
        falls back to manual counting for plain list[dict].
        """
        if hasattr(evidence_store, 'compute_evidence_graph'):
            return evidence_store.compute_evidence_graph()
        counts = {"V": 0, "S": 0, "I": 0, "U": 0}
        for record in evidence_store:
            level = record.get("evidence_level", "U") if isinstance(record, dict) else "U"
            if level in counts:
                counts[level] += 1
            else:
                counts["U"] += 1
        return KYCEvidenceGraph(
            total_evidence_records=len(evidence_store),
            verified_count=counts["V"],
            sourced_count=counts["S"],
            inferred_count=counts["I"],
            unknown_count=counts["U"],
        )

    async def synthesize(self, evidence_store: list[dict],
                         risk_assessment: dict,
                         client_summary: str,
                         search_query_summary: str = "",
                         investigation_summary: str = "") -> KYCSynthesisOutput:
        """Synthesize all evidence and recommend a decision."""
        es_list = evidence_store.to_list() if hasattr(evidence_store, 'to_list') else list(evidence_store)
        evidence_json = json.dumps(es_list, indent=2, default=str)

        search_section = ""
        if search_query_summary:
            search_section = f"""

{search_query_summary}

Use the above search queries to evaluate investigation thoroughness. Flag any gaps
where important searches were not performed or where additional queries would be warranted.
"""

        investigation_section = ""
        if investigation_summary:
            investigation_section = f"""

{investigation_summary}

The above contains the FULL investigation results from all agents and utilities.
Use this data to identify specific documents, actions, and requirements — not just summary counts.
"""

        prompt = f"""Synthesize all KYC screening results and recommend an onboarding decision.

## Client Summary
{client_summary}

## Current Risk Assessment
Risk Level: {risk_assessment.get('risk_level', 'UNKNOWN')}
Risk Score: {risk_assessment.get('total_score', 0)}
Risk Factors: {json.dumps(risk_assessment.get('risk_factors', []), default=str)}

## Evidence Store ({len(evidence_store)} records)
{evidence_json}
{search_section}{investigation_section}
Analyze ALL evidence records and investigation results. Cross-reference findings.
Identify contradictions. Reference specific documents, actions, and requirements by name.
Then recommend APPROVE, CONDITIONAL, ESCALATE, or DECLINE with detailed reasoning.

IMPORTANT: Distinguish between risk-based concerns (sanctions hits, PEP status, adverse media)
and procedural items (outstanding documents, pending verifications). Procedural items alone
should result in CONDITIONAL (with conditions), not ESCALATE."""

        self._last_evidence_store = evidence_store
        result = await self.run(prompt)
        return self._parse_result(result)

    def _parse_result(self, result: dict) -> KYCSynthesisOutput:
        data = result.get("json", {})
        if not data:
            return KYCSynthesisOutput(
                recommended_decision=OnboardingDecision.ESCALATE,
                decision_reasoning="Synthesis agent did not return structured data — escalating for manual review",
                items_requiring_review=["All findings require manual review"],
                senior_management_approval_needed=True,
            )

        decision = OnboardingDecision.ESCALATE
        try:
            raw_decision = data.get("recommended_decision", "ESCALATE")
            if not isinstance(raw_decision, str):
                raw_decision = str(raw_decision)
            decision = OnboardingDecision(raw_decision.upper())
        except (ValueError, AttributeError):
            pass

        # Deterministic evidence graph — override AI's unreliable counts
        evidence_store = getattr(self, '_last_evidence_store', [])
        graph = self._compute_evidence_graph(evidence_store)

        # Preserve AI's qualitative findings (contradictions, corroborations)
        graph_data = data.get("evidence_graph", {})
        if isinstance(graph_data, dict):
            graph.contradictions = coerce_contradictions(graph_data.get("contradictions", []))
            graph.corroborations = coerce_list(graph_data.get("corroborations", []))
            graph.unresolved_items = coerce_list(graph_data.get("unresolved_items", []))

        # Parse decision points
        decision_points = []
        raw_decision_points = data.get("decision_points", [])
        if not isinstance(raw_decision_points, list):
            raw_decision_points = []
        for dp_data in raw_decision_points:
            if not isinstance(dp_data, dict):
                continue
            try:
                ca_data = dp_data.get("counter_argument", {})
                if not isinstance(ca_data, dict):
                    ca_data = {}
                counter_arg = CounterArgument(
                    evidence_id=str(ca_data.get("evidence_id", "")),
                    disposition_challenged=str(ca_data.get("disposition_challenged", "")),
                    argument=str(ca_data.get("argument", "")),
                    risk_if_wrong=str(ca_data.get("risk_if_wrong", "")),
                    recommended_mitigations=coerce_str_list(ca_data.get("recommended_mitigations", [])),
                )

                options = []
                raw_options = dp_data.get("options", [])
                if not isinstance(raw_options, list):
                    raw_options = []
                for opt_data in raw_options:
                    if not isinstance(opt_data, dict):
                        continue
                    options.append(DecisionOption(
                        option_id=str(opt_data.get("option_id", "")),
                        label=str(opt_data.get("label", "")),
                        description=str(opt_data.get("description", "")),
                        consequences=coerce_str_list(opt_data.get("consequences", [])),
                        onboarding_impact=str(opt_data.get("onboarding_impact", "")),
                        timeline=str(opt_data.get("timeline", "")),
                    ))

                confidence_raw = dp_data.get("confidence", 0.0)
                try:
                    confidence_val = float(confidence_raw)
                except (ValueError, TypeError):
                    confidence_val = 0.0

                decision_points.append(DecisionPoint(
                    decision_id=str(dp_data.get("decision_id", f"dp_{len(decision_points)}")),
                    title=str(dp_data.get("title", "")),
                    context_summary=str(dp_data.get("context_summary", "")),
                    disposition=str(dp_data.get("disposition", "")),
                    confidence=confidence_val,
                    counter_argument=counter_arg,
                    options=options,
                ))
            except Exception as e:
                logger.warning(f"Could not parse decision point: {e}")

        return KYCSynthesisOutput(
            evidence_graph=graph,
            key_findings=coerce_str_list(data.get("key_findings", [])),
            contradictions=coerce_contradictions(data.get("contradictions", [])),
            risk_elevations=coerce_list(data.get("risk_elevations", [])),
            recommended_decision=decision,
            decision_reasoning=str(data.get("decision_reasoning", "")),
            conditions=coerce_str_list(data.get("conditions", [])),
            items_requiring_review=coerce_str_list(data.get("items_requiring_review", [])),
            senior_management_approval_needed=coerce_bool(data.get("senior_management_approval_needed", False)),
            decision_points=decision_points,
        )
