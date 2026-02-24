#!/usr/bin/env python3
"""
KYC Client Onboarding Intelligence System

AI-powered KYC screening for individual and business client onboarding.
AI investigates. Rules classify. Humans decide.

Usage:
    python main.py --client test_cases/case1_individual_low.json
    python main.py --client test_cases/case3_business_critical.json --output results
    python main.py --client test_cases/case2_individual_pep.json --resume
    python main.py --finalize results/sarah_thompson
"""

import argparse
import asyncio
import io
import json
import re
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# =============================================================================
# Tee stream — duplicate stdout to a log file in real-time
# =============================================================================

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


class _TeeStream(io.TextIOBase):
    """Write to both the original stream and a log file, stripping ANSI from the file."""

    def __init__(self, original: io.TextIOBase, log_file: io.TextIOBase):
        self._original = original
        self._log = log_file

    def write(self, data: str) -> int:
        self._original.write(data)
        self._log.write(_ANSI_RE.sub("", data))
        self._log.flush()
        return len(data)

    def flush(self) -> None:
        self._original.flush()
        self._log.flush()

    @property
    def encoding(self):
        return getattr(self._original, "encoding", "utf-8")

    def isatty(self) -> bool:
        return self._original.isatty()

    def fileno(self) -> int:
        return self._original.fileno()

    def readable(self) -> bool:
        return False

    def writable(self) -> bool:
        return True

# Load .env file before other imports
from agents import set_api_key
from config import get_config
from pipeline import KYCPipeline

# Use legacy_windows mode for better Windows compatibility
console = Console(force_terminal=True, legacy_windows=True)


def create_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="kyc-onboarding",
        description="KYC Client Onboarding Intelligence System - AI investigates. Rules classify. Humans decide.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s --demo                                         # Demo mode (Case 3, interactive)
    %(prog)s --client test_cases/case1_individual_low.json  # Interactive review
    %(prog)s --client test_cases/case2_individual_pep.json --non-interactive
    %(prog)s --client test_cases/case3_business_critical.json --resume
    %(prog)s --finalize results/northern_maple_trading_corp

The system will:
  1. Classify client risk and plan investigation
  2. Run AI screening agents + deterministic utilities
  3. Synthesize findings into evidence-linked risk profile
  4. Pause for conversational review (ask questions, approve dispositions)
  5. Generate final compliance brief and onboarding summary

