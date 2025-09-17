"""Shared data structures used across scraping and processing."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class RawOffer:
    """A raw travel offer as returned by a scraping backend."""

    provider: str
    title: str
    price: Optional[float]
    url: str
    metadata: Dict[str, Any]
