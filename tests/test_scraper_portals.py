"""Tests for portal specific Playwright scrapers."""

from __future__ import annotations

from typing import Dict, List, Optional

import pytest

from agent_core.config import AgentConfig
from agent_core.models import RawOffer
from agent_core.sources.portal_playwright import PORTAL_HANDLERS


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
        extra_selectors: Optional[Dict[str, _StubElement]] = None,
    ) -> None:
        self._elements: Dict[str, _StubElement] = {
            "[data-testid='offer-title']": _StubElement(title),
            "[data-testid='result-title']": _StubElement(title),
            ".offer-title": _StubElement(title),
            "header h3": _StubElement(title),
            "a[data-testid='offer-link']": _StubElement("", {"href": href}),
            "a[data-testid='result-link']": _StubElement("", {"href": href}),
            "a[href]": _StubElement("", {"href": href}),
            "[data-testid='offer-price']": _StubElement(price_text),
            "[data-testid='result-price']": _StubElement(price_text),
            ".offer-price": _StubElement(price_text),
            ".price": _StubElement(price_text),
        }
        if board:
            self._elements["[data-testid='offer-board']"] = _StubElement(board)
            self._elements["[data-testid='result-board']"] = _StubElement(board)
            self._elements[".board"] = _StubElement(board)
        if duration:
            self._elements["[data-testid='offer-duration']"] = _StubElement(duration)
            self._elements["[data-testid='result-duration']"] = _StubElement(duration)
            self._elements[".duration"] = _StubElement(duration)
        if rating:
            self._elements["[data-testid='offer-rating']"] = _StubElement(rating)
            self._elements["[data-testid='result-rating']"] = _StubElement(rating)
            self._elements[".rating"] = _StubElement(rating)
        if extra_selectors:
            self._elements.update(extra_selectors)

    async def query_selector(self, selector: str) -> Optional[_StubElement]:
        return self._elements.get(selector)


class _StubPage:
    """Imitates the small Playwright API surface used in tests."""

    def __init__(
        self,
        cards: Optional[List[_StubCard]] = None,
        card_selectors: Optional[List[str]] = None,
    ) -> None:
        self.cards = cards or []
        self.goto_calls: List[tuple[str, Optional[str]]] = []
        self.filled: Dict[str, str] = {}
        self.selected: Dict[str, str] = {}
        self.clicks: List[str] = []
        self.load_states: List[str] = []
        default_card_selectors = [
            "[data-testid='offer-card']",
            "article[data-testid='hc-result-card']",
            "article[data-testid='offer-card']",
            "[data-testid='result-card']",
            "article[data-testid='result-card']",
            "article",
        ]
        self.card_selectors = card_selectors or default_card_selectors

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
        if selector in self.card_selectors:
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

    offers = await PORTAL_HANDLERS["holidaycheck.de"](page, config, "Mallorca")

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


@pytest.mark.anyio
async def test_search_tui_returns_raw_offers() -> None:
    """TUI scraper should convert cards into RawOffer instances."""

    page = _StubPage(
        cards=[
            _StubCard(
                title="TUI Strandresort",
                href="/angebot/42",
                price_text="ab 1.199 €",
                board="All Inclusive",
                duration="10 Nächte",
            )
        ]
    )
    config = AgentConfig(destinations=["Kreta"], travellers=3, budget=2000.0)

    offers = await PORTAL_HANDLERS["tui.com"](page, config, "Kreta")

    assert offers, "expected at least one RawOffer"

    offer = offers[0]
    assert offer.provider == "tui.com"
    assert offer.title == "TUI Strandresort"
    assert offer.url == "https://www.tui.com/angebot/42"
    assert offer.price == 1199.0
    assert offer.metadata["destination"] == "Kreta"
    assert offer.metadata["travellers"] == 3
    assert offer.metadata["board"] == "All Inclusive"

    assert page.filled["input[name='q']"] == "Kreta"
    assert page.selected.get("select[name='travellers']") == "3"
    assert page.filled.get("input[name='maxPrice']") == "2000"


@pytest.mark.anyio
async def test_search_abindenurlaub_returns_raw_offers() -> None:
    """ab-in-den-urlaub scraper should parse RawOffer instances."""

    page = _StubPage(
        cards=[
            _StubCard(
                title="AIU Familienhotel",
                href="/reise/7",
                price_text="1.499 €",
                board="Frühstück",
                duration="5 Nächte",
                rating="90 % Weiterempfehlung",
            )
        ]
    )
    config = AgentConfig(destinations=["Barcelona"], travellers=2, budget=1800.0)

    offers = await PORTAL_HANDLERS["ab-in-den-urlaub.de"](page, config, "Barcelona")

    assert offers, "expected at least one RawOffer"

    offer = offers[0]
    assert offer.provider == "ab-in-den-urlaub.de"
    assert offer.title == "AIU Familienhotel"
    assert offer.url == "https://www.ab-in-den-urlaub.de/reise/7"
    assert offer.price == 1499.0
    assert offer.metadata["destination"] == "Barcelona"
    assert offer.metadata["travellers"] == 2
    assert offer.metadata["board"] == "Frühstück"
    assert offer.metadata.get("recommendation_score") == 90.0

    assert page.filled["input[name='destination']"] == "Barcelona"
    assert page.selected.get("select[name='travellers']") == "2"
    assert page.filled.get("input[name='budget']") == "1800"


@pytest.mark.anyio
async def test_search_weg_returns_raw_offers() -> None:
    """weg.de scraper should populate RawOffer instances."""

    page = _StubPage(
        cards=[
            _StubCard(
                title="WEG Citytrip",
                href="/travel/9",
                price_text="799 €",
                board="Ohne Verpflegung",
                duration="4 Nächte",
            )
        ]
    )
    config = AgentConfig(destinations=["London"], travellers=1, budget=900.0)

    offers = await PORTAL_HANDLERS["weg.de"](page, config, "London")

    assert offers, "expected at least one RawOffer"

    offer = offers[0]
    assert offer.provider == "weg.de"
    assert offer.title == "WEG Citytrip"
    assert offer.url == "https://www.weg.de/travel/9"
    assert offer.price == 799.0
    assert offer.metadata["destination"] == "London"
    assert offer.metadata["travellers"] == 1
    assert offer.metadata["board"] == "Ohne Verpflegung"

    assert page.filled["input[name='destination']"] == "London"
    assert page.selected.get("select[name='travellers']") == "1"
    assert page.filled.get("input[name='budget']") == "900"
