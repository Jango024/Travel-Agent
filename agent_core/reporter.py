"""Reporting helpers for the travel agent."""
from __future__ import annotations

from datetime import date
from typing import Iterable, List

from .config import AgentConfig
from .processor import ProcessedOffer, summarise_offers


def _format_date(value: date | None) -> str:
    if value is None:
        return "flexibel"
    return value.strftime("%d.%m.%Y")


def generate_offer_table(offers: Iterable[ProcessedOffer]) -> str:
    """Return a markdown-style table with the best offers."""

    rows: List[str] = ["| Anbieter | Ziel | Preis | Nächte | Verpflegung |", "| --- | --- | --- | --- | --- |"]
    for offer in offers:
        rows.append(
            f"| {offer.provider} | {offer.destination} | {offer.price:.0f} € | {offer.nights} | {offer.board} |"
        )
    if len(rows) == 2:
        rows.append("| Keine Treffer | | | | |")
    return "\n".join(rows)


def build_report(config: AgentConfig, offers: List[ProcessedOffer]) -> str:
    """Create a text report summarising the results."""

    summary = summarise_offers(offers)
    lines: List[str] = [
        "Reise-Report",
        "============",
        "",
        f"Ziele: {', '.join(config.destinations)}",
        f"Zeitraum: {_format_date(config.departure_date)} – {_format_date(config.return_date)}",
        f"Reisende: {config.travellers}",
    ]
    if config.budget:
        lines.append(f"Budget: {config.budget:.0f} €")
    if config.board_types:
        lines.append(f"Verpflegungswunsch: {', '.join(config.board_types)}")
    if config.notes:
        lines.append("")
        lines.append("Zusatzinformationen:")
        lines.append(config.notes.strip())

    lines.append("")
    lines.append("Zusammenfassung:")
    if summary["count"] == 0:
        lines.append("- Keine Angebote gefunden")
    else:
        lines.append(f"- {summary['count']} Angebote gefunden")
        lines.append(f"- Durchschnittlicher Preis: {summary['average_price']:.0f} €")
        lines.append(f"- Günstigstes Angebot: {summary['min_price']:.0f} €")

    lines.append("")
    lines.append("Top-Angebote:")
    lines.append(generate_offer_table(offers[:5]))

    lines.append("")
    lines.append("Detaillierte Links:")
    for offer in offers[:5]:
        lines.append(f"- {offer.provider}: {offer.url}")

    return "\n".join(lines)
