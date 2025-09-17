"""Web scraping utilities for the travel agent."""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set
from urllib.parse import quote_plus, urljoin, urlparse

try:  # pragma: no cover - optional dependency during development
    from playwright.async_api import Browser, Page, async_playwright  # type: ignore
except Exception:  # pragma: no cover
    Browser = Page = None  # type: ignore
    async_playwright = None  # type: ignore

from .config import AgentConfig


LOGGER = logging.getLogger(__name__)
_PRICE_PATTERN = re.compile(r"(\d+[\d.,]*)\s?(?:€|eur|euro|euros)?", re.IGNORECASE)
_STAR_PATTERN = re.compile(r"(\d(?:[.,]\d)?)\s*(?:sterne|stars)", re.IGNORECASE)
_RECOMMENDATION_PATTERN = re.compile(
    r"(\d{1,3})\s?%[^%]*(?:weiterempfehlung|recommended|bewertung)", re.IGNORECASE
)

@dataclass
class RawOffer:
    """A raw travel offer as returned by a scraping backend."""

    provider: str
    title: str
    price: Optional[float]
    url: str
    metadata: Dict[str, Any]


def _parse_price_from_text(text: str) -> Optional[float]:
    """Extract a numeric price from loosely formatted strings."""

    match = _PRICE_PATTERN.search(text)
    if not match:
        return None
    try:
        normalised = match.group(1).replace(".", "").replace(",", ".")
        return float(normalised)
    except ValueError:
        return None


async def _try_fill_field(page: Page, selectors: Iterable[str], value: str) -> None:
    """Attempt to fill the first matching selector with the provided value."""

    if not value:
        return
    for selector in selectors:
        try:
            await page.fill(selector, value)
            return
        except Exception:
            try:
                locator = page.locator(selector)
            except Exception:
                locator = None
            if locator is None:
                continue
            try:
                await locator.fill(value)
                return
            except Exception:
                continue


async def _try_select_option(page: Page, selectors: Iterable[str], value: str) -> None:
    """Attempt to select an option on the first working selector."""

    if not value:
        return
    for selector in selectors:
        try:
            await page.select_option(selector, value)
            return
        except Exception:
            continue


async def _extract_text(handle: Any, selectors: Iterable[str]) -> Optional[str]:
    """Return the first non-empty text found using the provided selectors."""

    for selector in selectors:
        try:
            element = await handle.query_selector(selector)
        except Exception:
            continue
        if element is None:
            continue
        try:
            text = await element.inner_text()
        except Exception:
            try:
                text = await element.text_content()
            except Exception:
                text = None
        if text:
            stripped = text.strip()
            if stripped:
                return stripped
    return None


async def _extract_attribute(
    handle: Any, selectors: Iterable[str], attribute: str
) -> Optional[str]:
    """Return the first non-empty attribute value for the selectors provided."""

    for selector in selectors:
        try:
            element = await handle.query_selector(selector)
        except Exception:
            continue
        if element is None:
            continue
        try:
            value = await element.get_attribute(attribute)
        except Exception:
            value = None
        if value:
            return value
    return None


def _build_portal_metadata(
    config: AgentConfig, destination: str, source: str
) -> Dict[str, Any]:
    """Generate metadata shared across portal scrapers."""

    metadata: Dict[str, Any] = {
        "destination": destination,
        "source": source,
    }
    if config.travellers:
        metadata["travellers"] = config.travellers
    if config.departure_date:
        metadata["departure_date"] = config.departure_date.isoformat()
    if config.return_date:
        metadata["return_date"] = config.return_date.isoformat()
    if config.budget is not None:
        metadata["budget"] = config.budget
    return metadata


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
        price_match = _PRICE_PATTERN.search(snippet)
        if price_match:
            try:
                price = float(price_match.group(1).replace(".", "").replace(",", "."))
            except ValueError:
                price = None

        star_rating = None
        star_match = _STAR_PATTERN.search(snippet)
        if star_match:
            try:
                star_rating = float(star_match.group(1).replace(",", "."))
            except ValueError:
                star_rating = None

        recommendation_score = None
        recommendation_match = _RECOMMENDATION_PATTERN.search(snippet)
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


