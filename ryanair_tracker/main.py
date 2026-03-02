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

from .flights import fetch_round_trips
from .storage import load_history, save_run
from .deals import evaluate_deal
from .notify import notify

app = typer.Typer(help="Daily Ryanair deal tracker from VIE airport.")
console = Console()


@app.command()
def search(
    origin: Annotated[str, typer.Option("--origin", "-o", help="Origin IATA code")] = "VIE",
    destinations: Annotated[list[str], typer.Option("--dest", "-d", help="Destination country codes (GR, IT, ES)")] = None,
    dest_airport: Annotated[str, typer.Option("--dest-airport", help="Specific destination airport IATA (e.g. RMI)")] = "",
    days_ahead: Annotated[int, typer.Option(help="How many days ahead to search")] = 90,
    date_from_str: Annotated[str, typer.Option("--date-from", help="Start date YYYY-MM-DD (default: today)")] = "",
    date_to_str: Annotated[str, typer.Option("--date-to", help="End date YYYY-MM-DD (overrides --days-ahead)")] = "",
    depart_after: Annotated[str, typer.Option(help="Earliest departure time HH:MM")] = "09:30",
    depart_before: Annotated[str, typer.Option(help="Latest departure time HH:MM")] = "17:30",
    min_nights: Annotated[int, typer.Option(help="Minimum trip duration in nights")] = 1,
    max_nights: Annotated[int, typer.Option(help="Maximum trip duration in nights")] = 14,
    max_price: Annotated[float, typer.Option(help="Max round-trip price in EUR (0 = no limit)")] = 0,
    deal_threshold_pct: Annotated[float, typer.Option(help="% below historical avg to flag as deal")] = 20.0,
    output_dir: Annotated[Path, typer.Option(help="Directory for XML output")] = Path("./data"),
    currency: Annotated[str, typer.Option(help="Currency for prices")] = "EUR",
    tg_token: Annotated[str, typer.Option("--tg-token", envvar="TG_TOKEN", help="Telegram bot token for push notifications")] = "",
    chats_file: Annotated[Path, typer.Option("--chats-file", help="Path to chats JSON file")] = Path("./data/chats.json"),
):
    """Fetch round-trip flights from VIE to Greece/Italy/Spain and flag cheap deals."""

    if destinations is None and not dest_airport:
        destinations = ["GR", "IT", "ES"]
    elif destinations is None:
        destinations = []

    time_from = datetime.strptime(depart_after, "%H:%M").time()
    time_to = datetime.strptime(depart_before, "%H:%M").time()
    date_from = date.fromisoformat(date_from_str) if date_from_str else date.today()
    date_to = date.fromisoformat(date_to_str) if date_to_str else date_from + timedelta(days=days_ahead)

    output_dir.mkdir(parents=True, exist_ok=True)

    dest_label = dest_airport if dest_airport else ', '.join(destinations)
    console.rule(f"[bold blue]Ryanair Tracker — {origin} → {dest_label}")
    console.print(f"Search window: [cyan]{date_from}[/] → [cyan]{date_to}[/]")
    console.print(f"Departure time filter: [cyan]{depart_after}[/] – [cyan]{depart_before}[/]")
    console.print(f"Trip duration: [cyan]{min_nights}[/]–[cyan]{max_nights}[/] nights")

    history = load_history(output_dir)

    with console.status("Fetching flights..."):
        flights = fetch_round_trips(
            origin=origin,
            country_codes=destinations,
            dest_airport=dest_airport or None,
            date_from=date_from,
            date_to=date_to,
            time_from=time_from,
            time_to=time_to,
            max_price=max_price or None,
            currency=currency,
            min_nights=min_nights,
            max_nights=max_nights,
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

    if tg_token:
        from .bot.common import build_cli_message
        msg = build_cli_message(deals, len(results))
        notify(tg_token, msg, chats_file)
        console.print("[dim]Push notification sent.[/dim]")


def _print_table(results: list[dict], title: str = "Flights") -> None:
    table = Table(title=title, show_lines=False)
    table.add_column("Outbound", style="cyan")
    table.add_column("Return", style="cyan")
    table.add_column("Dest")
    table.add_column("Depart", justify="center")
    table.add_column("Return Depart", justify="center")
    table.add_column("Nights", justify="center")
    table.add_column("Price", justify="right")
    table.add_column("Avg (hist)", justify="right", style="dim")
    table.add_column("Deal?", justify="center")

    for r in sorted(results, key=lambda x: x["total_price"]):
        deal_flag = "[bold green]✓ DEAL[/]" if r["is_deal"] else ""
        avg = f"{r['historical_avg']:.0f}" if r["historical_avg"] else "—"
        # Show date and time on one line, trimming year for brevity
        out_dt = r["outbound_depart"][5:]  # "MM-DD HH:MM"
        ret_dt = r["return_depart"][5:]
        table.add_row(
            r["outbound_flight"],
            r["return_flight"],
            r["destination"],
            out_dt,
            ret_dt,
            str(r.get("nights", "?")),
            f"{r['total_price']:.0f} {r['currency']}",
            avg,
            deal_flag,
        )

    console.print(table)


if __name__ == "__main__":
    app()
