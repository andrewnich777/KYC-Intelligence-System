"""
KYC Pipeline Orchestrator

Runs the 5-stage KYC pipeline:
1. Intake & Classification (deterministic)
2. Investigation (AI agents + deterministic utilities)
3. Synthesis & Proto-Reports (Opus AI)
4. Conversational Review (pause for human)
5. Final Reports (generators + PDF)
"""

import json
import time
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console

from logger import get_logger
from pipeline_metrics import AgentMetric, PipelineMetrics, StageMetric, display_metrics, save_metrics

logger = get_logger(__name__)

from agents import (
    BusinessAdverseMediaAgent,
    EntitySanctionsAgent,
    EntityVerificationAgent,
    IndividualAdverseMediaAgent,
    IndividualSanctionsAgent,
    JurisdictionRiskAgent,
    KYCSynthesisAgent,
    PEPDetectionAgent,
    TransactionMonitoringAgent,
)
from evidence_store import EvidenceStore
from models import (
    BusinessClient,
    ClientType,
    IndividualClient,
    InvestigationPlan,
    InvestigationResults,
    KYCOutput,
    KYCSynthesisOutput,
    OnboardingDecision,
    ReviewSession,
)
from pipeline_checkpoint import CheckpointMixin
from pipeline_investigation import InvestigationMixin
from pipeline_reports import ReportsMixin
from pipeline_review import ReviewMixin
from pipeline_synthesis import SynthesisMixin
from tools.screening_list import clear_screening_cache
from tools.tool_definitions import clear_fetch_cache, close_shared_client
from utilities.audit_trail import log_event as _audit
from utilities.investigation_planner import build_investigation_plan
from utilities.review_intelligence import compute_review_intelligence

console = Console(force_terminal=True, legacy_windows=True)


