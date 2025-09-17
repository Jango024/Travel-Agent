import asyncio
from xml.etree import ElementTree as ET
import unittest
from unittest.mock import AsyncMock, patch

from agent_core.scraper import _extract_duckduckgo_results


class _FakeElement:
    def __init__(self, element: ET.Element) -> None:
        self._element = element

    async def query_selector(self, selector: str):  # type: ignore[override]
        if selector == "a[data-testid='result-title-a']":
            return self._find_by_attr("a", "data-testid", "result-title-a")
        if selector == "a.result__a":
            return self._find_by_class("a", "result__a")
        if selector == "div[data-testid='result-snippet']":
            return self._find_by_attr("div", "data-testid", "result-snippet")
        if selector == "div.result__snippet":
            return self._find_by_class("div", "result__snippet")
        return None

    def _find_by_attr(self, tag: str, attribute: str, value: str):
        for child in self._element.findall(f".//{tag}"):
            if child.attrib.get(attribute) == value:
                return _FakeElement(child)
        return None

    def _find_by_class(self, tag: str, class_name: str):
        for child in self._element.findall(f".//{tag}"):
            classes = child.attrib.get("class", "").split()
            if class_name in classes:
                return _FakeElement(child)
        return None

    async def inner_text(self) -> str:  # type: ignore[override]
        return "".join(self._element.itertext())

    async def get_attribute(self, name: str):  # type: ignore[override]
        return self._element.attrib.get(name)


class _FakePage:
    def __init__(self, html: str) -> None:
        self._root = ET.fromstring(html)

    async def goto(self, url: str, wait_until: str = "networkidle") -> None:  # type: ignore[override]
        self.last_url = url
        self.wait_until = wait_until

    async def query_selector_all(self, selector: str):  # type: ignore[override]
        if selector == "article[data-testid='result']":
            return [
                _FakeElement(element)
                for element in self._root.findall(".//article[@data-testid='result']")
            ]
        if selector == "article.result":
            return [
                _FakeElement(element)
                for element in self._root.findall(".//article[@class]")
                if "result" in element.attrib.get("class", "").split()
            ]
        return []


class ExtractDuckDuckGoResultTests(unittest.TestCase):
    def test_offer_provider_contains_host_from_result_url(self) -> None:
        html = """
        <html>
            <body>
                <article data-testid="result">
                    <a data-testid="result-title-a" href="https://example.com/offers/berlin">
                        Traumreise Berlin
                    </a>
                    <div data-testid="result-snippet">Günstige Reise für 199€</div>
                </article>
            </body>
        </html>
        """
        page = _FakePage(html)

        with patch("agent_core.scraper._dismiss_common_banners", new=AsyncMock()) as mock_banner:
            offers = asyncio.run(_extract_duckduckgo_results(page, "Berlin"))

        mock_banner.assert_awaited()
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].provider, "example.com")


if __name__ == "__main__":
    unittest.main()
