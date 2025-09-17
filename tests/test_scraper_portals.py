"""Tests for portal specific Playwright scrapers."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

import pytest

import agent_core.scraper as scraper_module
from agent_core.config import AgentConfig
from agent_core.processor import prepare_offers
from agent_core.scraper import RawOffer, _search_holidaycheck, _search_tui


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
        self._elements: Dict[str, _StubElement] = {}

        def _register(selectors: Iterable[str], element: _StubElement) -> None:
            for selector in selectors:
                self._elements[selector] = element

        title_element = _StubElement(title)
        _register(
            [
                "[data-testid='offer-title']",
                ".offer-title",
                ".hotel-name",
                ".product-tile__title",
                "header h3",
            ],
            title_element,
        )

        link_element = _StubElement("", {"href": href})
        _register(["a[data-testid='offer-link']", "a[href]"], link_element)

        price_element = _StubElement(price_text)
        _register(
            [
                "[data-testid='offer-price']",
                ".offer-price",
                ".price",
                "[data-testid='product-price']",
            ],
            price_element,
        )

        if board:
            board_element = _StubElement(board)
            _register(
                [
                    "[data-testid='offer-board']",
                    ".board",
                    "[data-testid='catering']",
                    "[data-testid='product-board']",
                ],
                board_element,
            )
        if duration:
            duration_element = _StubElement(duration)
            _register(
                [
                    "[data-testid='offer-duration']",
                    ".duration",
                    "[data-testid='stay-length']",
                    "[data-testid='product-duration']",
                ],
                duration_element,
            )
        if rating:
            rating_element = _StubElement(rating)
            _register(
                [
                    "[data-testid='offer-rating']",
                    ".rating",
                    "[data-testid='recommendation']",
                ],
                rating_element,
            )

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
            "article[data-testid='result-card']",
            "article[data-testid='product-card']",
            "article",
        }:
            return self.cards
        return []


class _StubPlaywrightContext:
    def __init__(self, page: _StubPage) -> None:
        self._page = page

    async def new_page(self) -> _StubPage:
        return self._page


class _StubPlaywrightBrowser:
    def __init__(self, page: _StubPage) -> None:
        self._page = page

    async def new_context(self, locale: str = "") -> _StubPlaywrightContext:
        return _StubPlaywrightContext(self._page)

    async def close(self) -> None:  # pragma: no cover - trivial
        return None


class _StubFirefoxLauncher:
    def __init__(self, page: _StubPage) -> None:
        self._page = page

    async def launch(self, headless: bool = True) -> _StubPlaywrightBrowser:
        return _StubPlaywrightBrowser(self._page)


class _StubPlaywrightRuntime:
    def __init__(self, page: _StubPage) -> None:
        self.firefox = _StubFirefoxLauncher(page)


class _StubAsyncPlaywright:
    def __init__(self, page: _StubPage) -> None:
        self._runtime = _StubPlaywrightRuntime(page)

    async def __aenter__(self) -> _StubPlaywrightRuntime:
        return self._runtime

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: Any | None
    ) -> bool:  # pragma: no cover - trivial
        return False


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
    assert offer.metadata["duration"] == "7 Nächte"
    assert offer.metadata["nights"] == 7

    # The stubbed inputs should have been filled with search parameters.
    assert page.filled["input[name='destination']"] == "Mallorca"
    assert page.selected.get("select[name='travellers']") == "2"

    # Prepare offers should propagate metadata to the processed result.
    processed_offers = prepare_offers(offers, config)
    assert processed_offers and processed_offers[0].nights == 7


@pytest.mark.anyio
async def test_search_tui_extracts_nights_and_prepares_offers() -> None:
    """TUI scraping should preserve duration metadata and parsed nights."""

    page = _StubPage(
        cards=[
            _StubCard(
                title="Resort Kreta",
                href="/angebote/kreta",
                price_text="1299 €",
                board="All Inclusive",
                duration="10 Tage (7 Übernachtungen)",
            )
        ]
    )
    config = AgentConfig(destinations=["Kreta"], travellers=2)

    offers = await _search_tui(page, config, "Kreta")

    assert offers, "expected at least one RawOffer"

    offer = offers[0]
    assert isinstance(offer, RawOffer)
    assert offer.provider == "tui.com"
    assert offer.metadata["duration"] == "10 Tage (7 Übernachtungen)"
    assert offer.metadata["nights"] == 7

    processed_offers = prepare_offers(offers, config)
    assert processed_offers and processed_offers[0].nights == 7


@pytest.mark.anyio
async def test_search_tui_falls_back_to_days_when_only_days_are_present() -> None:
    """If only days are present the scraper should still set a night count."""

    page = _StubPage(
        cards=[
            _StubCard(
                title="Städtetrip",
                href="/angebote/city",
                price_text="499 €",
                duration="5 Tage",
            )
        ]
    )
    config = AgentConfig(destinations=["Berlin"], travellers=2)

    offers = await _search_tui(page, config, "Berlin")

    assert offers, "expected at least one RawOffer"

    offer = offers[0]
    assert isinstance(offer, RawOffer)
    assert offer.metadata["duration"] == "5 Tage"
    assert offer.metadata["nights"] == 5

    processed_offers = prepare_offers(offers, config)
    assert processed_offers and processed_offers[0].nights == 5


@pytest.mark.anyio
async def test_scrape_with_playwright_uses_alias_for_holidaycheck(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preferred sources like 'HolidayCheck' should resolve to the portal handler."""

    page = _StubPage()
    monkeypatch.setattr(
        scraper_module, "async_playwright", lambda: _StubAsyncPlaywright(page)
    )

    calls: List[tuple[_StubPage, str]] = []

    async def fake_handler(
        page_obj: _StubPage, config: AgentConfig, destination: str
    ) -> List[RawOffer]:
        calls.append((page_obj, destination))
        return [
            RawOffer(
                provider="holidaycheck.de",
                title=f"{destination} Special",
                price=None,
                url="https://www.holidaycheck.de/angebote/1",
                metadata={},
            )
        ]

    monkeypatch.setitem(
        scraper_module._PORTAL_SEARCH_HANDLERS, "holidaycheck.de", fake_handler
    )

    async def fake_duckduckgo(
        page_obj: _StubPage,
        destination: str,
        max_results: int = 5,
        site: str | None = None,
    ) -> List[RawOffer]:
        return []

    monkeypatch.setattr(
        scraper_module, "_extract_duckduckgo_results", fake_duckduckgo
    )

    config = AgentConfig(destinations=["Mallorca"], preferred_sources=["HolidayCheck"])

    offers = await scraper_module._scrape_with_playwright(config)

    assert calls and calls[0][0] is page
    assert calls[0][1] == "Mallorca"
    assert offers and offers[0].provider == "holidaycheck.de"
    assert offers[0].metadata.get("priority_source") is True


