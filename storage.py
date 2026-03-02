"""
XML persistence for flight runs.
Each run is saved as: data/YYYY-MM-DD.xml
History is loaded from all past XML files to compute averages.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from lxml import etree


def save_run(output_dir: Path, results: list[dict]) -> Path:
    """Serialize today's results to XML and return the file path."""
    today = date.today().isoformat()
    xml_path = output_dir / f"{today}.xml"

    root = etree.Element("flights", run_date=today)

    for r in results:
        flight = etree.SubElement(root, "flight")
        for key, val in r.items():
            etree.SubElement(flight, key).text = str(val)

    tree = etree.ElementTree(root)
    tree.write(xml_path, pretty_print=True, xml_declaration=True, encoding="UTF-8")

    return xml_path


def load_history(output_dir: Path) -> dict[str, list[float]]:
    """
    Load all past XML runs and return a dict mapping
    route_key → [price, price, ...] for historical average computation.
    """
    history: dict[str, list[float]] = {}

    for xml_file in sorted(output_dir.glob("*.xml")):
        try:
            tree = etree.parse(xml_file)
        except Exception:
            continue

        for flight in tree.getroot().findall("flight"):
            key = _route_key(flight)
            price_el = flight.find("total_price")
            if price_el is not None and price_el.text:
                history.setdefault(key, []).append(float(price_el.text))

    return history


def _route_key(flight_el: etree._Element) -> str:
    origin = (flight_el.findtext("origin") or "").strip()
    destination = (flight_el.findtext("destination") or "").strip()
    return f"{origin}-{destination}"