async def _collect_cards(page: Page, selectors: Iterable[str]) -> List[Any]:
    """Return result cards by iterating through fallback selectors."""

    for selector in selectors:
        try:
            cards = await page.query_selector_all(selector)
        except Exception:
            continue
        if cards:
            return cards
    return []


async def _search_holidaycheck(
    page: Page, config: AgentConfig, destination: str
) -> List[RawOffer]:
    """Scrape travel offers from holidaycheck.de."""

    base_url = "https://www.holidaycheck.de"
    search_url = f"{base_url}/suche"

    await page.goto(search_url, wait_until="networkidle")
    await _dismiss_common_banners(page)

    await _try_fill_field(page, ["input[name='destination']"], destination)
    await _try_select_option(page, ["select[name='travellers']"], str(config.travellers or ""))
    if config.departure_date:
        await _try_fill_field(
            page, ["input[name='departure']", "input[name='from']"], config.departure_date.isoformat()
        )
    if config.return_date:
        await _try_fill_field(
            page, ["input[name='return']", "input[name='to']"], config.return_date.isoformat()
        )
    if config.budget is not None:
        await _try_fill_field(
            page,
            ["input[name='budget']", "input[name='price']"],
            str(int(config.budget)),
        )

    try:
        await page.click("button[type='submit']")
    except Exception:
        pass
    try:
        await page.wait_for_load_state("networkidle")
    except Exception:
        pass

    cards = await _collect_cards(
        page,
        [
            "[data-testid='offer-card']",
            "article[data-testid='hc-result-card']",
            "article[data-testid='offer-card']",
            "article",
        ],
    )

    offers: List[RawOffer] = []
    base_metadata = _build_portal_metadata(config, destination, search_url)

    for card in cards:
        title = await _extract_text(
            card,
            [
                "[data-testid='offer-title']",
                "[data-testid='result-title']",
                ".offer-title",
                "header h3",
            ],
        )
        href = await _extract_attribute(
            card,
            [
                "a[data-testid='offer-link']",
                "a[data-testid='result-link']",
                "a[href]",
            ],
            "href",
        )
        if not title or not href:
            continue

        price_text = await _extract_text(
            card,
            [
                "[data-testid='offer-price']",
                "[data-testid='result-price']",
                ".offer-price",
                ".price",
            ],
        )
        price = _parse_price_from_text(price_text or "")

        metadata = base_metadata.copy()
        board = await _extract_text(
            card,
            [
                "[data-testid='offer-board']",
                "[data-testid='result-board']",
                ".board",
            ],
        )
        if board:
            metadata["board"] = board

        duration = await _extract_text(
            card,
            [
                "[data-testid='offer-duration']",
                "[data-testid='result-duration']",
                ".duration",
            ],
        )
        if duration:
            metadata["duration"] = duration

        rating_text = await _extract_text(
            card,
            [
                "[data-testid='offer-rating']",
                "[data-testid='result-rating']",
                ".rating",
            ],
        )
        if rating_text:
            match = _RECOMMENDATION_PATTERN.search(rating_text)
            if match:
                try:
                    metadata["recommendation_score"] = float(match.group(1))
                except ValueError:
                    pass

        offers.append(
            RawOffer(
                provider="holidaycheck.de",
                title=title,
                price=price,
                url=urljoin(base_url, href),
                metadata=metadata,
            )
        )

    return offers


