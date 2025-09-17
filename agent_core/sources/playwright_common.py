"""Reusable Playwright helpers shared by portal scrapers."""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from agent_core.config import AgentConfig

try:  # pragma: no cover - optional dependency during development
    from playwright.async_api import Page
except Exception:  # pragma: no cover
    Page = Any  # type: ignore

PRICE_PATTERN = re.compile(r"(\d+[\d.,]*)\s?(?:€|eur|euro|euros)?", re.IGNORECASE)
STAR_PATTERN = re.compile(r"(\d(?:[.,]\d)?)\s*(?:sterne|stars)", re.IGNORECASE)
RECOMMENDATION_PATTERN = re.compile(
    r"(\d{1,3})\s?%[^%]*(?:weiterempfehlung|recommended|bewertung)", re.IGNORECASE
)


def parse_price_from_text(text: str) -> Optional[float]:
    """Extract a numeric price from loosely formatted strings."""

    match = PRICE_PATTERN.search(text)
    if not match:
        return None
    try:
        normalised = match.group(1).replace(".", "").replace(",", ".")
        return float(normalised)
    except ValueError:
        return None


async def dismiss_common_banners(page: Page) -> None:
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


async def try_fill_field(page: Page, selectors: Sequence[str], value: str) -> None:
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


async def try_select_option(page: Page, selectors: Sequence[str], value: str) -> None:
    """Attempt to select an option on the first working selector."""

    if not value:
        return
    for selector in selectors:
        try:
            await page.select_option(selector, value)
            return
        except Exception:
            continue


async def extract_text(handle: Any, selectors: Sequence[str]) -> Optional[str]:
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


async def extract_attribute(
    handle: Any, selectors: Sequence[str], attribute: str
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


async def collect_cards(page: Page, selectors: Sequence[str]) -> List[Any]:
    """Return result cards by iterating through fallback selectors."""

    for selector in selectors:
        try:
            cards = await page.query_selector_all(selector)
        except Exception:
            continue
        if cards:
            return cards
    return []


def build_portal_metadata(
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
