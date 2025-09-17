import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_core.config import AgentConfig
from agent_core.processor import prepare_offers, summarise_offers
from agent_core.reporter import build_report
from agent_core.models import RawOffer


class ProcessorPipelineTests(unittest.TestCase):
    def test_offers_without_price_are_preserved_but_not_counted(self) -> None:
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

        self.assertEqual(len(processed_offers), 2)
        offers_by_provider = {offer.provider: offer for offer in processed_offers}
        self.assertIn("NoPrice", offers_by_provider)
        self.assertIsNone(offers_by_provider["NoPrice"].price)
        self.assertIn("Valid", offers_by_provider)
        self.assertAlmostEqual(offers_by_provider["Valid"].price or 0, 999.0)

        summary = summarise_offers(processed_offers)
        self.assertEqual(summary["count"], 1)
        self.assertAlmostEqual(summary["average_price"], 999.0)
        self.assertAlmostEqual(summary["min_price"], 999.0)

        report = build_report(config, processed_offers)
        self.assertIn("NoPrice", report)
        self.assertIn("| NoPrice | Berlin | – |", report)
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


    def test_report_when_only_offers_without_prices_remain(self) -> None:
        config = AgentConfig(destinations=["Berlin"], budget=500.0)
        raw_offers = [
            RawOffer(
                provider="NoPrice",
                title="Ohne Preis",
                price=None,
                url="https://example.com/ohne-preis",
                metadata={},
            ),
            RawOffer(
                provider="TooExpensive",
                title="Zu teuer",
                price=1500.0,
                url="https://example.com/zu-teuer",
                metadata={},
            ),
        ]

        processed_offers = prepare_offers(raw_offers, config)

        self.assertEqual(len(processed_offers), 1)
        self.assertEqual(processed_offers[0].provider, "NoPrice")
        self.assertIsNone(processed_offers[0].price)

        summary = summarise_offers(processed_offers)
        self.assertEqual(summary["count"], 0)

        report = build_report(config, processed_offers)
        self.assertIn("Keine Angebote mit Preisangabe", report)
        self.assertIn("| NoPrice | Berlin | – |", report)


if __name__ == "__main__":
    unittest.main()
