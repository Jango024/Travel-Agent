"""Compatibility wrapper exposing :mod:`agent_core.config` for tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


_SOURCE_SPEC = importlib.util.spec_from_file_location(
    "agent_core._compat_config_source",
    Path(__file__).resolve().parent.parent / "config.py",
)
if _SOURCE_SPEC is None or _SOURCE_SPEC.loader is None:
    raise ImportError("Could not load agent_core.config compatibility module")

_SOURCE_MODULE = importlib.util.module_from_spec(_SOURCE_SPEC)
sys.modules[_SOURCE_SPEC.name] = _SOURCE_MODULE
_SOURCE_SPEC.loader.exec_module(_SOURCE_MODULE)

__all__ = getattr(_SOURCE_MODULE, "__all__", [])

for _name in dir(_SOURCE_MODULE):
    if _name.startswith("__") and _name not in {"__all__", "__doc__"}:
        continue
    globals()[_name] = getattr(_SOURCE_MODULE, _name)

del _name
