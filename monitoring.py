"""
Continuous Monitoring.

Re-screens existing client results against current sanctions lists.
No AI agents — just the screening list tool.

Usage:
    python main.py --monitor results/
"""

import json
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from logger import get_logger

logger = get_logger(__name__)

console = Console(force_terminal=True, legacy_windows=True)


async def _screen_client(client_id: str, client_dir: Path) -> dict:
    """Re-screen a single client against the current screening list.

    Returns a dict with client_id, names screened, new matches, and status.
    """
    from tools.screening_list import search_screening_list

    result = {
        "client_id": client_id,
        "names_screened": [],
        "new_matches": [],
        "prior_sanctions_records": 0,
        "status": "ok",
    }

    # Load checkpoint for client data
    cp_path = client_dir / "checkpoint.json"
    if not cp_path.exists():
        result["status"] = "no_checkpoint"
        return result

    try:
        checkpoint = json.loads(cp_path.read_text(encoding="utf-8"))
    except Exception as e:
        result["status"] = f"checkpoint_error: {e}"
        return result

    client_data = checkpoint.get("client_data", {})
    if not client_data:
        result["status"] = "no_client_data"
        return result

    # Collect names to screen
    names: list[str] = []
    primary_name = client_data.get("full_name") or client_data.get("legal_name", "")
    if primary_name:
        names.append(primary_name)

    # UBOs
    for ubo in client_data.get("beneficial_owners", []):
        ubo_name = ubo.get("full_name", "")
        if ubo_name:
            names.append(ubo_name)

    result["names_screened"] = names

    # Load prior evidence for comparison
    es_path = client_dir / "02_investigation" / "evidence_store.json"
    prior_sanctions_eids: set[str] = set()
    if es_path.exists():
        try:
            evidence = json.loads(es_path.read_text(encoding="utf-8"))
            for er in evidence:
                if (er.get("source_name", "").lower() in ("individualsanctions", "entitysanctions", "uboscreening")
                        and er.get("disposition") in ("POTENTIAL_MATCH", "CONFIRMED_MATCH")):
                    prior_sanctions_eids.add(er.get("evidence_id", ""))
            result["prior_sanctions_records"] = len(prior_sanctions_eids)
        except Exception:
            pass

    # Screen each name
    for name in names:
        try:
            screening_result = await search_screening_list(name, fuzzy=True, threshold=0.75)
            matches = screening_result.get("matches", [])
            for m in matches:
                match_info = {
                    "name_screened": name,
                    "matched_name": m.get("name", ""),
                    "list_name": m.get("source", ""),
                    "score": m.get("score", 0),
                }
                result["new_matches"].append(match_info)
        except Exception as e:
            logger.warning("Screening failed for %s: %s", name, e)
            result["status"] = f"partial_error: {e}"

    return result


async def run_monitoring(results_dir: str, *, verbose: bool = True) -> int:
    """Scan all client results and re-screen against current sanctions lists.

    Returns exit code (0 = clean, 1 = new matches found).
    """
    results_path = Path(results_dir)
    if not results_path.is_dir():
        console.print(f"[bold red]Error:[/bold red] Directory not found: {results_dir}")
        return 1

    # Find all client directories with checkpoints
    client_dirs = sorted([
        d for d in results_path.iterdir()
        if d.is_dir() and (d / "checkpoint.json").exists()
        and not d.name.startswith("_")
    ])

    if not client_dirs:
        console.print(f"[yellow]No client results found in {results_dir}[/yellow]")
        return 0

    console.print(f"\n[bold blue]Continuous Monitoring[/bold blue]: {len(client_dirs)} client(s)\n")

    # Screen all clients
    all_results: list[dict] = []
    new_match_count = 0

    for cd in client_dirs:
        client_id = cd.name
        if verbose:
            console.print(f"  Screening: {client_id}...", end=" ")

        result = await _screen_client(client_id, cd)
        all_results.append(result)

        n_matches = len(result["new_matches"])
        new_match_count += n_matches

        if verbose:
            if n_matches:
                console.print(f"[red]{n_matches} match(es)[/red]")
            elif result["status"] != "ok":
                console.print(f"[yellow]{result['status']}[/yellow]")
            else:
                console.print("[green]clear[/green]")

        # Write per-client monitoring report
        report_path = cd / "monitoring_report.json"
        report = {
            "client_id": client_id,
            "screened_at": datetime.now().isoformat(),
            "names_screened": result["names_screened"],
            "new_matches": result["new_matches"],
            "prior_sanctions_records": result["prior_sanctions_records"],
            "status": result["status"],
        }
        report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    # Summary table
    console.print()
    table = Table(title="Monitoring Summary")
    table.add_column("Client ID", style="cyan")
    table.add_column("Names Screened", justify="right")
    table.add_column("New Matches", justify="right")
    table.add_column("Prior Sanctions", justify="right")
    table.add_column("Status")

    for r in all_results:
        match_style = "red" if r["new_matches"] else "green"
        status_style = "green" if r["status"] == "ok" else "yellow"
        table.add_row(
            r["client_id"],
            str(len(r["names_screened"])),
            f"[{match_style}]{len(r['new_matches'])}[/{match_style}]",
            str(r["prior_sanctions_records"]),
            f"[{status_style}]{r['status']}[/{status_style}]",
        )

    console.print(table)

    if new_match_count:
        console.print(f"\n[bold red]{new_match_count} new match(es) found — review monitoring_report.json files[/bold red]")
        return 1
    else:
        console.print("\n[green]All clients clear — no new sanctions matches[/green]")
        return 0