class KYCPipeline(CheckpointMixin, InvestigationMixin, SynthesisMixin, ReportsMixin, ReviewMixin):
    """Orchestrates the full KYC pipeline for client onboarding."""

    def __init__(self, output_dir: str = "results", verbose: bool = True, resume: bool = False,
                 interactive: bool = True):
        self.output_dir = Path(output_dir)
        self.verbose = verbose
        self.resume = resume
        self.interactive = interactive
        self.checkpoint = {}
        self.checkpoint_path = None

        # Initialize AI agents
        self.individual_sanctions_agent = IndividualSanctionsAgent()
        self.pep_detection_agent = PEPDetectionAgent()
        self.individual_adverse_media_agent = IndividualAdverseMediaAgent()
        self.entity_verification_agent = EntityVerificationAgent()
        self.entity_sanctions_agent = EntitySanctionsAgent()
        self.business_adverse_media_agent = BusinessAdverseMediaAgent()
        self.jurisdiction_risk_agent = JurisdictionRiskAgent()
        self.transaction_monitoring_agent = TransactionMonitoringAgent()
        self.synthesis_agent = KYCSynthesisAgent()

        # Evidence store — central truth for all findings
        self.evidence_store = EvidenceStore()

    def log(self, message: str, style: str = ""):
        """Log a message if verbose mode is on."""
        if self.verbose:
            console.print(message, style=style)

    # =========================================================================
    # Main Pipeline
    # =========================================================================

    async def run(self, client_data: dict) -> KYCOutput:
        """Run the full KYC pipeline for a client."""
        # Clear module-level caches from any prior run in the same process.
        # Without this, batch mode contaminates later clients with earlier
        # clients' cached web fetches and screening list results.
        clear_fetch_cache()
        clear_screening_cache()
        try:
            return await self._run_inner(client_data)
        finally:
            await close_shared_client()

    async def _run_inner(self, client_data: dict) -> KYCOutput:
        """Inner pipeline logic, wrapped by run() for connection cleanup."""
        start_time = datetime.now()

        # Parse client type
        client_type = client_data.get("client_type", "individual")
        if client_type == "individual":
            client = IndividualClient(**client_data)
        else:
            client = BusinessClient(**client_data)

        # Initialize stage timing
        self._stage_timings: list[StageMetric] = []
        self._agent_metrics: list[AgentMetric] = []

        # Stage 1: Intake & Classification
        self.log("\n[bold blue]Stage 1: Intake & Classification[/bold blue]")
        t_stage = time.time()
        plan = await self._run_intake(client)
        client_id = plan.client_id

        # Load checkpoint
        self.checkpoint = self._load_checkpoint(client_id)
        completed_stage = self.checkpoint.get("completed_stage", 0)

        # Save Stage 1
        self._save_stage_results(client_id, "01_intake", {
            "classification": plan.preliminary_risk.model_dump(mode="json"),
            "investigation_plan": plan.model_dump(mode="json"),
        })

        # Save client data to checkpoint for finalize() recovery
        self.checkpoint["client_data"] = client_data

        self.log(f"  Client ID: {client_id}")
        risk_colors = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red", "CRITICAL": "bold red"}
        _rl = plan.preliminary_risk.risk_level.value
        _rc = risk_colors.get(_rl, "white")
        self.log(f"  Risk Level: [{_rc}]{_rl}[/{_rc}] ({plan.preliminary_risk.total_score} pts)")
        self.log(f"  Regulations: {', '.join(plan.applicable_regulations)}")
        self.log(f"  Agents: {', '.join(plan.agents_to_run)}")
        if plan.ubo_cascade_needed:
            self.log(f"  UBO Cascade: {', '.join(plan.ubo_names)}")

        self._stage_timings.append(StageMetric("1. Intake & Classification", time.time() - t_stage))
        _audit(self.output_dir, client_id, "stage_complete", stage=1,
               risk_level=plan.preliminary_risk.risk_level.value,
               risk_score=plan.preliminary_risk.total_score)

        # Pre-flight freshness check (non-blocking)
        try:
            from utilities.reference_data_updater import check_staleness
            staleness_warning = check_staleness()
            if staleness_warning:
                self.log(f"  [yellow]Warning: {staleness_warning}[/yellow]")
        except Exception:
            pass  # Non-critical

        # Propagate risk level to all agents so tool limits scale
        # (HIGH → 1.5x, CRITICAL → 2x tool calls)
        risk_level = plan.preliminary_risk.risk_level.value
        for agent in (
            self.individual_sanctions_agent, self.pep_detection_agent,
            self.individual_adverse_media_agent, self.entity_verification_agent,
            self.entity_sanctions_agent, self.business_adverse_media_agent,
            self.jurisdiction_risk_agent, self.transaction_monitoring_agent,
            self.synthesis_agent,
        ):
            agent._risk_level = risk_level

        # Stage 2: Investigation
        t_stage = time.time()
        if completed_stage < 2:
            self.log("\n[bold blue]Stage 2: Investigation[/bold blue]")
            _audit(self.output_dir, client_id, "stage_start", stage=2, name="Investigation")
            investigation = await self._run_investigation(client, plan)
            self.checkpoint["completed_stage"] = 2
            self.checkpoint["investigation"] = self._serialize_investigation(investigation)
            self._save_checkpoint(client_id, self.checkpoint)
        else:
            self.log("\n[bold blue]Stage 2: Investigation[/bold blue] [green](cached)[/green]")
            investigation = self._deserialize_investigation(self.checkpoint.get("investigation", {}))
            # Restore evidence store from saved file
            self._load_evidence_store(client_id)

        # Save evidence store + stats in checkpoint
        self._save_evidence_store(client_id)
        self.checkpoint["evidence_stats"] = {
            "total": len(self.evidence_store),
            "by_level": self.evidence_store.count_by_level(),
        }
        _audit(self.output_dir, client_id, "stage_complete", stage=2,
               evidence_count=len(self.evidence_store),
               failed_agents=investigation.failed_agents)
        self._stage_timings.append(StageMetric("2. Investigation", time.time() - t_stage))

        # Stage 3: Synthesis
        t_stage = time.time()
        if completed_stage < 3:
            self.log("\n[bold blue]Stage 3: Synthesis & Proto-Reports[/bold blue]")
            _audit(self.output_dir, client_id, "stage_start", stage=3, name="Synthesis")
            synthesis = await self._run_synthesis(client, plan, investigation)
            # Propagate synthesis failure to is_degraded (specific signals only)
            _reasoning = (synthesis.decision_reasoning or "").lower() if synthesis else ""
            _failure_signals = ("synthesis failed", "unable to synthesize", "synthesis error")
            if synthesis and any(sig in _reasoning for sig in _failure_signals):
                investigation.is_degraded = True
            self.checkpoint["completed_stage"] = 3
            self.checkpoint["synthesis"] = synthesis.model_dump(mode="json") if synthesis else None
            self._save_checkpoint(client_id, self.checkpoint)
        else:
            self.log("\n[bold blue]Stage 3: Synthesis[/bold blue] [green](cached)[/green]")
            synth_data = self.checkpoint.get("synthesis")
            synthesis = KYCSynthesisOutput(**synth_data) if synth_data else None

        # Compute Review Intelligence (deterministic pass between Synthesis and Review)
        review_intel = compute_review_intelligence(
            evidence_store=self.evidence_store,
            synthesis=synthesis,
            plan=plan,
            investigation=investigation,
        )
        self._save_review_intelligence(client_id, review_intel)
        self.checkpoint["review_intelligence"] = review_intel.model_dump(mode="json") if review_intel else None
        self._save_checkpoint(client_id, self.checkpoint)
        # Save Stage 3 outputs (with review intelligence for proto-briefs)
        self._save_stage3_outputs(client_id, synthesis, plan, review_intelligence=review_intel)

        _audit(self.output_dir, client_id, "stage_complete", stage=3,
               decision=synthesis.recommended_decision.value if synthesis else None)
        self._stage_timings.append(StageMetric("3. Synthesis & Review Intel", time.time() - t_stage))

        # Display executive summary, review intelligence, THEN decision points
        self._display_executive_summary(
            client, plan, synthesis, investigation, self.evidence_store,
        )
        self._display_review_intelligence(review_intel)
        self._display_decision_points(synthesis)

        # Build preliminary KYCOutput for report generators that need it
        self._kyc_output = KYCOutput(
            client_id=client_id,
            client_type=ClientType(client_type),
            client_data=client_data,
            intake_classification=plan,
            investigation_results=investigation,
            synthesis=synthesis,
            review_intelligence=review_intel,
            review_session=ReviewSession(client_id=client_id),
            final_decision=synthesis.recommended_decision if synthesis else None,
            is_degraded=investigation.is_degraded,
            generated_at=datetime.now(),
        )

        # Stage 4: Review
        t_stage = time.time()
        if self.interactive:
            # Interactive review loop — officer asks questions, approves dispositions
            review_session, synthesis, review_intel = await self._run_interactive_review(
                client_id, synthesis, plan, review_intel, self.evidence_store,
                client=client, investigation=investigation,
            )

            # Update preliminary output with ALL review results
            self._kyc_output.review_session = review_session
            self._kyc_output.synthesis = synthesis
            self._kyc_output.review_intelligence = review_intel
            self._kyc_output.is_degraded = investigation.is_degraded
            self._kyc_output.final_decision = synthesis.recommended_decision if synthesis else None

            # Stage 5: Final Reports (runs immediately after finalize)
            if review_session.finalized:
                self.log("\n[bold blue]Stage 5: Final Reports[/bold blue]")
                _audit(self.output_dir, client_id, "stage_start", stage=5, name="Final Reports")
                await self._run_final_reports(
                    client_id, synthesis, plan, review_session, investigation,
                    review_intelligence=review_intel,
                )
                self._save_review_session(client_id, review_session)
        else:
            # Non-interactive: auto-generate final reports without review
            self.log("\n[bold yellow]Stage 4: Review (non-interactive)[/bold yellow]")
            review_session = ReviewSession(client_id=client_id)
            review_session.finalized = True
            review_session.finalized_at = datetime.now(UTC)
            self._kyc_output.review_session = review_session
            self._save_review_session(client_id, review_session)

            self.log("\n[bold blue]Stage 5: Final Reports[/bold blue]")
            await self._run_final_reports(
                client_id, synthesis, plan, review_session, investigation,
                review_intelligence=review_intel,
            )

        self._stage_timings.append(StageMetric("4. Review" + (" + 5. Reports" if (self.interactive and review_session.finalized) else ""), time.time() - t_stage))

        # Capture synthesis agent metrics
        synth_usage = getattr(self.synthesis_agent, '_last_usage', {})
        if synth_usage.get("input_tokens", 0) > 0:
            self._agent_metrics.append(AgentMetric(
                name="KYCSynthesis",
                model=self.synthesis_agent.model,
                input_tokens=synth_usage.get("input_tokens", 0),
                output_tokens=synth_usage.get("output_tokens", 0),
            ))

        # Build and display pipeline metrics
        metrics = PipelineMetrics(
            stages=self._stage_timings,
            agents=self._agent_metrics,
        )

        # Populate evidence quality from review intelligence
        if review_intel and review_intel.confidence:
            conf = review_intel.confidence
            metrics.evidence_grade = conf.overall_confidence_grade
            metrics.evidence_total = len(self.evidence_store)
            total = metrics.evidence_total or 1
            metrics.evidence_verified = round(conf.verified_pct * total / 100)
            metrics.evidence_sourced = round(conf.sourced_pct * total / 100)
            metrics.evidence_inferred = round(conf.inferred_pct * total / 100)
            metrics.evidence_unknown = round(conf.unknown_pct * total / 100)

        display_metrics(metrics, console)
        save_metrics(metrics, self.output_dir, client_id)

        # Calculate duration
        duration = (datetime.now() - start_time).total_seconds()

        # Auto-record outcome for feedback tracking
        try:
            from utilities.feedback_tracker import record_outcome
            _decision = synthesis.recommended_decision.value if synthesis else "PENDING"
            _rl = risk_level if isinstance(risk_level, str) else None
            _rs = plan.preliminary_risk.total_score if plan and plan.preliminary_risk else None
            record_outcome(
                client_id, _decision,
                output_dir=str(self.output_dir),
                risk_level=_rl,
                risk_score=_rs,
            )
        except Exception:
            pass  # Non-critical

        # Build output — carry over SAR/filing data generated during Stage 5
        output = KYCOutput(
            client_id=client_id,
            client_type=ClientType(client_type),
            client_data=client_data,
            intake_classification=plan,
            investigation_results=investigation,
            synthesis=synthesis,
            review_intelligence=review_intel,
            review_session=review_session,
            final_decision=synthesis.recommended_decision if synthesis else None,
            is_degraded=investigation.is_degraded,
            sar_narrative_draft=getattr(self._kyc_output, 'sar_narrative_draft', None),
            fincen_filing=getattr(self._kyc_output, 'fincen_filing', None),
            fintrac_filing=getattr(self._kyc_output, 'fintrac_filing', None),
            metrics=metrics.to_dict(),
            generated_at=datetime.now(),
            duration_seconds=duration,
        )

        return output

    async def finalize(self, results_dir: str) -> KYCOutput:
        """Finalize a paused review session and generate final reports."""
        try:
            return await self._finalize_inner(results_dir)
        finally:
            await close_shared_client()

    async def _finalize_inner(self, results_dir: str) -> KYCOutput:
        """Inner finalize logic, wrapped by finalize() for connection cleanup."""
        results_path = Path(results_dir)
        client_id = results_path.name

        self.log("\n[bold blue]Stage 5: Final Reports[/bold blue]")
        self.log(f"  Finalizing: {client_id}")

        # Load checkpoint
        cp_path = results_path / "checkpoint.json"
        if not cp_path.exists():
            raise ValueError(f"No checkpoint found at {results_dir}")

        checkpoint = json.loads(cp_path.read_text(encoding="utf-8"))

        # Load review session
        review_path = results_path / "04_review" / "review_session.json"
        review_session = None
        if review_path.exists():
            review_data = json.loads(review_path.read_text(encoding="utf-8"))
            review_session = ReviewSession(**review_data)
            review_session.finalized = True
            review_session.finalized_at = datetime.now()

        # Load synthesis
        synth_data = checkpoint.get("synthesis")
        synthesis = KYCSynthesisOutput(**synth_data) if synth_data else None

        # Load investigation plan
        intake_path = results_path / "01_intake" / "investigation_plan.json"
        plan_data = json.loads(intake_path.read_text(encoding="utf-8")) if intake_path.exists() else {}
        plan = InvestigationPlan(**plan_data) if plan_data else None

        # Load client data from checkpoint
        client_data = checkpoint.get("client_data", {})

        # Deserialize investigation results from checkpoint
        inv_data = checkpoint.get("investigation", {})
        investigation = self._deserialize_investigation(inv_data) if inv_data else InvestigationResults()

        # Check for unresolved decision points
        if synthesis and synthesis.decision_points:
            unresolved = [
                dp for dp in synthesis.decision_points
                if dp.officer_selection is None
            ]
            if unresolved:
                for dp in unresolved:
                    self.log(f"  [bold yellow]Unresolved decision point: {dp.title}[/bold yellow]")
                self.log(f"  [yellow]{len(unresolved)} decision point(s) without officer selection — "
                         f"recording as pending in audit trail[/yellow]")

        # Apply deterministic recommendation engine as safety net
        final_decision = synthesis.recommended_decision if synthesis else None
        if plan and synthesis:
            from generators.recommendation_engine import recommend_decision
            risk_assessment = synthesis.revised_risk_assessment or plan.preliminary_risk
            decision, reasoning, conditions = recommend_decision(risk_assessment, investigation)
            # Deterministic rules override AI for hard blocks (sanctions = DECLINE)
            if decision == OnboardingDecision.DECLINE:
                final_decision = OnboardingDecision.DECLINE
                self.log(f"  [bold red]Deterministic override: DECLINE ({reasoning})[/bold red]")

        # Load review intelligence (try checkpoint first, then JSON file)
        review_intel = None
        ri_checkpoint = checkpoint.get("review_intelligence")
        if ri_checkpoint:
            try:
                from models import ReviewIntelligence
                review_intel = ReviewIntelligence(**ri_checkpoint)
            except Exception as e:
                logger.warning(f"Could not load review intelligence from checkpoint: {e}")
        if review_intel is None:
            ri_path = results_path / "03_synthesis" / "review_intelligence.json"
            if ri_path.exists():
                try:
                    from models import ReviewIntelligence
                    ri_data = json.loads(ri_path.read_text(encoding="utf-8"))
                    review_intel = ReviewIntelligence(**ri_data)
                except Exception as e:
                    logger.warning(f"Could not load review intelligence from file: {e}")

        # Build preliminary output for report generators
        self._kyc_output = KYCOutput(
            client_id=client_id,
            client_type=ClientType(client_data.get("client_type", "individual")),
            client_data=client_data,
            intake_classification=plan or InvestigationPlan(client_type=ClientType.INDIVIDUAL, client_id=client_id),
            investigation_results=investigation,
            synthesis=synthesis,
            review_intelligence=review_intel,
            review_session=review_session,
            final_decision=final_decision,
            generated_at=datetime.now(),
        )

        # Generate final reports
        await self._run_final_reports(client_id, synthesis, plan, review_session, investigation,
                                      review_intelligence=review_intel)

        # Save finalized review session
        if review_session:
            self._save_review_session(client_id, review_session)

        duration = 0.0
        output = KYCOutput(
            client_id=client_id,
            client_type=ClientType(client_data.get("client_type", "individual")),
            client_data=client_data,
            intake_classification=plan or InvestigationPlan(
                client_type=ClientType(client_data.get("client_type", "individual")),
                client_id=client_id,
            ),
            investigation_results=investigation,
            synthesis=synthesis,
            review_intelligence=review_intel,
            review_session=review_session,
            final_decision=final_decision,
            is_degraded=investigation.is_degraded if investigation else False,
            sar_narrative_draft=getattr(self._kyc_output, 'sar_narrative_draft', None) if self._kyc_output else None,
            fincen_filing=getattr(self._kyc_output, 'fincen_filing', None) if self._kyc_output else None,
            fintrac_filing=getattr(self._kyc_output, 'fintrac_filing', None) if self._kyc_output else None,
            generated_at=datetime.now(),
            duration_seconds=duration,
        )

        self.log("\n[bold green]Finalization complete[/bold green]")
        return output

    # =========================================================================
    # Stage 1: Intake & Classification
    # =========================================================================

    async def _run_intake(self, client) -> InvestigationPlan:
        """Stage 1: Classify client and build investigation plan."""
        plan = build_investigation_plan(client)
        return plan
