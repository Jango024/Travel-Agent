"""Web scraping utilities for the travel agent."""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Iterable, List, Set
from urllib.parse import quote_plus, urlparse

try:  # pragma: no cover - optional dependency during development
    from playwright.async_api import Browser, Page, async_playwright  # type: ignore
except Exception:  # pragma: no cover
    Browser = Page = None  # type: ignore
    async_playwright = None  # type: ignore

from .config import AgentConfig
from .models import RawOffer
from .sources import PORTAL_HANDLERS
from .sources.playwright_common import (
    PRICE_PATTERN,
    RECOMMENDATION_PATTERN,
    STAR_PATTERN,
    dismiss_common_banners,
)


LOGGER = logging.getLogger(__name__)


async def _dismiss_common_banners(page: Page) -> None:
    """Backward-compatible wrapper for shared banner dismissal helper."""

    await dismiss_common_banners(page)


async def _extract_duckduckgo_results(
    page: Page, destination: str, max_results: int = 5, site: str | None = None
) -> List[RawOffer]:
    """Fetch a handful of organic search results from DuckDuckGo."""

    query_string = f"pauschalreise {destination}"
    if site:
        query_string += f" site:{site}"
    query = quote_plus(query_string)
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
        price_match = PRICE_PATTERN.search(snippet)
        if price_match:
            try:
                price = float(price_match.group(1).replace(".", "").replace(",", "."))
            except ValueError:
                price = None

        star_rating = None
        star_match = STAR_PATTERN.search(snippet)
        if star_match:
            try:
                star_rating = float(star_match.group(1).replace(",", "."))
            except ValueError:
                star_rating = None

        recommendation_score = None
        recommendation_match = RECOMMENDATION_PATTERN.search(snippet)
        if recommendation_match:
            try:
                recommendation_score = float(recommendation_match.group(1))
            except ValueError:
                recommendation_score = None

        provider = site or urlparse(url).netloc or "DuckDuckGo"


        offers.append(
            RawOffer(
                provider=provider,
                title=title,
                price=price,
                url=url,
                metadata={
                    "snippet": snippet,
                    "destination": destination,
                    "source": search_url,
                    "site_filter": site,
                    "star_rating": star_rating,
                    "recommendation_score": recommendation_score,
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
    seen_urls: Set[str] = set()

    async with async_playwright() as p:  # pragma: no cover - network heavy
        browser: Browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(locale="de-DE")
        page = await context.new_page()

        for source in config.preferred_sources:
            if not source:
                continue
            normalised_source = re.sub(r"^https?://", "", source.strip().lower())
            normalised_source = normalised_source.rstrip("/")
            portal_handler = PORTAL_HANDLERS.get(normalised_source)
            for destination in destinations:
                if portal_handler is not None:
                    try:
                        portal_offers = await portal_handler(page, config, destination)
                    except Exception as exc:  # pragma: no cover - network dependent
                        LOGGER.warning(
                            "Portal scraping failed for %s@%s: %s",
                            normalised_source,
                            destination,
                            exc,
                        )
                        portal_offers = []
                    if portal_offers:
                        for offer in portal_offers:
                            if offer.url in seen_urls:
                                continue
                            offer.metadata["priority_source"] = True
                            offers.append(offer)
                            seen_urls.add(offer.url)
                        continue
                try:
                    destination_offers = await _extract_duckduckgo_results(
                        page, destination, site=normalised_source
                    )
                except Exception as exc:  # pragma: no cover - network dependent
                    LOGGER.warning(
                        "Playwright scraping failed for %s@%s: %s",
                        normalised_source,
                        destination,
                        exc,
                    )
                    continue
                for offer in destination_offers:
                    if offer.url in seen_urls:
                        continue
                    offer.metadata["priority_source"] = True
                    offers.append(offer)
                    seen_urls.add(offer.url)

        
        for destination in destinations:
            try:
                destination_offers = await _extract_duckduckgo_results(page, destination)
            except Exception as exc:  # pragma: no cover - network dependent
                LOGGER.warning("Playwright scraping failed for %s: %s", destination, exc)
                continue
            for offer in destination_offers:
                if offer.url in seen_urls:
                    continue
                offers.append(offer)
                seen_urls.add(offer.url)

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
    mocked_star_ratings = [4.0, 4.5, 3.5]
    mocked_recommendations = [88.0, 92.0, 85.0]
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
                    "star_rating": mocked_star_ratings[idx % len(mocked_star_ratings)],
                    "recommendation_score": mocked_recommendations[idx % len(mocked_recommendations)],
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
