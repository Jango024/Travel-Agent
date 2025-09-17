import importlib.util
import sys
from pathlib import Path
import unittest


_CONFIG_SPEC = importlib.util.spec_from_file_location(
    "agent_core.config", Path(__file__).resolve().parent.parent / "agent_core" / "config.py"
)
assert _CONFIG_SPEC is not None and _CONFIG_SPEC.loader is not None
_CONFIG_MODULE = importlib.util.module_from_spec(_CONFIG_SPEC)
sys.modules[_CONFIG_SPEC.name] = _CONFIG_MODULE
_CONFIG_SPEC.loader.exec_module(_CONFIG_MODULE)

_parse_float = _CONFIG_MODULE._parse_float
create_config_from_form = _CONFIG_MODULE.create_config_from_form
create_config_from_text = _CONFIG_MODULE.create_config_from_text


class ParseFloatTests(unittest.TestCase):
    def test_parse_float_accepts_european_formats(self) -> None:
        for raw, expected in [("1.200€", 1200.0), ("1.200,50", 1200.5)]:
            with self.subTest(raw=raw):
                self.assertEqual(_parse_float(raw), expected)

class ExistingCallerTests(unittest.TestCase):
    def test_create_config_from_form_budget_parses_thousands_separator(self) -> None:
        config = create_config_from_form({"destinations": "Paris", "budget": "1.200€"})
        self.assertEqual(config.budget, 1200.0)

    def test_create_config_from_text_budget_parses_thousands_separator(self) -> None:
        config = create_config_from_text("Wir reisen nach Berlin mit Budget 1.200,50€")
        self.assertEqual(config.budget, 1200.5)

    def test_create_config_from_form_accepts_preferred_sources_and_filters(self) -> None:
        config = create_config_from_form(
            {
                "destinations": "Kreta",
                "preferred_sources": "holidaycheck.de, https://tui.com/",
                "min_star_rating": "4,5",
                "min_recommendation_score": "90%",
            }
        )
        self.assertEqual(config.preferred_sources, ["holidaycheck.de", "https://tui.com/"])
        self.assertAlmostEqual(config.min_star_rating or 0, 4.5)
        self.assertAlmostEqual(config.min_recommendation_score or 0, 90.0)

    def test_create_config_from_text_parses_star_and_recommendation(self) -> None:
        config = create_config_from_text(
            "Suche nach Mallorca mit mindestens 4 Sterne Hotel und 85% Weiterempfehlung"
        )
        self.assertAlmostEqual(config.min_star_rating or 0, 4.0)
        self.assertAlmostEqual(config.min_recommendation_score or 0, 85.0)


if __name__ == "__main__":
    unittest.main()
