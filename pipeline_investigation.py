"""
Investigation mixin for KYC Pipeline.

Handles Stage 2: AI agent execution, UBO cascade, and utility dispatch.
"""

import asyncio
import importlib
import time
from datetime import UTC, datetime

from constants import AGENT_GATHER_TIMEOUT, FAILED_SENTINEL_KEY
from dispatch import AGENT_DISPATCH, AGENT_RESULT_FIELD, UTILITY_DISPATCH, UTILITY_RESULT_FIELD
from logger import get_logger
from models import (
    AdverseMediaResult,
    BusinessClient,
    EntityVerification,
    InvestigationPlan,
    InvestigationResults,
    JurisdictionRiskResult,
    PEPClassification,
    SanctionsResult,
    TransactionMonitoringResult,
)
from pipeline_metrics import AgentMetric
from utilities.audit_trail import log_event as _audit

logger = get_logger(__name__)


class InvestigationMixin:
    """Stage 2 investigation execution."""

    async def _run_investigation(self, client, plan: InvestigationPlan) -> InvestigationResults:
        """Stage 2: Run AI agents and deterministic utilities."""
        results = InvestigationResults()

        # Initialize agent metrics list (consumed by pipeline.py for dashboard)
        if not hasattr(self, '_agent_metrics'):
            self._agent_metrics = []

        # Run AI agents in parallel
        risk_lvl = getattr(plan, 'preliminary_risk', None)
        risk_tag = risk_lvl.risk_level.value if risk_lvl else "?"
        self.log(f"  Running {len(plan.agents_to_run)} agents in parallel (risk: {risk_tag})...")
        tasks = [
            self._run_agent_with_metrics(agent_name, client, plan)
            for agent_name in plan.agents_to_run
        ]
        try:
            outcomes = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=AGENT_GATHER_TIMEOUT,
            )
        except TimeoutError:
            self.log(f"  [red]Agent gather timed out after {AGENT_GATHER_TIMEOUT}s — marking all as failed[/red]")
            logger.error("Agent gather timed out after %ds", AGENT_GATHER_TIMEOUT)
            for agent_name in plan.agents_to_run:
                results.failed_agents.append(agent_name)
                self._store_failed_result(results, agent_name, plan.client_id, "Agent gather timeout")
            results.is_degraded = True
            return results

        for agent_name, outcome in zip(plan.agents_to_run, outcomes, strict=False):
            if isinstance(outcome, Exception):
                self.log(f"  [red]{agent_name} error: {outcome}[/red]")
                logger.exception(f"Agent {agent_name} failed", exc_info=outcome)
                _audit(self.output_dir, plan.client_id, "agent_fail", agent=agent_name, error=str(outcome))
                results.failed_agents.append(agent_name)
                results.is_degraded = True
                # Store failed sentinel so downstream sees PENDING_REVIEW, not None
                self._store_failed_result(results, agent_name, plan.client_id, str(outcome))
                # Record failure evidence so synthesis and review see the gap
                self.evidence_store.append({
                    "evidence_id": f"agent_fail_{agent_name.lower()}",
                    "source_type": "agent",
                    "source_name": agent_name,
                    "entity_screened": plan.client_id,
                    "claim": f"Agent {agent_name} failed: {outcome}",
                    "evidence_level": "U",
                    "supporting_data": [{"error": str(outcome)}],
                    "disposition": "PENDING_REVIEW",
                    "confidence": "LOW",
                    "timestamp": datetime.now(UTC).isoformat(),
                })
            else:
                agent_result, duration = outcome
                self._store_agent_result(results, agent_name, agent_result)
                self._capture_agent_metric(agent_name, duration)
                ev_count = len(agent_result.evidence_records) if hasattr(agent_result, 'evidence_records') and agent_result.evidence_records else 0
                _audit(self.output_dir, plan.client_id, "agent_complete",
                       agent=agent_name, duration_s=round(duration, 1), evidence_records=ev_count)
                self.log(f"  [green]{agent_name} complete ({duration:.1f}s)[/green]")

        # UBO cascade for business clients
        if plan.ubo_cascade_needed and isinstance(client, BusinessClient):
            self.log(f"\n  [bold cyan]UBO Cascade ({len(plan.ubo_names)} owners)[/bold cyan]")
            for ubo in client.beneficial_owners:
                self.log(f"  Screening UBO: {ubo.full_name} ({ubo.ownership_percentage}%)")
                t0 = time.time()
                ubo_results = await self._screen_ubo_parallel(ubo)
                duration = time.time() - t0
                ubo_results["ownership_percentage"] = ubo.ownership_percentage
                results.ubo_screening[ubo.full_name] = ubo_results
                self.log(f"  [green]UBO {ubo.full_name} complete ({duration:.1f}s)[/green]")

        # Run deterministic utilities (pass partial results for EDD/compliance)
        self.log("\n  [bold cyan]Deterministic Utilities[/bold cyan]")
        for util_name in plan.utilities_to_run:
            self.log(f"  Running {util_name}...")
            try:
                result = await self._run_utility(util_name, client, plan, results)
                self._store_utility_result(results, util_name, result)
                self.log(f"  [green]{util_name} complete[/green]")
            except Exception as e:
                self.log(f"  [red]{util_name} error: {e}[/red]")
                logger.exception(f"Utility {util_name} failed")
                results.is_degraded = True
                # Record failure evidence so synthesis knows about the gap
                self.evidence_store.append({
                    "evidence_id": f"util_fail_{util_name}",
                    "source_type": "utility",
                    "source_name": util_name,
                    "entity_screened": plan.client_id,
                    "claim": f"Utility {util_name} failed: {e}",
                    "evidence_level": "U",
                    "supporting_data": [],
                    "disposition": "PENDING_REVIEW",
                    "confidence": "LOW",
                    "timestamp": datetime.now(UTC).isoformat(),
                })

        return results

    async def _run_agent_with_metrics(self, agent_name: str, client, plan: InvestigationPlan):
        """Run a single agent and return (result, duration). Exceptions propagate."""
        t0 = time.time()
        result = await self._run_agent(agent_name, client, plan)
        duration = time.time() - t0
        return result, duration

    async def _run_agent(self, agent_name: str, client, plan: InvestigationPlan):
        """Dispatch to the correct agent via dispatch table."""
        if agent_name not in AGENT_DISPATCH:
            raise ValueError(f"Unknown agent: {agent_name}")
        agent_attr, kwargs_fn = AGENT_DISPATCH[agent_name]
        agent = getattr(self, agent_attr)
        kwargs = kwargs_fn(client, plan)
        # JurisdictionRisk uses a positional arg, not kwargs
        positional = kwargs.pop("_positional_arg", None)
        if positional is not None:
            return await agent.research(positional)
        return await agent.research(**kwargs)

    async def _screen_ubo_parallel(self, ubo) -> dict:
        """Screen a single UBO with sanctions + PEP + adverse media in parallel."""
        ubo_results = {}
        context = f"UBO ({ubo.ownership_percentage}% owner)"

        async def _safe_ubo_task(key: str, coro):
            """Wrap a UBO screening coroutine so the key is always returned.

            Returns (key, result, None) on success or (key, None, exception) on failure.
            This eliminates the fragile reliance on positional index mapping.
            """
            try:
                result = await coro
                return key, result, None
            except Exception as e:
                return key, None, e

        try:
            outcomes = await asyncio.wait_for(
                asyncio.gather(
                    _safe_ubo_task("sanctions", self.individual_sanctions_agent.research(
                        full_name=ubo.full_name,
                        date_of_birth=ubo.date_of_birth,
                        citizenship=ubo.citizenship,
                        context=context,
                    )),
                    _safe_ubo_task("pep", self.pep_detection_agent.research(
                        full_name=ubo.full_name,
                        citizenship=ubo.citizenship,
                        pep_self_declaration=ubo.pep_self_declaration,
                    )),
                    _safe_ubo_task("adverse_media", self.individual_adverse_media_agent.research(
                        full_name=ubo.full_name,
                        citizenship=ubo.citizenship,
                    )),
                ),
                timeout=AGENT_GATHER_TIMEOUT,
            )
        except TimeoutError:
            logger.error("UBO screening timed out for %s after %ds", ubo.full_name, AGENT_GATHER_TIMEOUT)
            for key in ("sanctions", "pep", "adverse_media"):
                ubo_results[key] = {FAILED_SENTINEL_KEY: True, "error": "UBO screening timeout", "disposition": "PENDING_REVIEW"}
            return ubo_results

        for key, result, error in outcomes:
            if error is not None:
                logger.error(f"UBO screening failed for {ubo.full_name} ({key}): {error}")
                # Store failure sentinel so downstream sees "Error", not missing key
                ubo_results[key] = {
                    FAILED_SENTINEL_KEY: True,
                    "error": str(error),
                    "disposition": "PENDING_REVIEW",
                }
                # Record failure evidence so the gap is visible
                ubo_slug = ubo.full_name[:10].lower().replace(' ', '_')
                self.evidence_store.append({
                    "evidence_id": f"ubo_fail_{ubo_slug}_{key}",
                    "source_type": "agent",
                    "source_name": "UBOScreening",
                    "entity_screened": ubo.full_name,
                    "entity_context": context,
                    "claim": f"UBO {key} screening failed: {error}",
                    "evidence_level": "U",
                    "supporting_data": [],
                    "disposition": "PENDING_REVIEW",
                    "confidence": "LOW",
                    "timestamp": datetime.now(UTC).isoformat(),
                })
                continue
            ubo_results[key] = result.model_dump(mode="json") if result else None
            if result and hasattr(result, 'evidence_records') and result.evidence_records:
                for er in result.evidence_records:
                    er.entity_context = context
                    self.evidence_store.append(er.model_dump(mode="json"))

        return ubo_results

    async def _run_utility(self, util_name: str, client, plan: InvestigationPlan,
                           investigation: InvestigationResults = None):
        """Dispatch to the correct utility via dispatch table."""
        if util_name not in UTILITY_DISPATCH:
            raise ValueError(f"Unknown utility: {util_name}")
        module_path, func_name, args_fn = UTILITY_DISPATCH[util_name]
        module = importlib.import_module(module_path)
        func = getattr(module, func_name)
        args, kwargs = args_fn(client, plan, investigation)
        return func(*args, **kwargs)

    def _store_agent_result(self, results: InvestigationResults, agent_name: str, result):
        """Store agent result in the appropriate field and update evidence store."""
        field = AGENT_RESULT_FIELD.get(agent_name)
        if field:
            setattr(results, field, result)

        # Add evidence records to central store
        if hasattr(result, 'evidence_records') and result.evidence_records:
            for er in result.evidence_records:
                self.evidence_store.append(er.model_dump(mode="json") if hasattr(er, 'model_dump') else er)

    def _store_utility_result(self, results: InvestigationResults, util_name: str, result: dict):
        """Store utility result and update evidence store."""
        field = UTILITY_RESULT_FIELD.get(util_name)
        if field:
            setattr(results, field, result)

        # Add evidence records from utility (utilities use "evidence" key)
        if isinstance(result, dict):
            evidence = result.get("evidence_records") or result.get("evidence") or []
            self.evidence_store.extend(evidence)

    # Maps agent name → (result field, model class, entity extractor)
    _FAILED_RESULT_MAP: dict = {
        "IndividualSanctions": ("individual_sanctions", SanctionsResult),
        "EntitySanctions": ("entity_sanctions", SanctionsResult),
        "PEPDetection": ("pep_classification", PEPClassification),
        "IndividualAdverseMedia": ("individual_adverse_media", AdverseMediaResult),
        "BusinessAdverseMedia": ("business_adverse_media", AdverseMediaResult),
        "EntityVerification": ("entity_verification", EntityVerification),
        "JurisdictionRisk": ("jurisdiction_risk", JurisdictionRiskResult),
        "TransactionMonitoring": ("transaction_monitoring", TransactionMonitoringResult),
    }

    def _store_failed_result(self, results: InvestigationResults, agent_name: str,
                             client_id: str, error: str):
        """Store a failed sentinel result so downstream sees PENDING_REVIEW, not None."""
        entry = self._FAILED_RESULT_MAP.get(agent_name)
        if not entry:
            return
        field_name, model_cls = entry
        sentinel = model_cls.failed(entity=client_id, error=error)
        setattr(results, field_name, sentinel)

    def _capture_agent_metric(self, agent_name: str, duration: float):
        """Capture metrics from the agent that just ran."""
        # Map agent names to their attribute names on self
        agent_attr_map = {
            name: attr for name, (attr, _) in AGENT_DISPATCH.items()
        }
        attr = agent_attr_map.get(agent_name)
        if not attr:
            return

        agent = getattr(self, attr, None)
        if not agent:
            return

        usage = getattr(agent, '_last_usage', {})
        stats = getattr(agent, 'search_stats', {})
        metric = AgentMetric(
            name=agent_name,
            model=agent.model,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            web_searches=stats.get("web_search_count", 0),
            web_fetches=stats.get("web_fetch_count", 0),
            duration_seconds=duration,
        )
        self._agent_metrics.append(metric)