@pytest.mark.anyio
async def test_scrape_with_playwright_uses_domain_for_duckduckgo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DuckDuckGo fallbacks should receive a clean domain filter."""

    page = _StubPage()
    monkeypatch.setattr(
        scraper_module, "async_playwright", lambda: _StubAsyncPlaywright(page)
    )

    sites: List[str | None] = []

    async def fake_duckduckgo(
        page_obj: _StubPage,
        destination: str,
        max_results: int = 5,
        site: str | None = None,
    ) -> List[RawOffer]:
        sites.append(site)
        domain = site or "duckduckgo.com"
        return [
            RawOffer(
                provider=domain,
                title=f"{destination} via {domain}",
                price=None,
                url=f"https://{domain}/result-{len(sites)}",
                metadata={},
            )
        ]

    monkeypatch.setattr(
        scraper_module, "_extract_duckduckgo_results", fake_duckduckgo
    )

    config = AgentConfig(
        destinations=["Mallorca"],
        preferred_sources=["https://example.com/packages?ref=newsletter"],
    )

    offers = await scraper_module._scrape_with_playwright(config)

    assert sites and sites[0] == "example.com"
    assert any(site is None for site in sites), "expected fallback search without site filter"
    assert any(offer.provider == "example.com" for offer in offers)
    assert any(offer.metadata.get("priority_source") for offer in offers)
