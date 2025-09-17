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
create_config = _CONFIG_MODULE.create_config

class ParseFloatTests(unittest.TestCase):
    def test_parse_float_removes_euro_thousands_separator(self) -> None:
        self.assertEqual(_parse_float("1.200€"), 1200.0)

    def test_parse_float_handles_decimal_comma_after_thousands_separator(self) -> None:
        self.assertEqual(_parse_float("1.200,50"), 1200.5)


class ExistingCallerTests(unittest.TestCase):
    def test_create_config_from_form_budget_parses_thousands_separator(self) -> None:
        config = create_config_from_form({"destinations": "Paris", "budget": "1.200€"})
        self.assertEqual(config.budget, 1200.0)

    def test_create_config_from_text_budget_parses_thousands_separator(self) -> None:
        config = create_config_from_text("Wir reisen nach Berlin mit Budget 1.200,50€")
        self.assertEqual(config.budget, 1200.5)
        
    def test_create_config_from_form_handles_preferred_sources_and_filters(self) -> None:
        config = create_config_from_form(
            {
                "destinations": "Kreta",
                "preferred_sources": "holidaycheck.de, tui.com",
                "min_star_rating": "4",
                "min_recommendation_score": "85",
            }
        )
        self.assertEqual(config.preferred_sources, ["holidaycheck.de", "tui.com"])
        self.assertAlmostEqual(config.min_star_rating or 0, 4.0)
        self.assertAlmostEqual(config.min_recommendation_score or 0, 85.0)

    def test_create_config_from_text_detects_star_and_recommendation(self) -> None:
        config = create_config_from_text(
            "Bitte Reise nach Rhodos mit 4.5 Sterne Hotel und mindestens 90% Empfehlung"
        )
        self.assertAlmostEqual(config.min_star_rating or 0, 4.5)
        self.assertAlmostEqual(config.min_recommendation_score or 0, 90.0)

class CreateConfigInputTypeTests(unittest.TestCase):
    def test_raises_type_error_for_unsupported_type(self) -> None:
        with self.assertRaisesRegex(TypeError, "expected a mapping or string"):
            create_config(42)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
