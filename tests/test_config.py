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


if __name__ == "__main__":
    unittest.main()
