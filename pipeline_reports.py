"""
Reports mixin for KYC Pipeline.

Handles brief generation (proto and final), file I/O, and decision point display.
"""

import json
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from evidence_store import EvidenceStore
from logger import get_logger
from models import (
    ClientType,
    InvestigationPlan,
    InvestigationResults,
    KYCSynthesisOutput,
    ReviewIntelligence,
    ReviewSession,
)
from utilities.file_ops import atomic_write_json, atomic_write_text

logger = get_logger(__name__)

console = Console(force_terminal=True, legacy_windows=True)


# Brief generator table: (module_path, function_name, output_filename, accepts_extra_kwargs)
# All generators accept: client_id, synthesis, plan
# "extra_kwargs" lists additional keyword args the generator accepts
BRIEF_GENERATORS = [
    (
        "generators.aml_operations_brief",
        "generate_aml_operations_brief",
        "aml_operations_brief",
        {"evidence_store", "review_session", "investigation", "review_intelligence"},
    ),
    (
        "generators.risk_assessment_brief",
        "generate_risk_assessment_brief",
        "risk_assessment_brief",
        {"investigation"},
    ),
    (
        "generators.regulatory_actions_brief",
        "generate_regulatory_actions_brief",
        "regulatory_actions_brief",
        {"investigation", "review_intelligence"},
    ),
    (
        "generators.onboarding_summary",
        "generate_onboarding_summary",
        "onboarding_decision_brief",
        {"investigation", "review_intelligence"},
    ),
]


