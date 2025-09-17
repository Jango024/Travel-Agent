"""Portal-specific Playwright scraping helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Sequence
from urllib.parse import urljoin

from agent_core.config import AgentConfig
from agent_core.models import RawOffer
from .playwright_common import (
    RECOMMENDATION_PATTERN,
    build_portal_metadata,
    collect_cards,
    dismiss_common_banners,
    extract_attribute,
    extract_text,
    parse_price_from_text,
    try_fill_field,
    try_select_option,
)

try:  # pragma: no cover - optional dependency during development
    from playwright.async_api import Page
except Exception:  # pragma: no cover
    Page = Any  # type: ignore

PortalHandler = Callable[[Page, AgentConfig, str], Awaitable[List[RawOffer]]]


@dataclass(frozen=True)
class PortalFormSelectors:
    """Selectors used to populate the search form of a travel portal."""

    destination: Sequence[str]
    travellers: Sequence[str] = ()
    departure_date: Sequence[str] = ()
    return_date: Sequence[str] = ()
    budget: Sequence[str] = ()
    submit: Sequence[str] = ("button[type='submit']",)


@dataclass(frozen=True)
class PortalResultSelectors:
    """Selectors describing how to parse result cards for a portal."""

    cards: Sequence[str]
    title: Sequence[str]
    link: Sequence[str]
    price: Sequence[str] = ()
    board: Sequence[str] = ()
    duration: Sequence[str] = ()
    rating: Sequence[str] = ()


@dataclass(frozen=True)
class PortalScraperConfig:
    """Complete configuration required to scrape a travel portal."""

    provider: str
    base_url: str
    search_path: str
    form: PortalFormSelectors
    results: PortalResultSelectors


async def _search_portal(
    page: Page, portal: PortalScraperConfig, config: AgentConfig, destination: str
) -> List[RawOffer]:
    """Perform a search on a configured portal and return offers."""

    search_url = urljoin(portal.base_url, portal.search_path)

    await page.goto(search_url, wait_until="networkidle")
    await dismiss_common_banners(page)

    await try_fill_field(page, portal.form.destination, destination)

    travellers_value = str(config.travellers or "").strip()
    if travellers_value:
        await try_select_option(page, portal.form.travellers, travellers_value)
        await try_fill_field(page, portal.form.travellers, travellers_value)

    if config.departure_date:
        await try_fill_field(
            page, portal.form.departure_date, config.departure_date.isoformat()
        )
    if config.return_date:
        await try_fill_field(page, portal.form.return_date, config.return_date.isoformat())
    if config.budget is not None:
        await try_fill_field(page, portal.form.budget, str(int(config.budget)))

    submitted = False
    submit_selectors = portal.form.submit or ("button[type='submit']",)
    for selector in submit_selectors:
        try:
            await page.click(selector)
            submitted = True
            break
        except Exception:
            continue
    if not submitted:
        for selector in submit_selectors:
            try:
                await page.locator(selector).first.click(timeout=1500)
                break
            except Exception:
                continue

    try:
        await page.wait_for_load_state("networkidle")
    except Exception:
        pass

    cards = await collect_cards(page, portal.results.cards)

    offers: List[RawOffer] = []
    base_metadata = build_portal_metadata(config, destination, search_url)

    for card in cards:
        title = await extract_text(card, portal.results.title)
        href = await extract_attribute(card, portal.results.link, "href")
        if not title or not href:
            continue

        price_text = await extract_text(card, portal.results.price)
        price = parse_price_from_text(price_text or "") if price_text else None

        metadata = base_metadata.copy()

        board = await extract_text(card, portal.results.board)
        if board:
            metadata["board"] = board

        duration = await extract_text(card, portal.results.duration)
        if duration:
            metadata["duration"] = duration

        rating_text = await extract_text(card, portal.results.rating)
        if rating_text:
            match = RECOMMENDATION_PATTERN.search(rating_text)
            if match:
                try:
                    metadata["recommendation_score"] = float(match.group(1))
                except ValueError:
                    pass

        offers.append(
            RawOffer(
                provider=portal.provider,
                title=title,
                price=price,
                url=urljoin(portal.base_url, href),
                metadata=metadata,
            )
        )

    return offers


def _build_handler(portal: PortalScraperConfig) -> PortalHandler:
    async def handler(page: Page, config: AgentConfig, destination: str) -> List[RawOffer]:
        return await _search_portal(page, portal, config, destination)

    return handler


_HOLIDAYCHECK = PortalScraperConfig(
    provider="holidaycheck.de",
    base_url="https://www.holidaycheck.de",
    search_path="/suche",
    form=PortalFormSelectors(
        destination=("input[name='destination']",),
        travellers=("select[name='travellers']",),
        departure_date=("input[name='departure']", "input[name='from']"),
        return_date=("input[name='return']", "input[name='to']"),
        budget=("input[name='budget']", "input[name='price']"),
        submit=("button[type='submit']",),
    ),
    results=PortalResultSelectors(
        cards=(
            "[data-testid='offer-card']",
            "article[data-testid='hc-result-card']",
            "article[data-testid='offer-card']",
            "article",
        ),
        title=(
            "[data-testid='offer-title']",
            "[data-testid='result-title']",
            ".offer-title",
            "header h3",
        ),
        link=(
            "a[data-testid='offer-link']",
            "a[data-testid='result-link']",
            "a[href]",
        ),
        price=(
            "[data-testid='offer-price']",
            "[data-testid='result-price']",
            ".offer-price",
            ".price",
        ),
        board=(
            "[data-testid='offer-board']",
            "[data-testid='result-board']",
            ".board",
        ),
        duration=(
            "[data-testid='offer-duration']",
            "[data-testid='result-duration']",
            ".duration",
        ),
        rating=(
            "[data-testid='offer-rating']",
            "[data-testid='result-rating']",
            ".rating",
        ),
    ),
)

_TUI = PortalScraperConfig(
    provider="tui.com",
    base_url="https://www.tui.com",
    search_path="/suche",
    form=PortalFormSelectors(
        destination=("input[name='q']", "input[name='destination']"),
        travellers=("select[name='travellers']",),
        departure_date=("input[name='departure']", "input[name='from']"),
        return_date=("input[name='return']", "input[name='to']"),
        budget=("input[name='maxPrice']", "input[name='budget']"),
        submit=("button[type='submit']",),
    ),
    results=PortalResultSelectors(
        cards=(
            "[data-testid='result-card']",
            "article[data-testid='offer-card']",
            "article",
        ),
        title=(
            "[data-testid='result-title']",
            "[data-testid='offer-title']",
            ".offer-title",
            "header h3",
        ),
        link=(
            "a[data-testid='result-link']",
            "a[data-testid='offer-link']",
            "a[href]",
        ),
        price=(
            "[data-testid='result-price']",
            "[data-testid='offer-price']",
            ".offer-price",
            ".price",
        ),
        board=(
            "[data-testid='result-board']",
            "[data-testid='offer-board']",
            ".board",
        ),
        duration=(
            "[data-testid='result-duration']",
            "[data-testid='offer-duration']",
            ".duration",
        ),
    ),
)

_AB_IN_DEN_URLAUB = PortalScraperConfig(
    provider="ab-in-den-urlaub.de",
    base_url="https://www.ab-in-den-urlaub.de",
    search_path="/suche",
    form=PortalFormSelectors(
        destination=("input[name='destination']",),
        travellers=("select[name='travellers']",),
        departure_date=("input[name='departure']", "input[name='from']"),
        return_date=("input[name='return']", "input[name='to']"),
        budget=("input[name='budget']", "input[name='price']"),
        submit=("button[type='submit']",),
    ),
    results=PortalResultSelectors(
        cards=(
            "article[data-testid='offer-card']",
            "[data-testid='offer-card']",
            "article",
        ),
        title=(
            "[data-testid='offer-title']",
            "[data-testid='result-title']",
            ".offer-title",
            "header h3",
        ),
        link=(
            "a[data-testid='offer-link']",
            "a[data-testid='result-link']",
            "a[href]",
        ),
        price=(
            "[data-testid='offer-price']",
            "[data-testid='result-price']",
            ".offer-price",
            ".price",
        ),
        board=(
            "[data-testid='offer-board']",
            "[data-testid='result-board']",
            ".board",
        ),
        duration=(
            "[data-testid='offer-duration']",
            "[data-testid='result-duration']",
            ".duration",
        ),
        rating=(
            "[data-testid='offer-rating']",
            "[data-testid='result-rating']",
            ".rating",
        ),
    ),
)

_WEG = PortalScraperConfig(
    provider="weg.de",
    base_url="https://www.weg.de",
    search_path="/suche",
    form=PortalFormSelectors(
        destination=("input[name='destination']",),
        travellers=("select[name='travellers']",),
        departure_date=("input[name='departure']", "input[name='from']"),
        return_date=("input[name='return']", "input[name='to']"),
        budget=("input[name='budget']", "input[name='price']"),
        submit=("button[type='submit']",),
    ),
    results=PortalResultSelectors(
        cards=(
            "[data-testid='result-card']",
            "article[data-testid='offer-card']",
            "article",
        ),
        title=(
            "[data-testid='result-title']",
            "[data-testid='offer-title']",
            ".offer-title",
            "header h3",
        ),
        link=(
            "a[data-testid='result-link']",
            "a[data-testid='offer-link']",
            "a[href]",
        ),
        price=(
            "[data-testid='result-price']",
            "[data-testid='offer-price']",
            ".offer-price",
            ".price",
        ),
        board=(
            "[data-testid='result-board']",
            "[data-testid='offer-board']",
            ".board",
        ),
        duration=(
            "[data-testid='result-duration']",
            "[data-testid='offer-duration']",
            ".duration",
        ),
    ),
)

PORTAL_HANDLERS: Dict[str, PortalHandler] = {}
for domains, portal in {
    ("holidaycheck.de", "www.holidaycheck.de"): _HOLIDAYCHECK,
    ("tui.com", "www.tui.com"): _TUI,
    (
        "ab-in-den-urlaub.de",
        "www.ab-in-den-urlaub.de",
    ): _AB_IN_DEN_URLAUB,
    ("weg.de", "www.weg.de"): _WEG,
}.items():
    handler = _build_handler(portal)
    for domain in domains:
        PORTAL_HANDLERS[domain] = handler

__all__ = ["PORTAL_HANDLERS", "PortalHandler", "PortalScraperConfig"]
