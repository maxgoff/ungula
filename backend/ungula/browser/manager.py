"""
Browser manager — manages Playwright browser instance and tabs.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class BrowserManager:
    """Manages a Playwright browser instance with tab tracking."""

    def __init__(self, headless: bool = True, timeout: int = 30, max_tabs: int = 5):
        self.headless = headless
        self.timeout = timeout * 1000  # Playwright uses ms
        self.max_tabs = max_tabs
        self._playwright = None
        self._browser = None
        self._pages: dict[int, Any] = {}  # tab_id -> Page
        self._active_tab: int = 0
        self._next_tab_id: int = 0

    @property
    def is_running(self) -> bool:
        return self._browser is not None and self._browser.is_connected()

    async def start(self) -> None:
        """Start the browser."""
        if self.is_running:
            return

        try:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=self.headless)
            logger.info("Browser started (headless=%s)", self.headless)
        except ImportError:
            raise RuntimeError("playwright is not installed. Install with: pip install playwright && playwright install chromium")

    async def stop(self) -> None:
        """Stop the browser and cleanup."""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        self._pages.clear()
        logger.info("Browser stopped")

    async def _ensure_page(self) -> Any:
        """Get the active page, creating one if needed."""
        if not self.is_running:
            await self.start()

        if self._active_tab not in self._pages:
            page = await self._browser.new_page()
            page.set_default_timeout(self.timeout)
            tab_id = self._next_tab_id
            self._next_tab_id += 1
            self._pages[tab_id] = page
            self._active_tab = tab_id

        return self._pages[self._active_tab]

    async def navigate(self, url: str) -> dict[str, Any]:
        """Navigate to a URL."""
        page = await self._ensure_page()
        response = await page.goto(url, wait_until="domcontentloaded")
        return {
            "url": page.url,
            "title": await page.title(),
            "status": response.status if response else None,
        }

    async def snapshot(self) -> str:
        """Create an accessibility-oriented DOM snapshot.

        Returns numbered list of interactive/visible elements.
        """
        page = await self._ensure_page()
        from .snapshot import create_snapshot
        return await create_snapshot(page)

    async def screenshot(self) -> bytes:
        """Take a screenshot of the current page."""
        page = await self._ensure_page()
        return await page.screenshot()

    async def act(self, element: int, interaction: str, value: str | None = None) -> str:
        """Perform an action on a numbered element from the snapshot."""
        page = await self._ensure_page()
        from .actions import perform_action
        return await perform_action(page, element, interaction, value)

    async def get_tabs(self) -> list[dict[str, Any]]:
        """List open tabs."""
        tabs = []
        for tab_id, page in self._pages.items():
            tabs.append({
                "id": tab_id,
                "url": page.url,
                "title": await page.title(),
                "active": tab_id == self._active_tab,
            })
        return tabs

    def status(self) -> dict[str, Any]:
        """Get browser status."""
        return {
            "running": self.is_running,
            "headless": self.headless,
            "tabs": len(self._pages),
            "active_tab": self._active_tab,
        }
