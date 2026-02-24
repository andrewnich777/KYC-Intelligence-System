"""
Batch pipeline runner.

Runs the KYC pipeline on all case*.json files in a directory,
collects per-case results, and displays a Rich summary table.
"""

import json
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console(force_terminal=True, legacy_windows=True)


async def run_batch(case_dir: str, args, *, verbose: bool = True) -> int:
    """Run pipeline on all case*.json files in *case_dir*.

    Returns exit code (0 = all succeeded, 1 = at least one failure).
    """
    from pipeline import KYCPipeline

    case_path = Path(case_dir)
    if not case_path.is_dir():
        console.print(f"[bold red]Error:[/bold red] Directory not found: {case_dir}")
        return 1

    case_files = sorted(case_path.glob("case*.json"))
    if not case_files:
        console.print(f"[bold red]Error:[/bold red] No case*.json files found in {case_dir}")
        return 1

    console.print(f"\n[bold blue]Batch mode:[/bold blue] {len(case_files)} case(s) in {case_dir}\n")

    results: list[dict] = []
    failures = 0

    for idx, cf in enumerate(case_files, 1):
        console.print(f"[bold]━━━ Case {idx}/{len(case_files)}: {cf.name} ━━━[/bold]")
        try:
            client_data = json.loads(cf.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            console.print(f"  [red]Invalid JSON: {e}[/red]")
            results.append({"file": cf.name, "status": "JSON_ERROR", "error": str(e)})
            failures += 1
            continue

        client_name = client_data.get("full_name") or client_data.get("legal_name", cf.stem)
        pipeline = KYCPipeline(
            output_dir=args.output,
            verbose=verbose,
            resume=getattr(args, 'resume', False),
            interactive=False,  # Batch is always non-interactive
        )
        pipeline.skip_pdfs = getattr(args, 'skip_pdfs', False)
        pipeline.no_enhance_sar = getattr(args, 'no_enhance_sar', False)

        t0 = time.time()
        try:
            output = await pipeline.run(client_data)
            duration = time.time() - t0

            risk_level = "N/A"
            if output.intake_classification and output.intake_classification.preliminary_risk:
                risk_level = output.intake_classification.preliminary_risk.risk_level.value

            decision = output.final_decision.value if output.final_decision else "PENDING"
            cost = output.metrics.get("estimated_cost_usd", 0.0) if output.metrics else 0.0

            results.append({
                "file": cf.name,
                "client": client_name,
                "status": "OK",
                "risk_level": risk_level,
                "decision": decision,
                "duration": round(duration, 1),
                "cost": round(cost, 4),
            })
            console.print(f"  [green]Complete: {decision} ({duration:.1f}s)[/green]\n")
        except Exception as e:
            duration = time.time() - t0
            results.append({
                "file": cf.name,
                "client": client_name,
                "status": "FAILED",
                "error": str(e),
                "duration": round(duration, 1),
            })
            failures += 1
            console.print(f"  [red]Failed: {e}[/red]\n")

    # Summary table
    risk_colors = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red", "CRITICAL": "bold red"}
    table = Table(title=f"Batch Summary ({len(results)} cases)")
    table.add_column("File", style="cyan")
    table.add_column("Client")
    table.add_column("Status")
    table.add_column("Risk")
    table.add_column("Decision")
    table.add_column("Duration", justify="right")
    table.add_column("Cost", justify="right")

    total_duration = 0.0
    total_cost = 0.0
    for r in results:
        status_style = "green" if r["status"] == "OK" else "red"
        rl = r.get("risk_level", "")
        rc = risk_colors.get(rl, "white")
        table.add_row(
            r["file"],
            r.get("client", ""),
            f"[{status_style}]{r['status']}[/{status_style}]",
            f"[{rc}]{rl}[/{rc}]" if rl else "",
            r.get("decision", ""),
            f"{r.get('duration', 0):.1f}s",
            f"${r.get('cost', 0):.4f}" if r.get("cost") else "",
        )
        total_duration += r.get("duration", 0)
        total_cost += r.get("cost", 0)

    console.print(table)
    console.print(f"\nTotal: {total_duration:.1f}s, ${total_cost:.4f}")
    if failures:
        console.print(f"[red]{failures} failure(s)[/red]")

    return 1 if failures else 0
