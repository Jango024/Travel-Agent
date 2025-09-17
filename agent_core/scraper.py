"""Web scraping utilities for the travel agent."""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote_plus

try:  # pragma: no cover - optional dependency during development
    from playwright.async_api import Browser, Page, async_playwright  # type: ignore
except Exception:  # pragma: no cover
    Browser = Page = None  # type: ignore
    async_playwright = None  # type: ignore

from .config import AgentConfig


LOGGER = logging.getLogger(__name__)
_PRICE_PATTERN = re.compile(r"(\d+[\d.,]*)\s?(?:€|eur|euro|euros)?", re.IGNORECASE)


@dataclass
class RawOffer:
    """A raw travel offer as returned by a scraping backend."""

    provider: str
    title: str
    price: Optional[float]
    url: str
    metadata: Dict[str, Any]


async def _dismiss_common_banners(page: Page) -> None:
    """Attempt to dismiss cookie/consent banners that block results."""

    selectors = [
        "button:has-text('Accept')",
        "button:has-text('Zustimmen')",
        "button:has-text('Einverstanden')",
        "button:has-text('Alle akzeptieren')",
    ]
    for selector in selectors:
        try:
            await page.locator(selector).first.click(timeout=1500)
            break
        except Exception:
            continue


async def _extract_duckduckgo_results(page: Page, destination: str, max_results: int = 5) -> List[RawOffer]:
    """Fetch a handful of organic search results from DuckDuckGo."""

    query = quote_plus(f"pauschalreise {destination}")
    search_url = f"https://duckduckgo.com/?q={query}&ia=web"

    await page.goto(search_url, wait_until="networkidle")
    await _dismiss_common_banners(page)

    offers: List[RawOffer] = []

    # DuckDuckGo offers a consistent structure that we can query via data-testid attributes.
    cards = await page.query_selector_all("article[data-testid='result']")
    if not cards:
        cards = await page.query_selector_all("article.result")  # fallback for different layouts

    for card in cards:
        title_el = await card.query_selector("a[data-testid='result-title-a']")
        if title_el is None:
            title_el = await card.query_selector("a.result__a")
        if title_el is None:
            continue

        title = (await title_el.inner_text()).strip()
        url = (await title_el.get_attribute("href")) or search_url

        snippet_el = await card.query_selector("div[data-testid='result-snippet']")
        if snippet_el is None:
            snippet_el = await card.query_selector("div.result__snippet")
        snippet = (await snippet_el.inner_text()).strip() if snippet_el else ""

        price = None
        price_match = _PRICE_PATTERN.search(snippet)
        if price_match:
            try:
                price = float(price_match.group(1).replace(".", "").replace(",", "."))
            except ValueError:
                price = None

        offers.append(
            RawOffer(
                provider="DuckDuckGo",
                title=title,
                price=price,
                url=url,
                metadata={
                    "snippet": snippet,
                    "destination": destination,
                    "source": search_url,
                },
            )
        )

        if len(offers) >= max_results:
            break

    return offers


async def _scrape_with_playwright(config: AgentConfig) -> Iterable[RawOffer]:
    """Collect offers by driving a headless browser via Playwright."""

    if async_playwright is None:
        raise RuntimeError(
            "Playwright is not installed. Install playwright and run 'playwright install' to enable scraping."
        )

    destinations = config.destinations or ["Pauschalreise"]
    offers: List[RawOffer] = []

    async with async_playwright() as p:  # pragma: no cover - network heavy
        browser: Browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(locale="de-DE")
        page = await context.new_page()

        for destination in destinations:
            try:
                destination_offers = await _extract_duckduckgo_results(page, destination)
            except Exception as exc:  # pragma: no cover - network dependent
                LOGGER.warning("Playwright scraping failed for %s: %s", destination, exc)
                continue
            offers.extend(destination_offers)

        await browser.close()

    return offers


def _run_playwright_scraper(config: AgentConfig) -> List[RawOffer]:
    """Run the async Playwright scraper from synchronous code."""

    async def runner() -> Iterable[RawOffer]:
        return await _scrape_with_playwright(config)

    try:
        return list(asyncio.run(runner()))
    except RuntimeError as exc:
        if "asyncio.run() cannot be called" not in str(exc):
            raise
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return list(loop.run_until_complete(runner()))
        finally:
            asyncio.set_event_loop(None)
            loop.close()


def _fallback_mock_offers(config: AgentConfig, reason: str | None = None) -> List[RawOffer]:
    """Return deterministic offers so the pipeline keeps functioning."""

    LOGGER.debug("Falling back to mock offers: %s", reason or "no details")

    mocked_prices = [749.0, 899.0, 1020.0]
    providers = ["HolidayCheck", "TUI", "Booking.com"]
    offers: List[RawOffer] = []
    for idx, destination in enumerate(config.destinations or ["Unbekannt"]):
        price = mocked_prices[idx % len(mocked_prices)]
        offers.append(
            RawOffer(
                provider=providers[idx % len(providers)],
                title=f"Pauschalreise nach {destination}",
                price=price,
                url=f"https://example.com/offers/{destination.lower().replace(' ', '-')}",
                metadata={
                    "nights": 7,
                    "board": "Halbpension",
                    "origin": config.origin or "Beliebig",
                    "reason": reason or "mock",
                },
            )
        )
    return offers


def scrape_sources(config: AgentConfig) -> List[RawOffer]:
    """Scrape all configured sources, preferring Playwright when available."""

    if async_playwright is None:
        return _fallback_mock_offers(config, reason="playwright-missing")

    try:
        offers = _run_playwright_scraper(config)
    except Exception as exc:  # pragma: no cover - depends on network/Playwright
        LOGGER.error("Playwright scraping failed, falling back to mock offers: %s", exc)
        offers = []

    if not offers:
        return _fallback_mock_offers(config, reason="playwright-empty")
    return offers
