"""Reporting helpers for the travel agent."""
from __future__ import annotations

from datetime import date
import math
from typing import Iterable, List, Sequence

from .config import AgentConfig
from .processor import ProcessedOffer, summarise_offers


def _format_date(value: date | None) -> str:
    if value is None:
        return "flexibel"
    return value.strftime("%d.%m.%Y")


def generate_offer_table(offers: Iterable[ProcessedOffer]) -> str:
    """Return a markdown-style table with the best offers."""

    offer_list = list(offers)
    include_star = any(offer.star_rating is not None for offer in offer_list)
    include_recommendation = any(offer.recommendation_score is not None for offer in offer_list)

    headers = ["Anbieter", "Ziel", "Preis", "Nächte", "Verpflegung"]
    if include_star:
        headers.append("Sterne")
    if include_recommendation:
        headers.append("Weiterempfehlung")

    header_row = "| " + " | ".join(headers) + " |"
    separator_row = "| " + " | ".join(["---"] * len(headers)) + " |"

    rows: List[str] = [header_row, separator_row]

    if not offer_list:
        rows.append("| Keine Treffer |" + " |" * (len(headers) - 1))
        return "\n".join(rows)

    placeholder = "–"

    for offer in offer_list:
        price_value = offer.price
        if price_value is None:
            price_column = placeholder
        else:
            try:
                numeric_price = float(price_value)
            except (TypeError, ValueError):
                price_column = placeholder
            else:
                price_column = placeholder if math.isnan(numeric_price) else f"{numeric_price:.0f} €"

        columns = [
            offer.provider,
            offer.destination,
            price_column,
            str(offer.nights),
            offer.board,
        ]
        if include_star:
            columns.append(f"{offer.star_rating:.1f}" if offer.star_rating is not None else "-")
        if include_recommendation:
            columns.append(
                f"{offer.recommendation_score:.0f}%" if offer.recommendation_score is not None else "-"
            )
        rows.append("| " + " | ".join(columns) + " |")
    return "\n".join(rows)


def build_report(
    config: AgentConfig, offers: List[ProcessedOffer], warnings: Sequence[str] | None = None
) -> str:
    """Create a text report summarising the results."""

    summary = summarise_offers(offers)
    warning_messages = [message.strip() for message in (warnings or []) if message]
    lines: List[str] = [
        "Reise-Report",
        "============",
    ]
    if warning_messages:
        lines.append("")
        lines.extend(f"WARNUNG: {message}" for message in warning_messages)

    lines.extend(
        [
            "",
            f"Ziele: {', '.join(config.destinations)}",
        f"Zeitraum: {_format_date(config.departure_date)} – {_format_date(config.return_date)}",
        f"Reisende: {config.travellers}",
        ]
    )
    if config.budget:
        lines.append(f"Budget: {config.budget:.0f} €")
    if config.board_types:
        lines.append(f"Verpflegungswunsch: {', '.join(config.board_types)}")
    if config.preferred_sources:
        lines.append(f"Bevorzugte Portale: {', '.join(config.preferred_sources)}")
    if config.min_star_rating is not None:
        star_value = ("{:.1f}".format(config.min_star_rating)).rstrip("0").rstrip(".")
        lines.append(f"Mindestens {star_value} Sterne")
    if config.min_recommendation_score is not None:
        lines.append(f"Mindestens {config.min_recommendation_score:.0f}% Weiterempfehlung")
    if config.notes:
        lines.append("")
        lines.append("Zusatzinformationen:")
        lines.append(config.notes.strip())

    lines.append("")
    lines.append("Zusammenfassung:")
    if summary["count"] == 0:
        if offers:
            lines.append("- Keine Angebote mit Preisangabe gefunden")
        else:
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