class ReportsMixin:
    """Report generation and file I/O."""

    def _generate_briefs(
        self,
        output_dir: Path,
        client_id: str,
        synthesis,
        plan,
        *,
        prefix: str = "",
        evidence_store=None,
        review_session=None,
        investigation: InvestigationResults = None,
        review_intelligence: ReviewIntelligence = None,
        generate_pdfs: bool = False,
        risk_level: str = None,
    ):
        """Generate department-targeted briefs.

        Args:
            output_dir: Directory to write files into.
            client_id: Client identifier.
            synthesis: KYCSynthesisOutput.
            plan: InvestigationPlan.
            prefix: Filename prefix (e.g. "proto_" for stage 3).
            evidence_store: Evidence records list (for AML brief).
            review_session: ReviewSession (for AML brief, final only).
            investigation: InvestigationResults (for final briefs).
            review_intelligence: ReviewIntelligence (for enhanced briefs).
            generate_pdfs: Whether to also generate PDFs.
            risk_level: Risk level string for PDF headers.
        """
        import importlib

        output_dir.mkdir(parents=True, exist_ok=True)

        # Build pool of available extra kwargs
        available_kwargs = {}
        if evidence_store is not None:
            available_kwargs["evidence_store"] = evidence_store
        if review_session is not None:
            available_kwargs["review_session"] = review_session
        if investigation is not None:
            available_kwargs["investigation"] = investigation
        if review_intelligence is not None:
            available_kwargs["review_intelligence"] = review_intelligence

        for module_path, func_name, filename, accepted_extras in BRIEF_GENERATORS:
            try:
                module = importlib.import_module(module_path)
                func = getattr(module, func_name)

                # Build kwargs: base + accepted extras that are available
                kwargs = dict(client_id=client_id, synthesis=synthesis, plan=plan)
                for key in accepted_extras:
                    if key in available_kwargs:
                        kwargs[key] = available_kwargs[key]

                brief = func(**kwargs)
                atomic_write_text(output_dir / f"{prefix}{filename}.md", brief)
                self.log(f"  [green]{prefix}{filename} generated[/green]")
            except Exception as e:
                if prefix:
                    logger.warning(f"{prefix}{filename} failed: {e}")
                else:
                    self.log(f"  [red]{filename} error: {e}[/red]")
                    logger.exception(f"{filename} generation failed")

        # Generate PDFs (with executive summary page if kyc_output available)
        if generate_pdfs:
            try:
                from generators.pdf_generator import generate_kyc_pdf
                kyc_out = getattr(self, '_kyc_output', None)
                for _, _, filename, _ in BRIEF_GENERATORS:
                    md_path = output_dir / f"{filename}.md"
                    if md_path.exists():
                        md_content = md_path.read_text(encoding="utf-8")
                        pdf_path = output_dir / f"{filename}.pdf"
                        generate_kyc_pdf(md_content, str(pdf_path), filename,
                                         risk_level=risk_level, kyc_output=kyc_out)
                        self.log(f"  [green]PDF generated: {filename}.pdf[/green]")
            except Exception as e:
                self.log(f"  [yellow]PDF generation skipped: {e}[/yellow]")

    def _save_stage3_outputs(self, client_id: str, synthesis, plan, review_intelligence=None):
        """Save Stage 3 synthesis outputs and proto-reports."""
        synth_path = self.output_dir / client_id / "03_synthesis"
        synth_path.mkdir(parents=True, exist_ok=True)

        if synthesis:
            atomic_write_json(
                synth_path / "evidence_graph.json",
                synthesis.evidence_graph.model_dump(mode="json"),
            )
            atomic_write_json(
                synth_path / "risk_assessment.json",
                synthesis.revised_risk_assessment.model_dump(mode="json") if synthesis.revised_risk_assessment else {},
            )

            # Save decision points
            if synthesis.decision_points:
                atomic_write_json(
                    synth_path / "decision_points.json",
                    [dp.model_dump(mode="json") for dp in synthesis.decision_points],
                )

            # Generate proto-reports (4 department-targeted briefs)
            # Convert EvidenceStore to list[dict] for generators
            es_list = self.evidence_store.to_list()
            self._generate_briefs(
                output_dir=synth_path,
                client_id=client_id,
                synthesis=synthesis,
                plan=plan,
                prefix="proto_",
                evidence_store=es_list,
                review_intelligence=review_intelligence,
            )

    async def _run_final_reports(self, client_id: str, synthesis, plan, review_session,
                                investigation: InvestigationResults = None,
                                review_intelligence: ReviewIntelligence = None):
        """Stage 5: Generate final 4 department-targeted briefs + PDFs + Excel + SAR + case package."""
        output_dir = self.output_dir / client_id / "05_output"

        # Clean stale output files from any prior run so old results don't
        # persist alongside new ones.  Only removes known generated file types
        # to avoid destroying user-created files.
        if output_dir.exists():
            _stale_extensions = {".md", ".pdf", ".xlsx", ".txt", ".json", ".zip"}
            for old_file in output_dir.iterdir():
                if old_file.is_file() and old_file.suffix in _stale_extensions:
                    old_file.unlink()
                    logger.debug("Cleaned stale output: %s", old_file.name)

        # Use in-memory evidence store if available (normal flow), fall back to disk (finalize)
        if hasattr(self, 'evidence_store') and len(self.evidence_store) > 0:
            evidence_store = self.evidence_store
        else:
            es_path = self.output_dir / client_id / "02_investigation" / "evidence_store.json"
            evidence_store = EvidenceStore()
            if es_path.exists():
                records = json.loads(es_path.read_text(encoding="utf-8"))
                evidence_store.extend(records)

        # Fix evidence graph if synthesis reports zeros but evidence exists
        if (synthesis and synthesis.evidence_graph.total_evidence_records == 0
                and len(evidence_store) > 0):
            from agents.kyc_synthesis import KYCSynthesisAgent
            synthesis.evidence_graph = KYCSynthesisAgent._compute_evidence_graph(evidence_store)

        # Normalize to list[dict] for generators (consistent with Stage 3)
        es_list = evidence_store.to_list() if hasattr(evidence_store, 'to_list') else list(evidence_store)

        # Use officer-overridden risk level (synthesis) if available, else preliminary
        risk_level = None
        if synthesis and synthesis.revised_risk_assessment:
            risk_level = synthesis.revised_risk_assessment.risk_level.value
        elif plan and plan.preliminary_risk:
            risk_level = plan.preliminary_risk.risk_level.value

        # Load review intelligence if not provided
        if review_intelligence is None:
            ri_path = self.output_dir / client_id / "03_synthesis" / "review_intelligence.json"
            if ri_path.exists():
                try:
                    ri_data = json.loads(ri_path.read_text(encoding="utf-8"))
                    review_intelligence = ReviewIntelligence(**ri_data)
                except Exception as e:
                    logger.warning(f"Could not load review intelligence: {e}")

        self._generate_briefs(
            output_dir=output_dir,
            client_id=client_id,
            synthesis=synthesis,
            plan=plan,
            evidence_store=es_list,
            review_session=review_session,
            investigation=investigation,
            review_intelligence=review_intelligence,
            generate_pdfs=True,
            risk_level=risk_level,
        )

        # ---- Generate SAR/STR narrative draft ----
        # Skip SAR narrative for LOW/MEDIUM risk cases with no filing triggers
        sar_narrative = None
        sar_risk = investigation.sar_risk_assessment if investigation else None
        sar_risk_level = (sar_risk or {}).get("sar_risk_level") or risk_level
        sar_triggers = (sar_risk or {}).get("triggers", [])
        # Also check transaction monitoring SAR indicators directly
        tm_indicators = (
            investigation.transaction_monitoring.sar_risk_indicators
            if investigation and investigation.transaction_monitoring
            else []
        )
        skip_sar = (
            sar_risk_level in ("LOW", "MEDIUM")
            and not sar_triggers
            and not tm_indicators
            and risk_level is not None
            and risk_level in ("LOW", "MEDIUM")
        )
        if skip_sar:
            self.log("  [dim]SAR narrative skipped — no filing indicators detected[/dim]")
            # Clean up stale SAR files from prior runs
            for stale in ("sar_narrative_draft.txt", "sar_filing_fincen.json", "str_filing_fintrac.json"):
                stale_path = output_dir / stale
                if stale_path.exists():
                    stale_path.unlink()
                    logger.info("Cleaned up stale file: %s", stale)
        else:
            try:
                from generators.sar_narrative import generate_sar_narrative
                sar_narrative = generate_sar_narrative(self._kyc_output, evidence_store=es_list)
                # AI-enhance narrative for HIGH/CRITICAL if not opted out
                if (risk_level in ("HIGH", "CRITICAL")
                        and not getattr(self, 'no_enhance_sar', False)):
                    try:
                        from generators.sar_narrative import enhance_sar_narrative
                        sar_narrative = await enhance_sar_narrative(sar_narrative)
                        if sar_narrative.get("enhanced"):
                            self.log("  [green]SAR narrative enhanced by AI[/green]")
                    except Exception as e:
                        logger.warning("SAR enhancement failed (using raw): %s", e)

                self._kyc_output.sar_narrative_draft = sar_narrative
                atomic_write_text(output_dir / "sar_narrative_draft.txt", sar_narrative.get("narrative_text", ""))
                self.log("  [green]SAR narrative draft generated[/green]")
            except Exception as e:
                self.log(f"  [yellow]SAR narrative skipped: {e}[/yellow]")
                logger.warning(f"SAR narrative generation failed: {e}")

        # ---- Generate regulatory filing pre-fills ----
        fincen_filing = None
        fintrac_filing = None
        if skip_sar:
            self.log("  [dim]Regulatory filing pre-fills skipped — no filing indicators detected[/dim]")
        else:
            try:
                from generators.regulatory_filing import prefill_fincen_sar, prefill_fintrac_str
                fincen_filing = prefill_fincen_sar(self._kyc_output, sar_narrative=sar_narrative)
                fintrac_filing = prefill_fintrac_str(self._kyc_output, sar_narrative=sar_narrative)
                self._kyc_output.fincen_filing = fincen_filing
                self._kyc_output.fintrac_filing = fintrac_filing
                from utilities.file_ops import atomic_write_json
                atomic_write_json(output_dir / "sar_filing_fincen.json", fincen_filing)
                atomic_write_json(output_dir / "str_filing_fintrac.json", fintrac_filing)
                self.log("  [green]Regulatory filing pre-fills generated (FinCEN + FINTRAC)[/green]")
            except Exception as e:
                self.log(f"  [yellow]Regulatory filing pre-fills skipped: {e}[/yellow]")
                logger.warning(f"Regulatory filing generation failed: {e}")

        # ---- Generate Excel workbook (after filings, so worksheets can be included) ----
        try:
            from generators.excel_export import generate_excel
            excel_path = output_dir / "screening_results.xlsx"
            generate_excel(
                self._kyc_output, output_path=excel_path, evidence_store=es_list,
                fincen_filing=fincen_filing, fintrac_filing=fintrac_filing,
            )
            self.log("  [green]Excel workbook generated: screening_results.xlsx[/green]")
        except Exception as e:
            self.log(f"  [yellow]Excel generation skipped: {e}[/yellow]")
            logger.warning(f"Excel generation failed: {e}")

        # ---- Generate case package ZIP ----
        try:
            from generators.case_package import export_case_package
            zip_path = export_case_package(
                self._kyc_output,
                output_dir=output_dir,
                evidence_store=es_list,
                sar_narrative=sar_narrative,
                fincen_filing=fincen_filing,
                fintrac_filing=fintrac_filing,
            )
            self.log(f"  [green]Case package exported: {zip_path.name}[/green]")
        except Exception as e:
            self.log(f"  [yellow]Case package export skipped: {e}[/yellow]")
            logger.warning(f"Case package export failed: {e}")

    # =========================================================================
    # Executive Summary Display (before interactive review)
    # =========================================================================

    def _display_executive_summary(
        self,
        client,
        plan: InvestigationPlan,
        synthesis: KYCSynthesisOutput,
        investigation: InvestigationResults,
        evidence_store,
    ):
        """Display executive case summary before interactive review."""
        is_individual = plan.client_type == ClientType.INDIVIDUAL

        # --- Risk info ---
        risk = (synthesis.revised_risk_assessment
                if synthesis and synthesis.revised_risk_assessment
                else plan.preliminary_risk)
        risk_level = risk.risk_level.value if risk else "UNKNOWN"
        risk_score = risk.total_score if risk else 0
        risk_colors = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red", "CRITICAL": "bold red"}
        rc = risk_colors.get(risk_level, "white")

        decision = synthesis.recommended_decision.value if synthesis else "PENDING"
        decision_colors = {"APPROVE": "green", "CONDITIONAL": "yellow",
                           "ESCALATE": "yellow", "DECLINE": "red"}
        dc = decision_colors.get(decision, "white")

        # --- Applicable agent sets ---
        if is_individual:
            all_agents = {"IndividualSanctions", "PEPDetection",
                          "IndividualAdverseMedia", "JurisdictionRisk",
                          "TransactionMonitoring"}
        else:
            all_agents = {"EntityVerification", "EntitySanctions",
                          "BusinessAdverseMedia", "JurisdictionRisk",
                          "TransactionMonitoring"}

        # --- Build header lines ---
        lines = []

        if is_individual:
            name = getattr(client, "full_name", plan.client_id)
            lines.append(f"  {name} · Individual · [{rc}]{risk_level} risk ({risk_score} pts)[/{rc}]")

            parts = []
            if getattr(client, "citizenship", None):
                parts.append(client.citizenship)
            if getattr(client, "country_of_birth", None):
                parts.append(f"Born: {client.country_of_birth}")
            emp = getattr(client, "employment", None)
            if emp:
                emp_desc = emp.status.replace("_", "-")
                if emp.industry:
                    emp_desc += f" ({emp.industry})"
                parts.append(emp_desc)
            if parts:
                lines.append(f"  {' · '.join(parts)}")

            money_parts = []
            if getattr(client, "annual_income", None):
                money_parts.append(f"Income: ${client.annual_income:,.0f}")
            if getattr(client, "net_worth", None):
                money_parts.append(f"Net Worth: ${client.net_worth:,.0f}")
            if money_parts:
                lines.append(f"  {' · '.join(money_parts)}")
        else:
            name = getattr(client, "legal_name", plan.client_id)
            lines.append(f"  {name} · Business · [{rc}]{risk_level} risk ({risk_score} pts)[/{rc}]")

            parts = []
            if getattr(client, "industry", None):
                parts.append(client.industry)
            countries = getattr(client, "countries_of_operation", [])
            if countries:
                parts.append(f"Operates in: {', '.join(countries)}")
            if parts:
                lines.append(f"  {' · '.join(parts)}")

            biz_parts = []
            if getattr(client, "annual_revenue", None):
                biz_parts.append(f"Revenue: ${client.annual_revenue:,.0f}")
            ubos = getattr(client, "beneficial_owners", [])
            if ubos:
                biz_parts.append(f"{len(ubos)} UBO{'s' if len(ubos) != 1 else ''}")
            if biz_parts:
                lines.append(f"  {' · '.join(biz_parts)}")

        lines.append("")
        lines.append(f"  Recommendation: [{dc}]{decision}[/{dc}]")

        scope = getattr(plan, "investigation_scope", "full")
        agents_dispatched = len(plan.agents_to_run)
        lines.append(f"  Scope: {scope} — {agents_dispatched} of {len(all_agents)} agents dispatched")

        console.print(Panel("\n".join(lines), title="Case Summary",
                            border_style="cyan", padding=(1, 1)))

        # --- Findings from evidence records (grouped by agent) ---
        source_findings: dict[str, list[dict]] = {}
        for rec in evidence_store:
            src = rec.get("source_name", "unknown")
            source_findings.setdefault(src, []).append(rec)

        agent_labels = {
            "IndividualSanctions": "Sanctions",
            "EntitySanctions": "Sanctions",
            "PEPDetection": "PEP",
            "IndividualAdverseMedia": "Adverse Media",
            "BusinessAdverseMedia": "Adverse Media",
            "EntityVerification": "Entity Verification",
            "JurisdictionRisk": "Jurisdiction Risk",
            "TransactionMonitoring": "Txn Monitoring",
        }

        disp_colors = {
            "CLEAR": "green", "FALSE_POSITIVE": "green",
            "PENDING_REVIEW": "yellow",
            "POTENTIAL_MATCH": "red", "CONFIRMED_MATCH": "bold red",
        }

        disp_priority = {
            "CONFIRMED_MATCH": 4, "POTENTIAL_MATCH": 3,
            "PENDING_REVIEW": 2, "CLEAR": 1, "FALSE_POSITIVE": 0,
        }

        LEADER_WIDTH = 18  # label + dots total chars

        finding_lines = []
        for agent_name in plan.agents_to_run:
            label = agent_labels.get(agent_name, agent_name)
            records = source_findings.get(agent_name, [])
            dot_count = max(2, LEADER_WIDTH - len(label) - 2)
            leader = f"{label} {'·' * dot_count}"

            if records:
                dispositions = [r.get("disposition", "PENDING_REVIEW") for r in records]
                primary_disp = max(dispositions, key=lambda d: disp_priority.get(d, 1))
                dcolor = disp_colors.get(primary_disp, "white")

                # Use first record's claim as summary
                claim = records[0].get("claim", "")
                if len(claim) > 50:
                    claim = claim[:47] + "..."
                summary = f"({claim})" if claim else ""

                finding_lines.append(
                    f"    {leader} [{dcolor}]{primary_disp}[/{dcolor}] {summary}"
                )
            else:
                finding_lines.append(f"    {leader} [dim]no evidence records[/dim]")

        # --- Utility findings ---
        utility_lines = []

        suit = investigation.suitability_assessment
        if suit:
            label, suitable = "Suitability", suit.get("suitable", False)
            concerns = suit.get("concerns", [])
            dot_count = max(2, LEADER_WIDTH - len(label) - 2)
            leader = f"{label} {'·' * dot_count}"
            color = "green" if suitable else "yellow"
            status = "suitable" if suitable else "unsuitable"
            utility_lines.append(
                f"    {leader} [{color}]{status}[/{color}] ({len(concerns)} concern{'s' if len(concerns) != 1 else ''})"
            )

        fatca = investigation.fatca_crs
        if fatca:
            label = "FATCA/CRS"
            dot_count = max(2, LEADER_WIDTH - len(label) - 2)
            leader = f"{label} {'·' * dot_count}"
            reporting = fatca.get("reporting_required") or fatca.get("crs_reporting_required")
            jurisdictions = fatca.get("reporting_jurisdictions", [])
            if reporting:
                jur_text = f" ({', '.join(jurisdictions)})" if jurisdictions else ""
                utility_lines.append(f"    {leader} [yellow]reporting required{jur_text}[/yellow]")
            else:
                utility_lines.append(f"    {leader} [green]no reporting obligations[/green]")

        edd = investigation.edd_requirements
        if edd:
            label = "EDD"
            dot_count = max(2, LEADER_WIDTH - len(label) - 2)
            leader = f"{label} {'·' * dot_count}"
            required = edd.get("edd_required", False)
            triggers = edd.get("triggers", [])
            freq = edd.get("monitoring_frequency", "")
            if required:
                trig_text = f"{len(triggers)} trigger{'s' if len(triggers) != 1 else ''}"
                freq_text = f", {freq} monitoring" if freq else ""
                utility_lines.append(f"    {leader} [yellow]required ({trig_text}{freq_text})[/yellow]")
            else:
                utility_lines.append(f"    {leader} [green]not required[/green]")

        sar = investigation.sar_risk_assessment
        if sar:
            label = "SAR Risk"
            dot_count = max(2, LEADER_WIDTH - len(label) - 2)
            leader = f"{label} {'·' * dot_count}"
            sar_level = sar.get("sar_risk_level", "UNKNOWN")
            sar_triggers = sar.get("triggers", [])
            sar_color = risk_colors.get(sar_level, "white")
            utility_lines.append(
                f"    {leader} [{sar_color}]{sar_level}[/{sar_color}] "
                f"({len(sar_triggers)} trigger{'s' if len(sar_triggers) != 1 else ''})"
            )

        if finding_lines or utility_lines:
            console.print("\n  [bold]Findings[/bold]")
            for line in finding_lines:
                console.print(line)
            for line in utility_lines:
                console.print(line)

        # --- Risk factors ---
        if risk and risk.risk_factors:
            console.print("\n  [bold]Risk Factors[/bold]")
            for factor in sorted(risk.risk_factors, key=lambda f: f.points, reverse=True):
                console.print(f"    [yellow]+{factor.points}[/yellow]  {factor.factor}")

        # --- Decision reasoning (if populated) ---
        if synthesis and synthesis.decision_reasoning:
            console.print("\n  [bold]Decision Reasoning[/bold]")
            console.print(f"    [dim]{synthesis.decision_reasoning}[/dim]")

        # --- Adversarial challenges ---
        if synthesis and synthesis.adversarial_challenges:
            count = len(synthesis.adversarial_challenges)
            console.print(
                f"\n  [yellow]Adversarial review: {count} challenge{'s' if count != 1 else ''} raised[/yellow]"
            )

        # --- Not dispatched ---
        dispatched = set(plan.agents_to_run)
        not_dispatched = sorted(all_agents - dispatched)
        if not_dispatched:
            console.print(f"\n  [dim]Not Dispatched: {', '.join(not_dispatched)}[/dim]")
            console.print("  [dim]Use 'reinvestigate <agent>' to run additional agents[/dim]")

        # --- Degradation warning ---
        if investigation.is_degraded and investigation.failed_agents:
            failed = ", ".join(investigation.failed_agents)
            console.print(f"\n  [bold yellow]WARNING: Degraded investigation — {failed} failed[/bold yellow]")

        console.print()

    # =========================================================================
    # Review Intelligence Display & I/O
    # =========================================================================

    def _display_review_intelligence(self, review_intel: ReviewIntelligence):
        """Display review intelligence findings in the terminal."""
        if not review_intel:
            return

        console.print("\n[bold magenta]Review Intelligence[/bold magenta]\n")

        # 1. Confidence degradation banner
        conf = review_intel.confidence
        grade_color = {"A": "green", "B": "green", "C": "yellow", "D": "red", "F": "red"}.get(
            conf.overall_confidence_grade, "white")
        grade_text = (f"Evidence Quality: Grade {conf.overall_confidence_grade} — "
                      f"V:{conf.verified_pct:.0f}% S:{conf.sourced_pct:.0f}% "
                      f"I:{conf.inferred_pct:.0f}% U:{conf.unknown_pct:.0f}%")
        if conf.degraded:
            console.print(Panel(
                f"[bold]{grade_text}[/bold]\n" +
                "\n".join(f"  - {a}" for a in conf.follow_up_actions),
                title="CONFIDENCE DEGRADED",
                border_style="red",
            ))
        else:
            console.print(f"  [{grade_color}]{grade_text}[/{grade_color}]")

        # 2. Contradictions
        if review_intel.contradictions:
            console.print(Panel(
                f"[bold]{len(review_intel.contradictions)} contradiction(s) detected[/bold]",
                title="CONTRADICTIONS",
                border_style="red",
            ))
            for c in review_intel.contradictions:
                sev_color = {"CRITICAL": "red", "HIGH": "yellow", "MEDIUM": "cyan"}.get(c.severity.value, "white")
                console.print(f"  [{sev_color}][{c.severity.value}][/{sev_color}] "
                              f"{c.agent_a} vs {c.agent_b}")
                console.print(f"    A: {c.finding_a}")
                console.print(f"    B: {c.finding_b}")
                console.print(f"    [dim]{c.resolution_guidance}[/dim]")
                console.print()

        # 3. Critical discussion points
        if review_intel.discussion_points:
            table = Table(title="Discussion Points", show_lines=False)
            table.add_column("Sev", width=9)
            table.add_column("Finding", ratio=3)
            table.add_column("Action", ratio=2)

            for dp in review_intel.discussion_points:
                sev_color = {"CRITICAL": "red", "HIGH": "yellow", "MEDIUM": "cyan", "ADVISORY": "dim"}.get(
                    dp.severity.value, "white")
                table.add_row(
                    f"[{sev_color}]{dp.severity.value}[/{sev_color}]",
                    dp.title,
                    dp.recommended_action,
                )
            console.print(table)
            console.print()

        # 4. Regulatory mappings
        filing_count = sum(
            1 for fm in review_intel.regulatory_mappings
            for tag in fm.regulatory_tags if tag.filing_required
        )
        if review_intel.regulatory_mappings:
            console.print(f"  Regulatory mappings: {len(review_intel.regulatory_mappings)} findings tagged, "
                          f"{filing_count} filing obligation(s)")

        console.print()

    def _save_review_intelligence(self, client_id: str, review_intel: ReviewIntelligence | None):
        """Save review intelligence to JSON file."""
        if not review_intel:
            return
        synth_path = self.output_dir / client_id / "03_synthesis"
        synth_path.mkdir(parents=True, exist_ok=True)
        atomic_write_json(synth_path / "review_intelligence.json", review_intel.model_dump(mode="json"))

    # =========================================================================
    # File I/O Helpers
    # =========================================================================

    def _save_stage_results(self, client_id: str, stage_dir: str, data: dict):
        """Save stage results to appropriate directory."""
        from utilities.file_ops import atomic_write_json
        stage_path = self.output_dir / client_id / stage_dir
        stage_path.mkdir(parents=True, exist_ok=True)
        for filename, content in data.items():
            file_path = stage_path / f"{filename}.json"
            atomic_write_json(file_path, content)

    def _save_evidence_store(self, client_id: str):
        """Save the central evidence store."""
        from utilities.file_ops import atomic_write_json
        inv_path = self.output_dir / client_id / "02_investigation"
        inv_path.mkdir(parents=True, exist_ok=True)
        records = self.evidence_store.to_list()
        atomic_write_json(inv_path / "evidence_store.json", records)

    def _load_evidence_store(self, client_id: str):
        """Restore evidence store from saved JSON file (used on checkpoint resume)."""
        es_path = self.output_dir / client_id / "02_investigation" / "evidence_store.json"
        if es_path.exists():
            try:
                records = json.loads(es_path.read_text(encoding="utf-8"))
                # Clear before loading to prevent duplicate records
                self.evidence_store = EvidenceStore()
                self.evidence_store.extend(records)
                self.log(f"  [green]Restored {len(records)} evidence records from checkpoint[/green]")
            except Exception as e:
                logger.warning(f"Could not restore evidence store: {e}")

    def _display_decision_points(self, synthesis):
        """Display decision points requiring officer review in the terminal."""
        if not synthesis or not synthesis.decision_points:
            return

        console.print("\n[bold]Decision Points Requiring Officer Review:[/bold]\n")
        for dp in synthesis.decision_points:
            console.print(f"[bold yellow]{'━' * 60}[/bold yellow]")
            console.print(f"[bold yellow]  {dp.title}[/bold yellow]")
            console.print(f"[bold yellow]{'━' * 60}[/bold yellow]")
            console.print(f"  Disposition: {dp.disposition} ({dp.confidence:.0%} confidence)")
            console.print(f"  [dim]{dp.context_summary}[/dim]\n")
            console.print("  [bold red]Counter-case:[/bold red]")
            console.print(f"  {dp.counter_argument.argument}\n")
            console.print(f"  [bold red]Risk if wrong:[/bold red] {dp.counter_argument.risk_if_wrong}\n")
            if dp.counter_argument.recommended_mitigations:
                mitigations = ", ".join(dp.counter_argument.recommended_mitigations)
                console.print(f"  [dim]Mitigations: {mitigations}[/dim]\n")
            console.print("  [bold]Options:[/bold]")
            for opt in dp.options:
                console.print(f"    [{opt.option_id}] [bold]{opt.label}[/bold] — {opt.description}")
                for consequence in opt.consequences:
                    console.print(f"        • {consequence}")
                console.print(f"        Onboarding: {opt.onboarding_impact}")
                console.print(f"        Timeline: {opt.timeline}")
            console.print()

    def _save_review_session(self, client_id: str, session: ReviewSession):
        """Save review session data."""
        from utilities.file_ops import atomic_write_json
        review_path = self.output_dir / client_id / "04_review"
        review_path.mkdir(parents=True, exist_ok=True)
        atomic_write_json(review_path / "review_session.json", session.model_dump(mode="json"))
