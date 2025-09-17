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

    def test_star_and_recommendation_filters_are_applied(self) -> None:
        config = AgentConfig(
            destinations=["Kreta"], min_star_rating=4.0, min_recommendation_score=90.0
        )
        raw_offers = [
            RawOffer(
                provider="Preferred",
                title="Top Hotel",
                price=899.0,
                url="https://example.com/top",
                metadata={"star_rating": 4.5, "recommendation_score": 95.0},
            ),
            RawOffer(
                provider="LowStars",
                title="Drei Sterne",
                price=799.0,
                url="https://example.com/low",
                metadata={"star_rating": 3.5, "recommendation_score": 96.0},
            ),
            RawOffer(
                provider="LowRec",
                title="Geringe Empfehlung",
                price=750.0,
                url="https://example.com/rec",
                metadata={"star_rating": 4.2, "recommendation_score": 80.0},
            ),
        ]

        processed_offers = prepare_offers(raw_offers, config)

        self.assertEqual(len(processed_offers), 1)
        self.assertEqual(processed_offers[0].provider, "Preferred")
        self.assertAlmostEqual(processed_offers[0].star_rating or 0, 4.5)
        self.assertAlmostEqual(processed_offers[0].recommendation_score or 0, 95.0)

        summary = summarise_offers(processed_offers)
        self.assertEqual(summary["count"], 1)


if __name__ == "__main__":
    unittest.main()
