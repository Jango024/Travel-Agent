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


def _build_portal_metadata(
    config: AgentConfig, destination: str, source: str
) -> Dict[str, Any]:
    """Create a metadata dictionary shared by portal scrapers."""

    metadata: Dict[str, Any] = {
        "destination": destination,
        "source": source,
        "travellers": config.travellers,
    }
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


@dataclass(frozen=True)
class _PortalConfig:
    """Describe how to interact with and parse a travel portal."""

    provider: str
    base_url: str
    search_path: str
    destination_fields: tuple[str, ...]
    departure_fields: tuple[str, ...] = ()
    return_fields: tuple[str, ...] = ()
    travellers_selects: tuple[str, ...] = ()
    travellers_inputs: tuple[str, ...] = ()
    budget_fields: tuple[str, ...] = ()
    submit_buttons: tuple[str, ...] = ("button[type='submit']",)
    card_selectors: tuple[str, ...] = ("article",)
    title_selectors: tuple[str, ...] = ()
    link_selectors: tuple[str, ...] = ("a[href]",)
    price_selectors: tuple[str, ...] = ()
    board_selectors: tuple[str, ...] = ()
    duration_selectors: tuple[str, ...] = ()
    rating_selectors: tuple[str, ...] = ()


async def _search_portal(
    page: Page,
    config: AgentConfig,
    destination: str,
    portal: _PortalConfig,
    *,
    max_results: int = 5,
) -> List[RawOffer]:
    """Drive a portal search form and transform result cards into offers."""

    search_url = urljoin(portal.base_url, portal.search_path)

    await page.goto(search_url, wait_until="domcontentloaded")
    await _dismiss_common_banners(page)

    await _try_fill_field(page, portal.destination_fields, destination)

    if config.departure_date and portal.departure_fields:
        await _try_fill_field(
            page, portal.departure_fields, config.departure_date.isoformat()
        )
    if config.return_date and portal.return_fields:
        await _try_fill_field(
            page, portal.return_fields, config.return_date.isoformat()
        )

    travellers_value = str(config.travellers or 2)
    if portal.travellers_selects and await _try_select_option(
        page, portal.travellers_selects, travellers_value
    ):
        pass
    elif portal.travellers_inputs:
        await _try_fill_field(page, portal.travellers_inputs, travellers_value)

    if config.budget is not None and portal.budget_fields:
        await _try_fill_field(
            page, portal.budget_fields, f"{int(config.budget)}"
        )

    for selector in portal.submit_buttons:
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

    cards: list[Any] = []
    for selector in portal.card_selectors:
        cards = await page.query_selector_all(selector)
        if cards:
            break

    offers: List[RawOffer] = []
    for card in cards:
        title = await _extract_text(card, portal.title_selectors)
        if not title:
            continue

        href = await _extract_attribute(card, portal.link_selectors, "href")
        url = urljoin(portal.base_url, href) if href else portal.base_url

        price = None
        if portal.price_selectors:
            price_text = await _extract_text(card, portal.price_selectors)
            if price_text:
                price = _parse_price_from_text(price_text)

        metadata = _build_portal_metadata(config, destination, portal.provider)

        if portal.board_selectors:
            board = await _extract_text(card, portal.board_selectors)
            if board:
                metadata["board"] = board

        if portal.duration_selectors:
            duration = await _extract_text(card, portal.duration_selectors)
            if duration:
                metadata["duration"] = duration

        if portal.rating_selectors:
            rating_text = await _extract_text(card, portal.rating_selectors)
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
                provider=portal.provider,
                title=title,
                price=price,
                url=url,
                metadata=metadata,
            )
        )
        if len(offers) >= max_results:
            break

    return offers