async def _search_tui(page: Page, config: AgentConfig, destination: str) -> List[RawOffer]:
    """Scrape travel offers from tui.com."""

    base_url = "https://www.tui.com"
    search_url = f"{base_url}/suche"

    await page.goto(search_url, wait_until="networkidle")
    await _dismiss_common_banners(page)

    await _try_fill_field(page, ["input[name='q']", "input[name='destination']"], destination)
    await _try_select_option(page, ["select[name='travellers']"], str(config.travellers or ""))
    if config.departure_date:
        await _try_fill_field(
            page,
            ["input[name='departure']", "input[name='from']"],
            config.departure_date.isoformat(),
        )
    if config.return_date:
        await _try_fill_field(
            page, ["input[name='return']", "input[name='to']"], config.return_date.isoformat()
        )
    if config.budget is not None:
        await _try_fill_field(
            page,
            ["input[name='maxPrice']", "input[name='budget']"],
            str(int(config.budget)),
        )

    try:
        await page.click("button[type='submit']")
    except Exception:
        pass
    try:
        await page.wait_for_load_state("networkidle")
    except Exception:
        pass

    cards = await _collect_cards(
        page,
        [
            "[data-testid='result-card']",
            "article[data-testid='offer-card']",
            "article",
        ],
    )

    offers: List[RawOffer] = []
    base_metadata = _build_portal_metadata(config, destination, search_url)

    for card in cards:
        title = await _extract_text(
            card,
            [
                "[data-testid='result-title']",
                "[data-testid='offer-title']",
                ".offer-title",
                "header h3",
            ],
        )
        href = await _extract_attribute(
            card,
            [
                "a[data-testid='result-link']",
                "a[data-testid='offer-link']",
                "a[href]",
            ],
            "href",
        )
        if not title or not href:
            continue

        price_text = await _extract_text(
            card,
            [
                "[data-testid='result-price']",
                "[data-testid='offer-price']",
                ".offer-price",
                ".price",
            ],
        )
        price = _parse_price_from_text(price_text or "")

        metadata = base_metadata.copy()
        board = await _extract_text(
            card,
            [
                "[data-testid='result-board']",
                "[data-testid='offer-board']",
                ".board",
            ],
        )
        if board:
            metadata["board"] = board

        duration = await _extract_text(
            card,
            [
                "[data-testid='result-duration']",
                "[data-testid='offer-duration']",
                ".duration",
            ],
        )
        if duration:
            metadata["duration"] = duration

        offers.append(
            RawOffer(
                provider="tui.com",
                title=title,
                price=price,
                url=urljoin(base_url, href),
                metadata=metadata,
            )
        )

    return offers


async def _search_abindenurlaub(
    page: Page, config: AgentConfig, destination: str
) -> List[RawOffer]:
    """Scrape travel offers from ab-in-den-urlaub.de."""

    base_url = "https://www.ab-in-den-urlaub.de"
    search_url = f"{base_url}/suche"

    await page.goto(search_url, wait_until="networkidle")
    await _dismiss_common_banners(page)

    await _try_fill_field(page, ["input[name='destination']"], destination)
    await _try_select_option(page, ["select[name='travellers']"], str(config.travellers or ""))
    if config.departure_date:
        await _try_fill_field(
            page,
            ["input[name='departure']", "input[name='from']"],
            config.departure_date.isoformat(),
        )
    if config.return_date:
        await _try_fill_field(
            page, ["input[name='return']", "input[name='to']"], config.return_date.isoformat()
        )
    if config.budget is not None:
        await _try_fill_field(
            page,
            ["input[name='budget']", "input[name='price']"],
            str(int(config.budget)),
        )

    try:
        await page.click("button[type='submit']")
    except Exception:
        pass
    try:
        await page.wait_for_load_state("networkidle")
    except Exception:
        pass

    cards = await _collect_cards(
        page,
        [
            "article[data-testid='offer-card']",
            "[data-testid='offer-card']",
            "article",
        ],
    )

    offers: List[RawOffer] = []
    base_metadata = _build_portal_metadata(config, destination, search_url)

    for card in cards:
        title = await _extract_text(
            card,
            [
                "[data-testid='offer-title']",
                "[data-testid='result-title']",
                ".offer-title",
                "header h3",
            ],
        )
        href = await _extract_attribute(
            card,
            [
                "a[data-testid='offer-link']",
                "a[data-testid='result-link']",
                "a[href]",
            ],
            "href",
        )
        if not title or not href:
            continue

        price_text = await _extract_text(
            card,
            [
                "[data-testid='offer-price']",
                "[data-testid='result-price']",
                ".offer-price",
                ".price",
            ],
        )
        price = _parse_price_from_text(price_text or "")

        metadata = base_metadata.copy()
        board = await _extract_text(
            card,
            [
                "[data-testid='offer-board']",
                "[data-testid='result-board']",
                ".board",
            ],
        )
        if board:
            metadata["board"] = board

        duration = await _extract_text(
            card,
            [
                "[data-testid='offer-duration']",
                "[data-testid='result-duration']",
                ".duration",
            ],
        )
        if duration:
            metadata["duration"] = duration

        rating_text = await _extract_text(
            card,
            [
                "[data-testid='offer-rating']",
                "[data-testid='result-rating']",
                ".rating",
            ],
        )
        if rating_text:
            match = _RECOMMENDATION_PATTERN.search(rating_text)
            if match:
                try:
                    metadata["recommendation_score"] = float(match.group(1))
                except ValueError:
                    pass

        offers.append(
            RawOffer(
                provider="ab-in-den-urlaub.de",
                title=title,
                price=price,
                url=urljoin(base_url, href),
                metadata=metadata,
            )
        )

    return offers


