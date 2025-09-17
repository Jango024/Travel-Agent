import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_core.config import AgentConfig
from agent_core.processor import prepare_offers, summarise_offers
from agent_core.reporter import build_report
from agent_core.scraper import RawOffer


class ProcessorPipelineTests(unittest.TestCase):
    def test_offers_without_price_do_not_influence_statistics(self) -> None:
        config = AgentConfig(destinations=["Berlin"])
        raw_offers = [
            RawOffer(
                provider="NoPrice",
                title="Ohne Preis",
                price=None,
                url="https://example.com/ohne-preis",
                metadata={},
            ),
            RawOffer(
                provider="Valid",
                title="Mit Preis",
                price=999.0,
                url="https://example.com/mit-preis",
                metadata={},
            ),
        ]

        processed_offers = prepare_offers(raw_offers, config)

        self.assertEqual(len(processed_offers), 1)
        self.assertEqual(processed_offers[0].provider, "Valid")

        summary = summarise_offers(processed_offers)
        self.assertEqual(summary["count"], 1)
        self.assertAlmostEqual(summary["average_price"], 999.0)
        self.assertAlmostEqual(summary["min_price"], 999.0)

        report = build_report(config, processed_offers)
        self.assertNotIn("nan", report.lower())


if __name__ == "__main__":
    unittest.main()