_HOLIDAYCHECK_CONFIG = _PortalConfig(
    provider="holidaycheck.de",
    base_url="https://www.holidaycheck.de/",
    search_path="",
    destination_fields=(
        "input[name='destination']",
        "input[data-testid='destination-input']",
        "input[aria-label='Reiseziel']",
    ),
    departure_fields=(
        "input[name='departureDate']",
        "input[data-testid='date-range-start']",
        "input[name='startDate']",
    ),
    return_fields=(
        "input[name='returnDate']",
        "input[data-testid='date-range-end']",
        "input[name='endDate']",
    ),
    travellers_selects=(
        "select[name='travellers']",
        "select[name='guests']",
        "select[data-testid='guest-select']",
    ),
    travellers_inputs=("input[name='travellers']", "input[name='guests']"),
    budget_fields=(
        "input[name='budget']",
        "input[data-testid='price-budget']",
    ),
    submit_buttons=(
        "button[type='submit']",
        "button[data-testid='search-button']",
        "button:has-text('Angebote anzeigen')",
    ),
    card_selectors=(
        "[data-testid='offer-card']",
        "article[data-testid='hc-result-card']",
        "article",
    ),
    title_selectors=(
        "[data-testid='offer-title']",
        ".offer-title",
        ".hotel-name",
        "header h3",
    ),
    link_selectors=("a[data-testid='offer-link']", "a[href]"),
    price_selectors=(
        "[data-testid='offer-price']",
        ".offer-price",
        ".price",
        "[data-testid='offer-card'] [data-testid='price']",
    ),
    board_selectors=(
        "[data-testid='offer-board']",
        ".board",
        "[data-testid='catering']",
    ),
    duration_selectors=(
        "[data-testid='offer-duration']",
        ".duration",
        "[data-testid='stay-length']",
    ),
    rating_selectors=(
        "[data-testid='offer-rating']",
        ".rating",
        "[data-testid='recommendation']",
    ),
)


_TUI_CONFIG = _PortalConfig(
    provider="tui.com",
    base_url="https://www.tui.com/",
    search_path="pauschalreisen/",
    destination_fields=(
        "input[name='q']",
        "input[data-testid='search-input']",
        "input[placeholder*='Wohin']",
    ),
    departure_fields=(
        "input[name='departureDate']",
        "input[data-testid='date-departure']",
    ),
    return_fields=(
        "input[name='returnDate']",
        "input[data-testid='date-return']",
    ),
    travellers_selects=(
        "select[name='travellers']",
        "select[data-testid='travellers-select']",
    ),
    travellers_inputs=("input[name='travellers']",),
    budget_fields=(
        "input[name='maxPrice']",
        "input[data-testid='price-to']",
    ),
    submit_buttons=(
        "button[type='submit']",
        "button[data-testid='search-button']",
        "button:has-text('Angebote finden')",
    ),
    card_selectors=(
        "[data-testid='offer-card']",
        "article[data-testid='result-card']",
        "article",
    ),
    title_selectors=(
        "[data-testid='offer-title']",
        ".offer-title",
        ".product-tile__title",
        "header h3",
    ),
    link_selectors=("a[data-testid='offer-link']", "a[href]"),
    price_selectors=(
        "[data-testid='offer-price']",
        ".offer-price",
        ".price",
        "[data-testid='product-price']",
    ),
    board_selectors=(
        "[data-testid='offer-board']",
        ".board",
        "[data-testid='product-board']",
    ),
    duration_selectors=(
        "[data-testid='offer-duration']",
        ".duration",
        "[data-testid='product-duration']",
    ),
)


_AB_IN_DEN_URLAUB_CONFIG = _PortalConfig(
    provider="ab-in-den-urlaub.de",
    base_url="https://www.ab-in-den-urlaub.de/",
    search_path="suche",
    destination_fields=(
        "input[name='destination']",
        "input[name='q']",
        "input[data-testid='destination-input']",
        "input[placeholder*='Wohin']",
    ),
    departure_fields=(
        "input[name='departureDate']",
        "input[name='hinreise']",
        "input[data-testid='departure-date']",
    ),
    return_fields=(
        "input[name='returnDate']",
        "input[name='rueckreise']",
        "input[data-testid='return-date']",
    ),
    travellers_selects=(
        "select[name='travellers']",
        "select[name='adults']",
        "select[data-testid='guests-select']",
    ),
    travellers_inputs=("input[name='travellers']", "input[name='adults']"),
    budget_fields=(
        "input[name='budget']",
        "input[name='maxPrice']",
        "input[data-testid='price-to']",
    ),
    submit_buttons=(
        "button[type='submit']",
        "button[data-testid='search-button']",
        "button:has-text('Angebote suchen')",
    ),
    card_selectors=(
        "[data-testid='result-card']",
        "article[data-testid='offer-card']",
        "article",
    ),
    title_selectors=(
        "[data-testid='result-title']",
        "[data-testid='offer-title']",
        ".result-card__title",
        "header h3",
    ),
    link_selectors=(
        "a[data-testid='offer-link']",
        "a[data-testid='result-link']",
        "a[href]",
    ),
    price_selectors=(
        "[data-testid='result-price']",
        "[data-testid='offer-price']",
        ".offer-price",
        ".price",
    ),
    board_selectors=(
        "[data-testid='result-board']",
        "[data-testid='offer-board']",
        ".board",
        "[data-testid='catering']",
    ),
    duration_selectors=(
        "[data-testid='result-duration']",
        "[data-testid='offer-duration']",
        ".duration",
        "[data-testid='stay-length']",
    ),
    rating_selectors=(
        "[data-testid='result-rating']",
        "[data-testid='offer-rating']",
        ".rating",
        "[data-testid='recommendation']",
    ),
)


