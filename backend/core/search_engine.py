"""
Web search - supports Searx (self-hosted), Brave API, and Jina article reader
"""
import asyncio
import logging
from typing import Optional
import httpx
from bs4 import BeautifulSoup
from core.config import settings

logger = logging.getLogger(__name__)


class SearchEngine:

    async def search(self, query: str, n: int = None) -> list[dict]:
        """Search using available backend - Brave first, then Searx, then fallback."""
        n = n or settings.MAX_SEARCH_RESULTS
        results = []

        if settings.BRAVE_API_KEY:
            results = await self._brave_search(query, n)
        if not results:
            results = await self._searx_search(query, n)
        if not results:
            results = await self._duckduckgo_scrape(query, n)

        return results[:n]

    # -- Brave Search ----------------------------------------------------------

    async def _brave_search(self, query: str, n: int) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=settings.SEARCH_TIMEOUT) as client:
                resp = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": n},
                    headers={
                        "Accept": "application/json",
                        "X-Subscription-Token": settings.BRAVE_API_KEY,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "snippet": r.get("description", ""),
                        "source": "brave",
                    }
                    for r in data.get("web", {}).get("results", [])
                ]
        except Exception as e:
            logger.debug("Brave search failed: %s", e)
            return []

    # -- Searx -----------------------------------------------------------------

    async def _searx_search(self, query: str, n: int) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=settings.SEARCH_TIMEOUT) as client:
                resp = await client.get(
                    f"{settings.SEARX_URL}/search",
                    params={"q": query, "format": "json", "categories": "general"},
                )
                resp.raise_for_status()
                data = resp.json()
                return [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "snippet": r.get("content", ""),
                        "source": "searx",
                    }
                    for r in data.get("results", [])[:n]
                ]
        except Exception as e:
            logger.debug("Searx search failed: %s", e)
            return []

    # -- DuckDuckGo fallback (scraping) ----------------------------------------

    async def _duckduckgo_scrape(self, query: str, n: int) -> list[dict]:
        """Lightweight DDG HTML scrape - no API key needed."""
        try:
            headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
            async with httpx.AsyncClient(timeout=settings.SEARCH_TIMEOUT,
                                         follow_redirects=True) as client:
                resp = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                    headers=headers,
                )
                soup = BeautifulSoup(resp.text, "lxml")
                results = []
                for r in soup.select(".result")[:n]:
                    title_el = r.select_one(".result__title a")
                    snippet_el = r.select_one(".result__snippet")
                    if title_el:
                        results.append({
                            "title": title_el.get_text(strip=True),
                            "url": title_el.get("href", ""),
                            "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
                            "source": "duckduckgo",
                        })
                return results
        except Exception as e:
            logger.debug("DuckDuckGo scrape failed: %s", e)
            return []

    # -- Article Reader --------------------------------------------------------

    async def read_url(self, url: str, max_chars: int = 8000) -> dict:
        """Extract full article text from a URL using Jina Reader or direct scrape."""
        # Try Jina first (handles JS-heavy sites)
        content = await self._jina_read(url)
        if not content:
            content = await self._direct_scrape(url)
        return {
            "url": url,
            "content": content[:max_chars] if content else "",
            "chars": len(content) if content else 0,
        }

    async def _jina_read(self, url: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(
                    f"{settings.JINA_BASE_URL}/{url}",
                    headers={"Accept": "text/plain"},
                )
                if resp.status_code == 200:
                    return resp.text
        except Exception:
            pass
        return ""

    async def _direct_scrape(self, url: str) -> str:
        try:
            headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers)
                soup = BeautifulSoup(resp.text, "lxml")
                # Remove noise
                for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                    tag.decompose()
                # Get main content
                for selector in ["article", "main", "[role=main]", ".content", "#content"]:
                    main = soup.select_one(selector)
                    if main:
                        return main.get_text(separator="\n", strip=True)
                return soup.get_text(separator="\n", strip=True)
        except Exception as e:
            logger.debug("Direct scrape failed for %s: %s", url, e)
            return ""


search_engine = SearchEngine()
