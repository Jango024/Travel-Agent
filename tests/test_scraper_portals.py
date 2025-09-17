"""Tests for portal specific Playwright scrapers."""

from __future__ import annotations

from typing import Dict, List, Optional

import pytest

from agent_core.config import AgentConfig
from agent_core.scraper import RawOffer, _search_holidaycheck


class _StubLocator:
    """Minimal locator stub that records click/fill invocations."""

    def __init__(self) -> None:
        self.clicks: List[int] = []
        self.fill_values: List[str] = []

    @property
    def first(self) -> "_StubLocator":
        return self

    async def click(self, timeout: int | None = None) -> None:
        self.clicks.append(timeout or 0)

    async def fill(self, value: str) -> None:
        self.fill_values.append(value)


class _StubElement:
    def __init__(self, text: str = "", attributes: Optional[Dict[str, str]] = None) -> None:
        self._text = text
        self._attributes = attributes or {}

    async def inner_text(self) -> str:
        return self._text

    async def text_content(self) -> str:
        return self._text

    async def get_attribute(self, name: str) -> Optional[str]:
        return self._attributes.get(name)


class _StubCard:
    def __init__(
        self,
        title: str,
        href: str,
        price_text: str,
        board: str = "",
        duration: str = "",
        rating: str = "",
    ) -> None:
        self._elements: Dict[str, _StubElement] = {
            "[data-testid='offer-title']": _StubElement(title),
            ".offer-title": _StubElement(title),
            "header h3": _StubElement(title),
            "a[data-testid='offer-link']": _StubElement("", {"href": href}),
            "a[href]": _StubElement("", {"href": href}),
            "[data-testid='offer-price']": _StubElement(price_text),
            ".offer-price": _StubElement(price_text),
        }
        if board:
            self._elements["[data-testid='offer-board']"] = _StubElement(board)
        if duration:
            self._elements["[data-testid='offer-duration']"] = _StubElement(duration)
        if rating:
            self._elements["[data-testid='offer-rating']"] = _StubElement(rating)

    async def query_selector(self, selector: str) -> Optional[_StubElement]:
        return self._elements.get(selector)


class _StubPage:
    """Imitates the small Playwright API surface used in tests."""

    def __init__(self, cards: Optional[List[_StubCard]] = None) -> None:
        self.cards = cards or []
        self.goto_calls: List[tuple[str, Optional[str]]] = []
        self.filled: Dict[str, str] = {}
        self.selected: Dict[str, str] = {}
        self.clicks: List[str] = []
        self.load_states: List[str] = []

    async def goto(self, url: str, wait_until: Optional[str] = None) -> None:
        self.goto_calls.append((url, wait_until))

    async def fill(self, selector: str, value: str) -> None:
        self.filled[selector] = value

    def locator(self, selector: str) -> _StubLocator:
        return _StubLocator()

    async def select_option(self, selector: str, value: str) -> None:
        self.selected[selector] = value

    async def click(self, selector: str) -> None:
        self.clicks.append(selector)

    async def wait_for_load_state(self, state: str) -> None:
        self.load_states.append(state)

    async def query_selector_all(self, selector: str) -> List[_StubCard]:
        if selector in {
            "[data-testid='offer-card']",
            "article[data-testid='hc-result-card']",
            "article",
        }:
            return self.cards
        return []


@pytest.fixture
def anyio_backend() -> str:
    """Restrict anyio tests to the asyncio backend for deterministic behaviour."""

    return "asyncio"


@pytest.mark.anyio
async def test_search_holidaycheck_returns_raw_offers() -> None:
    """HolidayCheck scraping should transform cards into RawOffer objects."""

    page = _StubPage(
        cards=[
            _StubCard(
                title="Hotel Mallorca",
                href="/offers/1",
                price_text="ab 999 €",
                board="Halbpension",
                duration="7 Nächte",
                rating="95 % Weiterempfehlung",
            )
        ]
    )
    config = AgentConfig(destinations=["Mallorca"], travellers=2, budget=1200.0)

    offers = await _search_holidaycheck(page, config, "Mallorca")

    assert offers, "expected at least one RawOffer"

    offer = offers[0]
    assert isinstance(offer, RawOffer)
    assert offer.provider == "holidaycheck.de"
    assert offer.title == "Hotel Mallorca"
    assert offer.url == "https://www.holidaycheck.de/offers/1"
    assert offer.price == 999.0
    assert offer.metadata["destination"] == "Mallorca"
    assert offer.metadata["travellers"] == 2
    assert offer.metadata["board"] == "Halbpension"
    assert offer.metadata.get("recommendation_score") == 95.0

    # The stubbed inputs should have been filled with search parameters.
    assert page.filled["input[name='destination']"] == "Mallorca"
    assert page.selected.get("select[name='travellers']") == "2"
