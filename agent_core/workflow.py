"""High level orchestration for running the travel agent pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Set

from .config import AgentConfig
from .processor import ProcessedOffer, prepare_offers, summarise_offers
from .reporter import build_report
from .scraper import RawOffer, scrape_sources


@dataclass
class AgentResult:
    """Result returned by :func:`run_agent_workflow`."""

    config: AgentConfig
    raw_offers: List[RawOffer]
    offers: List[ProcessedOffer]
    report: str
    summary: Dict[str, float]
    warnings: List[str]

    def to_dict(self) -> Dict[str, object]:
        return {
            "config": self.config.to_dict(),
            "summary": self.summary,
            "offers": [offer.to_dict() for offer in self.offers],
            "report": self.report,
            "warnings": list(self.warnings),
            "raw_offers": [offer.to_dict() for offer in self.raw_offers],
        }


def run_agent_workflow(config: AgentConfig) -> AgentResult:
    """Execute the full data acquisition and reporting pipeline."""

    raw_offers = scrape_sources(config)
    warnings = _collect_mock_warnings(raw_offers)
    offers = prepare_offers(raw_offers, config)
    summary = summarise_offers(offers)
    report = build_report(config, offers, warnings=warnings)
    return AgentResult(
        config=config,
        raw_offers=raw_offers,
        offers=offers,
        summary=summary,
        report=report,
        warnings=warnings,
    )


def _collect_mock_warnings(raw_offers: List[RawOffer]) -> List[str]:
    """Inspect raw offers and derive user-facing warnings for mock data."""

    mock_reasons: Set[str] = {
        str(offer.metadata.get("mock_reason"))
        for offer in raw_offers
        if offer.metadata.get("mock_reason")
    }
    if not mock_reasons:
        return []

    readable_reasons = []
    reason_messages = {
        "playwright-missing": "Playwright nicht verfügbar",
        "playwright-empty": "keine Ergebnisse von Playwright erhalten",
    }
    for reason in sorted(mock_reasons):
        readable_reasons.append(reason_messages.get(reason, reason))

    if readable_reasons:
        details = "; ".join(readable_reasons)
        message = f"Playwright-Suche fehlgeschlagen, zeige Beispielangebote (Details: {details})."
    else:
        message = "Playwright-Suche fehlgeschlagen, zeige Beispielangebote."
    return [message]
