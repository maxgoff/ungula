"""
Web Search Tool using Brave Search API with Tavily fallback.

Provides web search capabilities for agents.
Fetches actual page content from top results for accurate data.
Falls back to Tavily if Brave fails (e.g., rate limit exhausted).
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from .base import Tool, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
TAVILY_SEARCH_URL = "https://api.tavily.com/search"


@dataclass
class BraveSearchConfig:
    """Configuration for Brave Search."""

    api_key: str
    max_results: int = 5
    fetch_top_n: int = 2  # Fetch full content from top N results
    timeout: float = 10.0


@dataclass
class TavilySearchConfig:
    """Configuration for Tavily Search (fallback)."""

    api_key: str
    max_results: int = 5
    fetch_top_n: int = 2
    timeout: float = 10.0
    search_depth: str = "basic"  # basic, advanced, fast, ultra-fast


class WebSearchTool(Tool):
    """
    Web search tool using Brave Search API with Tavily fallback.

    Searches the web and returns relevant results with titles,
    URLs, and descriptions. Falls back to Tavily if Brave fails.
    """

    name = "web_search"
    description = "Search the web for information. Use this when you need current information, facts, or to look up something you don't know."
    cacheable = True
    parameters = [
        ToolParameter(
            name="query",
            description="The search query - be specific and include relevant keywords",
            type="string",
            required=True,
        ),
        ToolParameter(
            name="num_results",
            description="Number of results to return (1-10)",
            type="integer",
            required=False,
            default=5,
        ),
    ]

    def __init__(
        self,
        config: BraveSearchConfig,
        tavily_config: TavilySearchConfig | None = None,
    ):
        """
        Initialize the web search tool.

        Args:
            config: Brave Search configuration with API key.
            tavily_config: Optional Tavily Search configuration for fallback.
        """
        self.config = config
        self.tavily_config = tavily_config
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.config.timeout)
        return self._client

    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        Execute a web search.

        Tries Brave Search first, falls back to Tavily on failure.

        Args:
            query: The search query.
            num_results: Number of results to return (default: 5).

        Returns:
            ToolResult with search results.
        """
        query = kwargs.get("query")
        if not query:
            return ToolResult(
                success=False,
                output="",
                error="Query parameter is required",
            )

        num_results = min(kwargs.get("num_results", self.config.max_results), 10)

        # Try Brave Search first
        brave_result = await self._search_brave(query, num_results)
        if brave_result.success:
            return brave_result

        # Log Brave failure
        logger.warning("Brave Search failed: %s", brave_result.error)

        # Fall back to Tavily if configured
        if self.tavily_config:
            logger.info("Falling back to Tavily Search")
            tavily_result = await self._search_tavily(query, num_results)
            if tavily_result.success:
                return tavily_result
            logger.error("Tavily Search also failed: %s", tavily_result.error)

        # Return the original Brave error if no fallback or fallback failed
        return brave_result

    async def _search_brave(self, query: str, num_results: int) -> ToolResult:
        """Execute search using Brave Search API."""
        try:
            client = await self._get_client()

            response = await client.get(
                BRAVE_SEARCH_URL,
                params={
                    "q": query,
                    "count": num_results,
                },
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": self.config.api_key,
                },
            )

            if response.status_code != 200:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Brave Search failed with status {response.status_code}: {response.text}",
                )

            data = response.json()
            results = self._parse_brave_results(data)

            if not results:
                return ToolResult(
                    success=True,
                    output=f"No results found for: {query}",
                    data={"query": query, "results": [], "provider": "brave"},
                )

            # Fetch actual page content from top results
            page_contents = await self._fetch_page_contents(results[:self.config.fetch_top_n])

            # Format results for LLM (including page content)
            output = self._format_results(query, results, page_contents, provider="Brave")

            return ToolResult(
                success=True,
                output=output,
                data={"query": query, "results": results, "provider": "brave"},
            )

        except httpx.TimeoutException:
            return ToolResult(
                success=False,
                output="",
                error="Brave Search request timed out",
            )
        except Exception as e:
            logger.error("Brave Search error: %s", e, exc_info=True)
            return ToolResult(
                success=False,
                output="",
                error=f"Brave Search error: {str(e)}",
            )

    async def _search_tavily(self, query: str, num_results: int) -> ToolResult:
        """Execute search using Tavily Search API."""
        if not self.tavily_config:
            return ToolResult(
                success=False,
                output="",
                error="Tavily Search not configured",
            )

        try:
            client = await self._get_client()

            response = await client.post(
                TAVILY_SEARCH_URL,
                headers={
                    "Authorization": f"Bearer {self.tavily_config.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "query": query,
                    "max_results": num_results,
                    "search_depth": self.tavily_config.search_depth,
                    "include_answer": False,
                },
                timeout=self.tavily_config.timeout,
            )

            if response.status_code != 200:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Tavily Search failed with status {response.status_code}: {response.text}",
                )

            data = response.json()
            results = self._parse_tavily_results(data)

            if not results:
                return ToolResult(
                    success=True,
                    output=f"No results found for: {query}",
                    data={"query": query, "results": [], "provider": "tavily"},
                )

            # Tavily already provides content, but fetch more if needed
            page_contents = {}
            for result in results[:self.tavily_config.fetch_top_n]:
                if result.get("content"):
                    page_contents[result["url"]] = result["content"]

            # Format results for LLM
            output = self._format_results(query, results, page_contents, provider="Tavily")

            return ToolResult(
                success=True,
                output=output,
                data={"query": query, "results": results, "provider": "tavily"},
            )

        except httpx.TimeoutException:
            return ToolResult(
                success=False,
                output="",
                error="Tavily Search request timed out",
            )
        except Exception as e:
            logger.error("Tavily Search error: %s", e, exc_info=True)
            return ToolResult(
                success=False,
                output="",
                error=f"Tavily Search error: {str(e)}",
            )

    async def _fetch_page_contents(self, results: list[dict[str, Any]]) -> dict[str, str]:
        """Fetch page content from multiple URLs."""
        page_contents = {}
        for result in results:
            url = result['url']
            logger.info("Fetching page content from: %s", url)
            content = await self._fetch_page_content(url)
            if content:
                page_contents[url] = content
                logger.info("Got %d chars from %s", len(content), url)
        return page_contents

    def _parse_brave_results(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Parse Brave Search API response."""
        results = []

        web_results = data.get("web", {}).get("results", [])
        for item in web_results:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": item.get("description", ""),
            })

        return results

    def _parse_tavily_results(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Parse Tavily Search API response."""
        results = []

        for item in data.get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": item.get("content", ""),  # Tavily uses 'content' field
                "content": item.get("content", ""),  # Store full content
                "score": item.get("score", 0),
            })

        return results

    async def _fetch_page_content(self, url: str) -> str | None:
        """Fetch and extract text content from a URL."""
        try:
            client = await self._get_client()
            response = await client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; UngulaBot/1.0)"},
                follow_redirects=True,
                timeout=8.0,
            )

            if response.status_code != 200:
                return None

            html = response.text

            # Simple HTML to text extraction
            # Remove script and style elements
            html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r'<head[^>]*>.*?</head>', '', html, flags=re.DOTALL | re.IGNORECASE)

            # Remove HTML tags
            text = re.sub(r'<[^>]+>', ' ', html)

            # Clean up whitespace
            text = re.sub(r'\s+', ' ', text).strip()

            # Limit length
            if len(text) > 4000:
                text = text[:4000] + "..."

            return text if len(text) > 100 else None

        except Exception as e:
            logger.debug("Failed to fetch %s: %s", url, e)
            return None

    def _format_results(
        self,
        query: str,
        results: list[dict[str, Any]],
        page_contents: dict[str, str] | None = None,
        provider: str = "Web",
    ) -> str:
        """Format search results for LLM context."""
        lines = [f"{provider} search results for: {query}\n"]

        for i, result in enumerate(results, 1):
            lines.append(f"{i}. {result['title']}")
            lines.append(f"   URL: {result['url']}")
            if result.get("description"):
                # Clean HTML tags from description
                desc = re.sub(r'<[^>]+>', '', result["description"])
                lines.append(f"   {desc}")

            # Include fetched page content if available
            if page_contents and result['url'] in page_contents:
                content = page_contents[result['url']]
                lines.append(f"   [PAGE CONTENT]: {content[:2000]}")

            lines.append("")

        return "\n".join(lines)

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