Output structure:
  results/{client_id}/
    01_intake/          Risk classification and investigation plan
    02_investigation/   Evidence store and screening results
    03_synthesis/       Evidence graph and proto-reports
    04_review/          Review session log
    05_output/          Final compliance brief + onboarding summary (MD + PDF)
        """
    )

    parser.add_argument(
        "--client",
        help="Path to client JSON file (individual or business)"
    )

    parser.add_argument(
        "-o", "--output",
        default="results",
        help="Output directory for results (default: results/)"
    )

    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress progress output"
    )

    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 1.0.0"
    )

    parser.add_argument(
        "--api-key",
        help="Anthropic API key (can also use ANTHROPIC_API_KEY env var)"
    )

    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from checkpoint if available (skips completed stages)"
    )

    parser.add_argument(
        "--finalize",
        type=str,
        metavar="RESULTS_DIR",
        help="Finalize a paused review session. Pass the results directory path."
    )

    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Skip interactive review (pause and finalize separately, original behavior)"
    )

    parser.add_argument(
        "--demo",
        action="store_true",
        help="Demo mode: auto-loads Case 3 with narrator panels explaining each stage"
    )

    parser.add_argument(
        "--update-lists",
        action="store_true",
        help="Fetch latest FATF/OFAC/FINTRAC lists and show diff report"
    )

    parser.add_argument(
        "--apply-updates",
        action="store_true",
        help="Apply fetched list updates to screening_lists/ (requires --update-lists)"
    )

    parser.add_argument(
        "--record-outcome",
        nargs=2,
        metavar=("CLIENT_ID", "OUTCOME"),
        help="Record a post-decision outcome (e.g. --record-outcome sarah_thompson APPROVE)"
    )

    parser.add_argument(
        "--feedback-report",
        action="store_true",
        help="Display accuracy metrics and calibration suggestions"
    )

    parser.add_argument(
        "--log-file",
        type=str,
        metavar="PATH",
        help="Tee all output to a log file in real-time (ANSI stripped). "
             "Useful for monitoring from another process while running interactively."
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run Stage 1 only and print the investigation plan, then exit. Zero API cost."
    )

    parser.add_argument(
        "--skip-pdfs",
        action="store_true",
        help="Skip PDF generation (useful on machines without PDF dependencies)"
    )

    parser.add_argument(
        "--batch",
        type=str,
        metavar="DIR",
        help="Batch mode: run pipeline on all case*.json files in DIR and display summary"
    )

    parser.add_argument(
        "--no-enhance-sar",
        action="store_true",
        help="Skip AI-enhanced SAR narrative (use raw template-driven narrative only)"
    )

    parser.add_argument(
        "--monitor",
        type=str,
        metavar="RESULTS_DIR",
        help="Continuous monitoring: re-screen all clients in RESULTS_DIR against current sanctions lists"
    )

    return parser


DEMO_NARRATION = {
    "stage1": (
        "Stage 1: Intake & Classification",
        "Deterministic risk scoring detected CRITICAL risk: Russia operations, "
        "US nexus via Oregon warehouse, 3 UBOs including a 51% Russian-citizen owner.\n"
        "The system identified applicable regulations (FINTRAC, CIRO, OFAC, FATCA, CRS) "
        "and planned 7 AI agents + 3 UBO cascades.",
    ),
    "complete": (
        "Pipeline Complete",
        "AI agents screened across 5 jurisdictions. Opus cross-referenced all evidence, "
        "surfaced contradictions, and generated counter-arguments for each disposition.\n"
        "Review Intelligence graded evidence quality and mapped findings to regulatory obligations.\n"
        "A human analyst would spend 4-6 hours on this case. The system completed it in minutes, "
        "with full evidence traceability and an auditable review session.",
    ),
}


def _demo_narrator(stage_key: str):
    """Display a demo narrator panel between stages."""
    if stage_key not in DEMO_NARRATION:
        return
    title, body = DEMO_NARRATION[stage_key]
    console.print(Panel(
        body,
        title=f"[bold magenta]{title}[/bold magenta]",
        border_style="magenta",
        padding=(1, 2),
    ))
    console.print()


def display_summary(output):
    """Display a summary of the KYC results."""
    plan = output.intake_classification
    synthesis = output.synthesis

    # Risk level color mapping
    risk_colors = {
        "LOW": "green",
        "MEDIUM": "yellow",
        "HIGH": "red",
        "CRITICAL": "bold red",
    }

    # Client info panel
    client_data = output.client_data
    client_name = client_data.get("full_name") or client_data.get("legal_name", "Unknown")
    risk_level = plan.preliminary_risk.risk_level.value
    risk_color = risk_colors.get(risk_level, "white")

    info_lines = [
        f"[bold]{client_name}[/bold]",
        f"Type: {output.client_type.value.title()}",
        f"Client ID: {output.client_id}",
        f"Risk Level: [{risk_color}]{risk_level}[/{risk_color}] ({plan.preliminary_risk.total_score} pts)",
    ]

    if plan.applicable_regulations:
        info_lines.append(f"Regulations: {', '.join(plan.applicable_regulations)}")

    console.print(Panel(
        "\n".join(info_lines),
        title="KYC Client Profile",
        border_style="blue"
    ))

    # Risk factors table
    if plan.preliminary_risk.risk_factors:
        table = Table(title="Risk Factors")
        table.add_column("Factor", style="cyan")
        table.add_column("Points", justify="right")
        table.add_column("Category", style="dim")

        for rf in plan.preliminary_risk.risk_factors:
            table.add_row(rf.factor, str(rf.points), rf.category)

        console.print(table)

    # Synthesis results if available
    if synthesis:
        decision_colors = {
            "APPROVE": "green",
            "CONDITIONAL": "yellow",
            "ESCALATE": "red",
            "DECLINE": "bold red",
        }
        decision = synthesis.recommended_decision.value
        dec_color = decision_colors.get(decision, "white")

        console.print(f"\n[bold]Recommended Decision:[/bold] [{dec_color}]{decision}[/{dec_color}]")

        if synthesis.key_findings:
            console.print("\n[bold]Key Findings:[/bold]")
            for finding in synthesis.key_findings[:5]:
                console.print(f"  - {finding}")

        if synthesis.conditions:
            console.print("\n[bold yellow]Conditions:[/bold yellow]")
            for cond in synthesis.conditions:
                console.print(f"  - {cond}")

        if synthesis.items_requiring_review:
            console.print("\n[bold red]Items Requiring Review:[/bold red]")
            for item in synthesis.items_requiring_review:
                console.print(f"  - {item}")


async def main_async(args: argparse.Namespace) -> int:
    """Async main function."""
    verbose = not args.quiet

    try:
        # 1F. Validate --record-outcome outcome values
        if args.record_outcome:
            from utilities.feedback_tracker import record_outcome
            client_id, outcome = args.record_outcome
            valid_outcomes = {"APPROVE", "DECLINE", "ESCALATE", "CONDITIONAL"}
            if outcome.upper() not in valid_outcomes:
                console.print(f"[bold red]Error:[/bold red] Invalid outcome '{outcome}'. "
                              f"Valid: {', '.join(sorted(valid_outcomes))}")
                return 1
            record_outcome(client_id, outcome, output_dir=args.output)
            if verbose:
                console.print(f"[green]Outcome recorded: {client_id} → {outcome}[/green]")
            return 0

        # Handle --feedback-report
        if args.feedback_report:
            from utilities.feedback_tracker import compute_accuracy_metrics, compute_calibration
            metrics = compute_accuracy_metrics(output_dir=args.output)
            cal = compute_calibration(output_dir=args.output)

            if verbose:
                console.print(Panel.fit(
                    f"[bold]Feedback Report[/bold] ({metrics.total_cases} cases)\n"
                    f"Approvals: {metrics.approvals}  Escalations: {metrics.escalations}  "
                    f"Declines: {metrics.declines}  Conditional: {metrics.conditionals}\n"
                    f"Post-onboarding SARs: {metrics.post_onboarding_sars}  "
                    f"No issues: {metrics.post_onboarding_no_issues}\n"
                    f"Approval rate: {metrics.approval_rate:.0%}  "
                    f"False negative rate: {metrics.false_negative_rate:.0%}  "
                    f"False positive rate: {metrics.false_positive_rate:.0%}",
                    border_style="blue",
                ))
                if cal.suggestions:
                    console.print("\n[bold]Calibration Suggestions:[/bold]")
                    for s in cal.suggestions:
                        console.print(f"  - {s}")
            return 0

        # 1C. Validate --apply-updates requires --update-lists
        if args.apply_updates and not args.update_lists:
            console.print("[bold red]Error:[/bold red] --apply-updates requires --update-lists")
            return 1

        # Handle --update-lists
        if args.update_lists:
            from utilities.reference_data_updater import apply_updates, check_for_updates
            if verbose:
                console.print("[bold blue]Fetching latest reference data...[/bold blue]")
            report = await check_for_updates()
            if verbose:
                console.print(report.format_text())
            if args.apply_updates and report.has_changes:
                override_path = apply_updates(report)
                if verbose:
                    console.print(f"\n[bold green]Updates applied to {override_path}[/bold green]")
            elif args.apply_updates:
                if verbose:
                    console.print("\n[dim]No changes to apply.[/dim]")
            return 0

        # Handle --monitor
        if args.monitor:
            from monitoring import run_monitoring
            return await run_monitoring(args.monitor, verbose=verbose)

        # Handle --batch
        if args.batch:
            from batch import run_batch
            return await run_batch(args.batch, args, verbose=verbose)

        # 1H. Warn on conflicting flags
        if args.demo and args.client:
            if verbose:
                console.print("[yellow]Warning:[/yellow] --demo and --client both provided; --client will be ignored.")
        if args.client and args.finalize:
            if verbose:
                console.print("[yellow]Warning:[/yellow] --client and --finalize both provided; --client will be ignored.")

        # Set API key
        config = get_config()
        api_key = args.api_key or config.api_key

        if api_key:
            set_api_key(api_key)
        else:
            console.print("[bold red]Error:[/bold red] No API key found.")
            console.print("Set ANTHROPIC_API_KEY in .env file or pass --api-key argument.")
            return 1

        if verbose:
            console.print(Panel.fit(
                "[bold blue]KYC Client Onboarding Intelligence System[/bold blue]\n"
                "AI investigates. Rules classify. Humans decide.",
                border_style="blue"
            ))

        interactive = not args.non_interactive

        pipeline = KYCPipeline(
            output_dir=args.output,
            verbose=verbose,
            resume=args.resume,
            interactive=interactive,
        )
        pipeline.skip_pdfs = getattr(args, 'skip_pdfs', False)
        pipeline.no_enhance_sar = getattr(args, 'no_enhance_sar', False)

        if args.finalize:
            # Finalize a paused review session
            result = await pipeline.finalize(args.finalize)
        elif args.demo or args.client:
            # Demo mode: auto-load Case 3
            if args.demo:
                demo_path = Path(__file__).parent / "test_cases" / "case3_business_critical.json"
                if not demo_path.exists():
                    console.print(f"[bold red]Error:[/bold red] Demo case not found: {demo_path}")
                    return 1
                client_data = json.loads(demo_path.read_text(encoding="utf-8"))
                if verbose:
                    console.print(Panel(
                        "[bold]Demo Mode[/bold]: Running Case 3 — Northern Maple Trading Corp\n"
                        "CRITICAL risk: Russia trade corridor, US nexus, 3 UBOs including 51% Russian owner\n\n"
                        "[dim]This demonstrates the full 5-stage pipeline with interactive review.[/dim]",
                        title="KYC Demo",
                        border_style="magenta",
                    ))
            else:
                # Load client data
                client_path = Path(args.client)
                if not client_path.exists():
                    console.print(f"[bold red]Error:[/bold red] Client file not found: {args.client}")
                    return 1
                # 1D. Better error for invalid JSON
                try:
                    client_data = json.loads(client_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError as e:
                    console.print(f"[bold red]Error:[/bold red] Invalid JSON in {args.client}: {e}")
                    return 1

            if verbose:
                client_name = client_data.get("full_name") or client_data.get("legal_name", "Unknown")
                console.print(f"\nProcessing: [bold]{client_name}[/bold]\n")

            # --dry-run: Stage 1 only, print plan, exit
            if args.dry_run:
                from models import BusinessClient, IndividualClient
                from utilities.investigation_planner import build_investigation_plan
                ct = client_data.get("client_type", "individual")
                client = IndividualClient(**client_data) if ct == "individual" else BusinessClient(**client_data)
                plan = build_investigation_plan(client)
                risk = plan.preliminary_risk
                risk_colors = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red", "CRITICAL": "bold red"}
                rc = risk_colors.get(risk.risk_level.value, "white")
                console.print(Panel.fit(
                    f"[bold]Investigation Plan (Dry Run)[/bold]\n\n"
                    f"Client ID: {plan.client_id}\n"
                    f"Risk Level: [{rc}]{risk.risk_level.value}[/{rc}] ({risk.total_score} pts)\n"
                    f"Regulations: {', '.join(plan.applicable_regulations)}\n"
                    f"Agents: {', '.join(plan.agents_to_run)}\n"
                    f"Utilities: {', '.join(plan.utilities_to_run)}\n"
                    f"UBO Cascade: {'Yes (' + ', '.join(plan.ubo_names) + ')' if plan.ubo_cascade_needed else 'No'}\n"
                    f"Investigation Scope: {plan.investigation_scope}",
                    border_style="blue",
                ))
                if risk.risk_factors:
                    table = Table(title="Risk Factors")
                    table.add_column("Factor", style="cyan")
                    table.add_column("Points", justify="right")
                    table.add_column("Category", style="dim")
                    for rf in risk.risk_factors:
                        table.add_row(rf.factor, str(rf.points), rf.category)
                    console.print(table)
                console.print("\n[dim]Dry run complete — no API calls made.[/dim]")
                return 0

            # Demo narrator: Stage 1
            if args.demo and verbose:
                _demo_narrator("stage1")

            result = await pipeline.run(client_data)

            # Demo narrator: completion
            if args.demo and verbose:
                _demo_narrator("complete")
        else:
            # 1G. Show full help instead of partial error
            parser = create_parser()
            parser.print_help()
            return 1

        if verbose:
            console.print()
            display_summary(result)

        if verbose:
            console.print(f"\n[bold green]Pipeline complete in {result.duration_seconds:.1f}s[/bold green]")

        # If paused for review, inform user
        if not result.synthesis or (result.review_session and not result.review_session.finalized):
            if verbose:
                console.print("\n[bold yellow]Pipeline paused for review.[/bold yellow]")
                console.print("Review the proto-reports, ask questions, then run:")
                console.print(f"  python main.py --finalize results/{result.client_id}")

        return 0

    except KeyboardInterrupt:
        console.print("\n[yellow]Pipeline cancelled by user[/yellow]")
        return 130

    except Exception as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        if verbose:
            console.print_exception()
        return 1


def main() -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()

    log_fh = None
    original_stdout = sys.stdout

    # Set up log-file tee before any output
    if args.log_file:
        try:
            log_fh = open(args.log_file, "w", encoding="utf-8")
            sys.stdout = _TeeStream(original_stdout, log_fh)
            # Rich Console instances capture sys.stdout at creation time,
            # so we need to point them at the tee stream explicitly.
            import pipeline as _pl
            import pipeline_metrics as _pm
            import pipeline_reports as _pr
            import pipeline_review as _rv
            for c in (console, _pl.console, _pr.console, _pm.console, _rv.console):
                c.file = sys.stdout
        except OSError as e:
            print(f"Warning: Could not open log file {args.log_file}: {e}", file=sys.stderr)

    # 1A. Wrap asyncio.run in KeyboardInterrupt handler
    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        return 130
    finally:
        # Restore original stdout on all Console instances
        if log_fh:
            import pipeline as _pl
            import pipeline_metrics as _pm
            import pipeline_reports as _pr
            import pipeline_review as _rv
            for c in (console, _pl.console, _pr.console, _pm.console, _rv.console):
                c.file = original_stdout
        sys.stdout = original_stdout
        if log_fh:
            log_fh.close()


if __name__ == "__main__":
    sys.exit(main())