async def _search_weg(page: Page, config: AgentConfig, destination: str) -> List[RawOffer]:
    """Scrape travel offers from weg.de."""

    base_url = "https://www.weg.de"
    search_url = f"{base_url}/suche"

    await page.goto(search_url, wait_until="networkidle")
    await _dismiss_common_banners(page)

    await _try_fill_field(page, ["input[name='destination']"], destination)
    await _try_select_option(page, ["select[name='travellers']"], str(config.travellers or ""))
    if config.departure_date:
        await _try_fill_field(
            page,
            ["input[name='departure']", "input[name='from']"],
            config.departure_date.isoformat(),
        )
    if config.return_date:
        await _try_fill_field(
            page, ["input[name='return']", "input[name='to']"], config.return_date.isoformat()
        )
    if config.budget is not None:
        await _try_fill_field(
            page,
            ["input[name='budget']", "input[name='price']"],
            str(int(config.budget)),
        )

    try:
        await page.click("button[type='submit']")
    except Exception:
        pass
    try:
        await page.wait_for_load_state("networkidle")
    except Exception:
        pass

    cards = await _collect_cards(
        page,
        [
            "[data-testid='result-card']",
            "article[data-testid='offer-card']",
            "article",
        ],
    )

    offers: List[RawOffer] = []
    base_metadata = _build_portal_metadata(config, destination, search_url)

    for card in cards:
        title = await _extract_text(
            card,
            [
                "[data-testid='result-title']",
                "[data-testid='offer-title']",
                ".offer-title",
                "header h3",
            ],
        )
        href = await _extract_attribute(
            card,
            [
                "a[data-testid='result-link']",
                "a[data-testid='offer-link']",
                "a[href]",
            ],
            "href",
        )
        if not title or not href:
            continue

        price_text = await _extract_text(
            card,
            [
                "[data-testid='result-price']",
                "[data-testid='offer-price']",
                ".offer-price",
                ".price",
            ],
        )
        price = _parse_price_from_text(price_text or "")

        metadata = base_metadata.copy()
        board = await _extract_text(
            card,
            [
                "[data-testid='result-board']",
                "[data-testid='offer-board']",
                ".board",
            ],
        )
        if board:
            metadata["board"] = board

        duration = await _extract_text(
            card,
            [
                "[data-testid='result-duration']",
                "[data-testid='offer-duration']",
                ".duration",
            ],
        )
        if duration:
            metadata["duration"] = duration

        offers.append(
            RawOffer(
                provider="weg.de",
                title=title,
                price=price,
                url=urljoin(base_url, href),
                metadata=metadata,
            )
        )

    return offers


_PORTAL_HANDLERS = {
    "holidaycheck.de": _search_holidaycheck,
    "www.holidaycheck.de": _search_holidaycheck,
    "tui.com": _search_tui,
    "www.tui.com": _search_tui,
    "ab-in-den-urlaub.de": _search_abindenurlaub,
    "www.ab-in-den-urlaub.de": _search_abindenurlaub,
    "weg.de": _search_weg,
    "www.weg.de": _search_weg,
}


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
            portal_handler = _PORTAL_HANDLERS.get(normalised_source)
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
                        "Playwright scraping failed for %s@%s: %s", normalised_source, destination, exc
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
