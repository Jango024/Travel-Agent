"""High level orchestration for running the travel agent pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

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

    def to_dict(self) -> Dict[str, object]:
        return {
            "config": self.config.to_dict(),
            "summary": self.summary,
            "offers": [offer.to_dict() for offer in self.offers],
            "report": self.report,
        }


def run_agent_workflow(config: AgentConfig) -> AgentResult:
    """Execute the full data acquisition and reporting pipeline."""

    raw_offers = scrape_sources(config)
    offers = prepare_offers(raw_offers, config)
    summary = summarise_offers(offers)
    report = build_report(config, offers)
    return AgentResult(config=config, raw_offers=raw_offers, offers=offers, summary=summary, report=report)
