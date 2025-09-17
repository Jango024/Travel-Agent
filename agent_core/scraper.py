"""Web scraping utilities for the travel agent."""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Set
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
_NIGHTS_PATTERN = re.compile(
    r"(\d+)\s*(?:nächte?|nacht|naechte?|tage?|tag|days?|day)", re.IGNORECASE
)


def _parse_price_from_text(text: str) -> Optional[float]:
    """Extract a float price from a loosely formatted string."""

    match = _PRICE_PATTERN.search(text)
    if not match:
        return None
    try:
        numeric = match.group(1).replace(".", "").replace(",", ".")
        return float(numeric)
    except ValueError:
        return None


def _parse_nights_from_text(text: str) -> Optional[int]:
    """Extract the number of nights from a duration string."""

    if not text:
        return None

    match = _NIGHTS_PATTERN.search(text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


async def _try_fill_field(page: Page, selectors: Iterable[str], value: str) -> None:
    """Attempt to fill the first selector that works on the current page."""

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


async def _try_select_option(page: Page, selectors: Iterable[str], value: str) -> bool:
    """Attempt to select an option; return True on success."""

    if not value:
        return False
    for selector in selectors:
        try:
            await page.select_option(selector, value)
            return True
        except Exception:
            continue
    return False


async def _extract_text(handle: Any, selectors: Iterable[str]) -> Optional[str]:
    """Return the first non-empty text for the given selectors."""

    for selector in selectors:
        try:
            element = await handle.query_selector(selector)
        except Exception:
            continue
        if element is None:
            continue
        text: Optional[str] = None
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
    """Fetch an attribute from the first matching selector."""

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

        price = _parse_price_from_text(snippet)

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


async def _search_holidaycheck(
    page: Page, config: AgentConfig, destination: str, max_results: int = 5
) -> List[RawOffer]:
    """Search holidaycheck.de directly and extract structured offers."""

    base_url = "https://www.holidaycheck.de/"

    await page.goto(base_url, wait_until="domcontentloaded")
    await _dismiss_common_banners(page)

    await _try_fill_field(
        page,
        [
            "input[name='destination']",
            "input[data-testid='destination-input']",
            "input[aria-label='Reiseziel']",
        ],
        destination,
    )

    if config.departure_date:
        await _try_fill_field(
            page,
            [
                "input[name='departureDate']",
                "input[data-testid='date-range-start']",
                "input[name='startDate']",
            ],
            config.departure_date.isoformat(),
        )
    if config.return_date:
        await _try_fill_field(
            page,
            [
                "input[name='returnDate']",
                "input[data-testid='date-range-end']",
                "input[name='endDate']",
            ],
            config.return_date.isoformat(),
        )

    travellers_value = str(config.travellers or 2)
    if not await _try_select_option(
        page,
        [
            "select[name='travellers']",
            "select[name='guests']",
            "select[data-testid='guest-select']",
        ],
        travellers_value,
    ):
        await _try_fill_field(
            page,
            ["input[name='travellers']", "input[name='guests']"],
            travellers_value,
        )

    if config.budget is not None:
        await _try_fill_field(
            page,
            ["input[name='budget']", "input[data-testid='price-budget']"],
            f"{int(config.budget)}",
        )

    for selector in [
        "button[type='submit']",
        "button[data-testid='search-button']",
        "button:has-text('Angebote anzeigen')",
    ]:
        try:
            await page.click(selector)
            break
        except Exception:
            continue

    try:
        await page.wait_for_load_state("networkidle")
    except Exception:
        pass
    await _dismiss_common_banners(page)

    cards = await page.query_selector_all("[data-testid='offer-card']")
    if not cards:
        cards = await page.query_selector_all("article[data-testid='hc-result-card']")
    if not cards:
        cards = await page.query_selector_all("article")

    offers: List[RawOffer] = []
    for card in cards:
        title = await _extract_text(
            card,
            [
                "[data-testid='offer-title']",
                ".offer-title",
                ".hotel-name",
                "header h3",
            ],
        )
        if not title:
            continue

        href = await _extract_attribute(card, ["a[data-testid='offer-link']", "a[href]"], "href")
        url = urljoin(base_url, href) if href else base_url

        price_text = await _extract_text(
            card,
            [
                "[data-testid='offer-price']",
                ".offer-price",
                ".price",
                "[data-testid='offer-card'] [data-testid='price']",
            ],
        )
        price = _parse_price_from_text(price_text) if price_text else None

        board = await _extract_text(
            card,
            [
                "[data-testid='offer-board']",
                ".board",
                "[data-testid='catering']",
            ],
        )
        duration = await _extract_text(
            card,
            [
                "[data-testid='offer-duration']",
                ".duration",
                "[data-testid='stay-length']",
            ],
        )
        nights = _parse_nights_from_text(duration) if duration else None
        rating_text = await _extract_text(
            card,
            [
                "[data-testid='offer-rating']",
                ".rating",
                "[data-testid='recommendation']",
            ],
        )

        metadata: Dict[str, Any] = {
            "destination": destination,
            "source": "holidaycheck.de",
            "travellers": config.travellers,
        }
        if config.departure_date:
            metadata["departure_date"] = config.departure_date.isoformat()
        if config.return_date:
            metadata["return_date"] = config.return_date.isoformat()
        if config.budget is not None:
            metadata["budget"] = config.budget
        if board:
            metadata["board"] = board
        if duration:
            metadata["duration"] = duration
        if nights is not None:
            metadata["nights"] = nights

        if rating_text:
            star_match = _STAR_PATTERN.search(rating_text)
            if star_match:
                try:
                    metadata["star_rating"] = float(
                        star_match.group(1).replace(",", ".")
                    )
                except ValueError:
                    pass
            recommendation_match = _RECOMMENDATION_PATTERN.search(rating_text)
            if recommendation_match:
                try:
                    metadata["recommendation_score"] = float(
                        recommendation_match.group(1)
                    )
                except ValueError:
                    pass

        offers.append(
            RawOffer(
                provider="holidaycheck.de",
                title=title,
                price=price,
                url=url,
                metadata=metadata,
            )
        )
        if len(offers) >= max_results:
            break

    return offers


async def _search_tui(
    page: Page, config: AgentConfig, destination: str, max_results: int = 5
) -> List[RawOffer]:
    """Search tui.com for a given destination."""

    base_url = "https://www.tui.com/"
    search_url = urljoin(base_url, "pauschalreisen/")

    await page.goto(search_url, wait_until="domcontentloaded")
    await _dismiss_common_banners(page)

    await _try_fill_field(
        page,
        [
            "input[name='q']",
            "input[data-testid='search-input']",
            "input[placeholder*='Wohin']",
        ],
        destination,
    )

    if config.departure_date:
        await _try_fill_field(
            page,
            ["input[name='departureDate']", "input[data-testid='date-departure']"],
            config.departure_date.isoformat(),
        )
    if config.return_date:
        await _try_fill_field(
            page,
            ["input[name='returnDate']", "input[data-testid='date-return']"],
            config.return_date.isoformat(),
        )

    travellers_value = str(config.travellers or 2)
    if not await _try_select_option(
        page,
        ["select[name='travellers']", "select[data-testid='travellers-select']"],
        travellers_value,
    ):
        await _try_fill_field(page, ["input[name='travellers']"], travellers_value)

    if config.budget is not None:
        await _try_fill_field(
            page,
            ["input[name='maxPrice']", "input[data-testid='price-to']"],
            f"{int(config.budget)}",
        )

    for selector in [
        "button[type='submit']",
        "button[data-testid='search-button']",
        "button:has-text('Angebote finden')",
    ]:
        try:
            await page.click(selector)
            break
        except Exception:
            continue

    try:
        await page.wait_for_load_state("networkidle")
    except Exception:
        pass
    await _dismiss_common_banners(page)

    cards = await page.query_selector_all("[data-testid='offer-card']")
    if not cards:
        cards = await page.query_selector_all("article[data-testid='result-card']")
    if not cards:
        cards = await page.query_selector_all("article")

    offers: List[RawOffer] = []
    for card in cards:
        title = await _extract_text(
            card,
            [
                "[data-testid='offer-title']",
                ".offer-title",
                ".product-tile__title",
                "header h3",
            ],
        )
        if not title:
            continue

        href = await _extract_attribute(
            card,
            ["a[data-testid='offer-link']", "a[href]"],
            "href",
        )
        url = urljoin(base_url, href) if href else base_url

        price_text = await _extract_text(
            card,
            [
                "[data-testid='offer-price']",
                ".offer-price",
                ".price",
                "[data-testid='product-price']",
            ],
        )
        price = _parse_price_from_text(price_text) if price_text else None

        board = await _extract_text(
            card,
            ["[data-testid='offer-board']", ".board", "[data-testid='product-board']"],
        )
        duration = await _extract_text(
            card,
            [
                "[data-testid='offer-duration']",
                ".duration",
                "[data-testid='product-duration']",
            ],
        )
        nights = _parse_nights_from_text(duration) if duration else None

        metadata: Dict[str, Any] = {
            "destination": destination,
            "source": "tui.com",
            "travellers": config.travellers,
        }
        if config.departure_date:
            metadata["departure_date"] = config.departure_date.isoformat()
        if config.return_date:
            metadata["return_date"] = config.return_date.isoformat()
        if config.budget is not None:
            metadata["budget"] = config.budget
        if board:
            metadata["board"] = board
        if duration:
            metadata["duration"] = duration
        if nights is not None:
            metadata["nights"] = nights

        offers.append(
            RawOffer(
                provider="tui.com",
                title=title,
                price=price,
                url=url,
                metadata=metadata,
            )
        )
        if len(offers) >= max_results:
            break

    return offers


_PORTAL_SEARCH_HANDLERS: Dict[
    str, Callable[[Page, AgentConfig, str], Awaitable[List[RawOffer]]]
] = {
    "holidaycheck.de": _search_holidaycheck,
    "www.holidaycheck.de": _search_holidaycheck,
    "tui.com": _search_tui,
    "www.tui.com": _search_tui,
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
            handler = _PORTAL_SEARCH_HANDLERS.get(normalised_source)
            for destination in destinations:
                try:
                    if handler is not None:
                        destination_offers = await handler(page, config, destination)
                    else:
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
