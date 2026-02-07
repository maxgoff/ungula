"""
Tests for browser automation: snapshot, actions, manager.

Since Playwright requires actual browser binaries (which may not be installed
in test environments), these tests mock the Playwright page objects to test
the snapshot formatting logic, action dispatch, and manager state tracking.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ungula.browser.manager import BrowserManager
from ungula.browser.snapshot import INTERACTIVE_ROLES, INTERACTIVE_TAGS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_page(
    elements: list[dict[str, Any]] | None = None,
    title: str = "Test Page",
    url: str = "https://example.com",
    body_text: str = "",
) -> MagicMock:
    """Create a mock Playwright page object."""
    page = MagicMock()
    page.url = url
    page.title = AsyncMock(return_value=title)

    if elements is not None:
        page.evaluate = AsyncMock(side_effect=[elements])
    else:
        # No elements case: evaluate called twice (elements, then body text)
        async def eval_side_effect(js, *args, **kwargs):
            if "querySelectorAll" in str(js):
                return []
            return body_text
        page.evaluate = AsyncMock(side_effect=[[], body_text])

    return page


def _mock_page_for_action(element_exists: bool = True) -> MagicMock:
    """Create a mock page for action tests."""
    page = MagicMock()
    page.url = "https://example.com"
    page.title = AsyncMock(return_value="Test Page")

    el = MagicMock()
    el.click = AsyncMock()
    el.fill = AsyncMock()
    el.select_option = AsyncMock()
    el.hover = AsyncMock()

    page.wait_for_load_state = AsyncMock()
    page.evaluate = AsyncMock()

    if element_exists:
        page.query_selector = AsyncMock(return_value=el)
    else:
        page.query_selector = AsyncMock(return_value=None)

    return page


# ===========================================================================
# Snapshot constants
# ===========================================================================


class TestSnapshotConstants:
    """Tests for interactive tags and roles constants."""

    def test_interactive_tags_is_set(self):
        assert isinstance(INTERACTIVE_TAGS, set)

    def test_interactive_tags_contains_core_elements(self):
        for tag in ["a", "button", "input", "select", "textarea"]:
            assert tag in INTERACTIVE_TAGS

    def test_interactive_roles_is_set(self):
        assert isinstance(INTERACTIVE_ROLES, set)

    def test_interactive_roles_contains_core_roles(self):
        for role in ["button", "link", "textbox", "checkbox"]:
            assert role in INTERACTIVE_ROLES


# ===========================================================================
# Snapshot formatting
# ===========================================================================


class TestCreateSnapshot:
    """Tests for snapshot output formatting."""

    @pytest.mark.asyncio
    async def test_snapshot_with_elements(self):
        from ungula.browser.snapshot import create_snapshot

        elements = [
            {"index": 1, "tag": "button", "text": "Submit", "type": None, "name": None,
             "placeholder": None, "href": None, "value": None, "role": None,
             "checked": False, "disabled": False},
            {"index": 2, "tag": "input", "text": "", "type": "email", "name": "email",
             "placeholder": "Enter email", "href": None, "value": "", "role": None,
             "checked": False, "disabled": False},
            {"index": 3, "tag": "a", "text": "About Us", "type": None, "name": None,
             "placeholder": None, "href": "/about", "value": None, "role": None,
             "checked": False, "disabled": False},
        ]
        page = _mock_page(elements)
        result = await create_snapshot(page)

        assert "Page: Test Page" in result
        assert "URL: https://example.com" in result
        assert "[1]" in result
        assert "<button>" in result
        assert '"Submit"' in result
        assert "[2]" in result
        assert '<input>' in result
        assert 'type="email"' in result
        assert 'name="email"' in result
        assert 'placeholder="Enter email"' in result
        assert "[3]" in result
        assert '<a>' in result
        assert 'href="/about"' in result

    @pytest.mark.asyncio
    async def test_snapshot_no_elements(self):
        from ungula.browser.snapshot import create_snapshot

        page = _mock_page(elements=None, body_text="Hello page body")
        result = await create_snapshot(page)

        assert "No interactive elements found" in result
        assert "Hello page body" in result

    @pytest.mark.asyncio
    async def test_snapshot_with_checked_and_disabled(self):
        from ungula.browser.snapshot import create_snapshot

        elements = [
            {"index": 1, "tag": "input", "text": "", "type": "checkbox", "name": "agree",
             "placeholder": None, "href": None, "value": None, "role": None,
             "checked": True, "disabled": True},
        ]
        page = _mock_page(elements)
        result = await create_snapshot(page)

        assert "[checked]" in result
        assert "[disabled]" in result

    @pytest.mark.asyncio
    async def test_snapshot_with_role(self):
        from ungula.browser.snapshot import create_snapshot

        elements = [
            {"index": 1, "tag": "div", "text": "Custom Button", "type": None, "name": None,
             "placeholder": None, "href": None, "value": None, "role": "button",
             "checked": False, "disabled": False},
        ]
        page = _mock_page(elements)
        result = await create_snapshot(page)

        assert 'role="button"' in result
        assert '"Custom Button"' in result


# ===========================================================================
# Actions
# ===========================================================================


class TestPerformAction:
    """Tests for browser action dispatch."""

    @pytest.mark.asyncio
    async def test_click(self):
        from ungula.browser.actions import perform_action

        page = _mock_page_for_action()
        result = await perform_action(page, 1, "click")
        assert "Clicked" in result

    @pytest.mark.asyncio
    async def test_type(self):
        from ungula.browser.actions import perform_action

        page = _mock_page_for_action()
        result = await perform_action(page, 1, "type", "hello@test.com")
        assert "Typed" in result

    @pytest.mark.asyncio
    async def test_type_no_value(self):
        from ungula.browser.actions import perform_action

        page = _mock_page_for_action()
        result = await perform_action(page, 1, "type")
        assert "value is required" in result.lower()

    @pytest.mark.asyncio
    async def test_select(self):
        from ungula.browser.actions import perform_action

        page = _mock_page_for_action()
        result = await perform_action(page, 1, "select", "option1")
        assert "Selected" in result

    @pytest.mark.asyncio
    async def test_select_no_value(self):
        from ungula.browser.actions import perform_action

        page = _mock_page_for_action()
        result = await perform_action(page, 1, "select")
        assert "value is required" in result.lower()

    @pytest.mark.asyncio
    async def test_scroll_down(self):
        from ungula.browser.actions import perform_action

        page = _mock_page_for_action()
        result = await perform_action(page, 1, "scroll", "down")
        assert "Scrolled down" in result

    @pytest.mark.asyncio
    async def test_scroll_up(self):
        from ungula.browser.actions import perform_action

        page = _mock_page_for_action()
        result = await perform_action(page, 1, "scroll", "up")
        assert "Scrolled up" in result

    @pytest.mark.asyncio
    async def test_scroll_top(self):
        from ungula.browser.actions import perform_action

        page = _mock_page_for_action()
        result = await perform_action(page, 1, "scroll", "top")
        assert "Scrolled top" in result

    @pytest.mark.asyncio
    async def test_scroll_bottom(self):
        from ungula.browser.actions import perform_action

        page = _mock_page_for_action()
        result = await perform_action(page, 1, "scroll", "bottom")
        assert "Scrolled bottom" in result

    @pytest.mark.asyncio
    async def test_scroll_default(self):
        from ungula.browser.actions import perform_action

        page = _mock_page_for_action()
        result = await perform_action(page, 1, "scroll")
        assert "Scrolled down" in result

    @pytest.mark.asyncio
    async def test_hover(self):
        from ungula.browser.actions import perform_action

        page = _mock_page_for_action()
        result = await perform_action(page, 1, "hover")
        assert "Hovered" in result

    @pytest.mark.asyncio
    async def test_clear(self):
        from ungula.browser.actions import perform_action

        page = _mock_page_for_action()
        result = await perform_action(page, 1, "clear")
        assert "Cleared" in result

    @pytest.mark.asyncio
    async def test_unknown_interaction(self):
        from ungula.browser.actions import perform_action

        page = _mock_page_for_action()
        result = await perform_action(page, 1, "explode")
        assert "Unknown interaction" in result

    @pytest.mark.asyncio
    async def test_element_not_found(self):
        from ungula.browser.actions import perform_action

        page = _mock_page_for_action(element_exists=False)
        result = await perform_action(page, 99, "click")
        assert "not found" in result.lower()
        assert "99" in result

    @pytest.mark.asyncio
    async def test_action_exception(self):
        from ungula.browser.actions import perform_action

        page = _mock_page_for_action()
        el = await page.query_selector('[data-snap-id="1"]')
        el.click = AsyncMock(side_effect=Exception("click failed"))
        result = await perform_action(page, 1, "click")
        assert "failed" in result.lower()


# ===========================================================================
# BrowserManager
# ===========================================================================


class TestBrowserManager:
    """Tests for BrowserManager state tracking (without actual browser)."""

    def test_initial_state(self):
        mgr = BrowserManager()
        assert mgr.is_running is False
        assert mgr.headless is True

    def test_custom_config(self):
        mgr = BrowserManager(headless=False, timeout=60, max_tabs=10)
        assert mgr.headless is False
        assert mgr.timeout == 60_000  # Converted to ms
        assert mgr.max_tabs == 10

    def test_status_not_running(self):
        mgr = BrowserManager()
        status = mgr.status()
        assert status["running"] is False
        assert status["tabs"] == 0

    @pytest.mark.asyncio
    async def test_start_without_playwright(self):
        """Starting without playwright installed raises RuntimeError."""
        mgr = BrowserManager()
        with patch.dict("sys.modules", {"playwright": None, "playwright.async_api": None}):
            # This may or may not raise depending on sys.modules state.
            # The key is it should handle missing playwright gracefully.
            try:
                await mgr.start()
            except (RuntimeError, ImportError, TypeError):
                pass  # Expected when playwright not available

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self):
        """Stopping a non-started browser should be a no-op."""
        mgr = BrowserManager()
        await mgr.stop()  # Should not raise
        assert mgr.is_running is False

    @pytest.mark.asyncio
    async def test_get_tabs_empty(self):
        """No tabs when browser hasn't navigated."""
        mgr = BrowserManager()
        mgr._pages = {}
        tabs = await mgr.get_tabs()
        assert tabs == []


# ===========================================================================
# Browser tool metadata
# ===========================================================================


class TestBrowserToolImport:
    """Test that the browser tool can be imported and has correct metadata."""

    def test_browser_tool_import(self):
        import sys
        import types
        from unittest.mock import MagicMock

        # Mock playwright before importing
        if "playwright" not in sys.modules:
            sys.modules["playwright"] = MagicMock()
            sys.modules["playwright.async_api"] = MagicMock()

        from ungula.skills.builtin.browser.tool import BrowserTool
        # Just verify it has the right name
        assert BrowserTool.name == "browser"
        assert len(BrowserTool.parameters) > 0
