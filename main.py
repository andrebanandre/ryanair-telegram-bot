"""
Ryanair Deal Tracker — daily CLI to find cheap round-trips from VIE.
Usage: poetry run ryanair-tracker search [OPTIONS]
"""

from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from ryanair_tracker.flights import fetch_round_trips
from ryanair_tracker.storage import load_history, save_run
from ryanair_tracker.deals import evaluate_deal

app = typer.Typer(help="Daily Ryanair deal tracker from VIE airport.")
console = Console()


@app.command()
def search(
    origin: Annotated[str, typer.Option("--origin", "-o", help="Origin IATA code")] = "VIE",
    destinations: Annotated[list[str], typer.Option("--dest", "-d", help="Destination country codes (GR, IT, ES)")] = None,
    days_ahead: Annotated[int, typer.Option(help="How many days ahead to search")] = 90,
    depart_after: Annotated[str, typer.Option(help="Earliest departure time HH:MM")] = "09:30",
    depart_before: Annotated[str, typer.Option(help="Latest departure time HH:MM")] = "17:30",
    max_price: Annotated[float, typer.Option(help="Max round-trip price in EUR (0 = no limit)")] = 0,
    deal_threshold_pct: Annotated[float, typer.Option(help="% below historical avg to flag as deal")] = 20.0,
    output_dir: Annotated[Path, typer.Option(help="Directory for XML output")] = Path("./data"),
    currency: Annotated[str, typer.Option(help="Currency for prices")] = "EUR",
):
    """Fetch round-trip flights from VIE to Greece/Italy/Spain and flag cheap deals."""

    if destinations is None:
        destinations = ["GR", "IT", "ES"]

    time_from = datetime.strptime(depart_after, "%H:%M").time()
    time_to = datetime.strptime(depart_before, "%H:%M").time()
    date_from = date.today()
    date_to = date_from + timedelta(days=days_ahead)

    output_dir.mkdir(parents=True, exist_ok=True)

    console.rule(f"[bold blue]Ryanair Tracker — {origin} → {', '.join(destinations)}")
    console.print(f"Search window: [cyan]{date_from}[/] → [cyan]{date_to}[/]")
    console.print(f"Departure time filter: [cyan]{depart_after}[/] – [cyan]{depart_before}[/]")

    history = load_history(output_dir)

    with console.status("Fetching flights..."):
        flights = fetch_round_trips(
            origin=origin,
            country_codes=destinations,
            date_from=date_from,
            date_to=date_to,
            time_from=time_from,
            time_to=time_to,
            max_price=max_price or None,
            currency=currency,
        )

    if not flights:
        console.print("[yellow]No flights found matching your criteria.[/]")
        raise typer.Exit()

    # Evaluate deals
    results = [evaluate_deal(f, history, deal_threshold_pct) for f in flights]
    deals = [r for r in results if r["is_deal"]]

    # Save to XML
    xml_path = save_run(output_dir, results)
    console.print(f"\nSaved [green]{len(results)}[/] flights → [dim]{xml_path}[/]")

    # Display table
    _print_table(results)

    if deals:
        console.print(f"\n🔥 [bold green]{len(deals)} DEAL(S) FOUND[/bold green]")
        _print_table(deals, title="🔥 Hot Deals")
    else:
        console.print("\n[dim]No deals vs historical average this run.[/dim]")


def _print_table(results: list[dict], title: str = "Flights") -> None:
    table = Table(title=title, show_lines=False)
    table.add_column("Outbound", style="cyan")
    table.add_column("Return", style="cyan")
    table.add_column("Destination")
    table.add_column("Depart", justify="center")
    table.add_column("Return Depart", justify="center")
    table.add_column("Price", justify="right")
    table.add_column("Avg (hist)", justify="right", style="dim")
    table.add_column("Deal?", justify="center")

    for r in sorted(results, key=lambda x: x["total_price"]):
        deal_flag = "[bold green]✓ DEAL[/]" if r["is_deal"] else ""
        avg = f"{r['historical_avg']:.0f}" if r["historical_avg"] else "—"
        table.add_row(
            r["outbound_flight"],
            r["return_flight"],
            r["destination"],
            r["outbound_depart"],
            r["return_depart"],
            f"{r['total_price']:.0f} {r['currency']}",
            avg,
            deal_flag,
        )

    console.print(table)


if __name__ == "__main__":
    app()