_WEG_CONFIG = _PortalConfig(
    provider="weg.de",
    base_url="https://www.weg.de/",
    search_path="urlaubsreisen",
    destination_fields=(
        "input[name='destination']",
        "input[name='q']",
        "input[data-testid='destination-input']",
        "input[placeholder*='Wohin']",
    ),
    departure_fields=(
        "input[name='departureDate']",
        "input[name='hinreise']",
        "input[data-testid='departure-date']",
    ),
    return_fields=(
        "input[name='returnDate']",
        "input[name='rueckreise']",
        "input[data-testid='return-date']",
    ),
    travellers_selects=(
        "select[name='travellers']",
        "select[name='adults']",
        "select[data-testid='guests-select']",
    ),
    travellers_inputs=("input[name='travellers']", "input[name='adults']"),
    budget_fields=(
        "input[name='budget']",
        "input[name='maxPrice']",
        "input[data-testid='price-to']",
    ),
    submit_buttons=(
        "button[type='submit']",
        "button[data-testid='search-button']",
        "button:has-text('Angebote finden')",
    ),
    card_selectors=(
        "[data-testid='result-card']",
        "article[data-testid='offer-card']",
        "article",
    ),
    title_selectors=(
        "[data-testid='result-title']",
        "[data-testid='offer-title']",
        ".offer-title",
        "header h3",
    ),
    link_selectors=(
        "a[data-testid='offer-link']",
        "a[data-testid='result-link']",
        "a[href]",
    ),
    price_selectors=(
        "[data-testid='result-price']",
        "[data-testid='offer-price']",
        ".offer-price",
        ".price",
    ),
    board_selectors=(
        "[data-testid='result-board']",
        "[data-testid='offer-board']",
        ".board",
        "[data-testid='product-board']",
    ),
    duration_selectors=(
        "[data-testid='result-duration']",
        "[data-testid='offer-duration']",
        ".duration",
        "[data-testid='product-duration']",
    ),
    rating_selectors=(
        "[data-testid='result-rating']",
        "[data-testid='offer-rating']",
        ".rating",
        "[data-testid='recommendation']",
    ),
)


async def _search_holidaycheck(
    page: Page, config: AgentConfig, destination: str, max_results: int = 5
) -> List[RawOffer]:
    return await _search_portal(
        page, config, destination, _HOLIDAYCHECK_CONFIG, max_results=max_results
    )


async def _search_tui(
    page: Page, config: AgentConfig, destination: str, max_results: int = 5
) -> List[RawOffer]:
    return await _search_portal(
        page, config, destination, _TUI_CONFIG, max_results=max_results
    )


async def _search_abindenurlaub(
    page: Page, config: AgentConfig, destination: str, max_results: int = 5
) -> List[RawOffer]:
    return await _search_portal(
        page, config, destination, _AB_IN_DEN_URLAUB_CONFIG, max_results=max_results
    )


async def _search_weg(
    page: Page, config: AgentConfig, destination: str, max_results: int = 5
) -> List[RawOffer]:
    return await _search_portal(
        page, config, destination, _WEG_CONFIG, max_results=max_results
    )


_PORTAL_SEARCH_HANDLERS: Dict[
    str, Callable[[Page, AgentConfig, str], Awaitable[List[RawOffer]]]
] = {
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
