"""
Browser automation tool — provides browser control via Playwright.
"""

import base64
import logging
from typing import Any

from ungula.tools.base import Tool, ToolParameter, ToolResult

logger = logging.getLogger(__name__)


class BrowserTool(Tool):
    """Control a web browser for navigation, interaction, and data extraction."""

    name = "browser"
    description = "Control a web browser: navigate to pages, snapshot interactive elements, click/type/select, take screenshots. Start the browser first, then navigate and interact."
    parameters = [
        ToolParameter(
            name="action",
            description="Action: status, start, stop, navigate, snapshot, screenshot, act, tabs",
            required=True,
        ),
        ToolParameter(name="url", description="URL for navigate action", required=False),
        ToolParameter(name="element", description="Element number from snapshot (for act)", type="integer", required=False),
        ToolParameter(name="interaction", description="Interaction type: click, type, select, scroll, hover, clear", required=False),
        ToolParameter(name="value", description="Value for type/select/scroll interactions", required=False),
    ]

    def __init__(self, browser_manager: Any):
        self.manager = browser_manager

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "").lower()

        if action == "status":
            return ToolResult(success=True, output=str(self.manager.status()), data=self.manager.status())

        if action == "start":
            try:
                await self.manager.start()
                return ToolResult(success=True, output="Browser started")
            except Exception as e:
                return ToolResult(success=False, output="", error=str(e))

        if action == "stop":
            await self.manager.stop()
            return ToolResult(success=True, output="Browser stopped")

        if action == "navigate":
            url = kwargs.get("url", "")
            if not url:
                return ToolResult(success=False, output="", error="url is required for navigate")
            try:
                result = await self.manager.navigate(url)
                return ToolResult(
                    success=True,
                    output=f"Navigated to {result['url']} — {result['title']}",
                    data=result,
                )
            except Exception as e:
                return ToolResult(success=False, output="", error=str(e))

        if action == "snapshot":
            try:
                snap = await self.manager.snapshot()
                return ToolResult(success=True, output=snap)
            except Exception as e:
                return ToolResult(success=False, output="", error=str(e))

        if action == "screenshot":
            try:
                img_bytes = await self.manager.screenshot()
                b64 = base64.b64encode(img_bytes).decode("ascii")
                return ToolResult(
                    success=True,
                    output=f"Screenshot taken ({len(img_bytes)} bytes)",
                    data={"image_base64": b64, "mime_type": "image/png"},
                )
            except Exception as e:
                return ToolResult(success=False, output="", error=str(e))

        if action == "act":
            element = kwargs.get("element")
            interaction = kwargs.get("interaction", "")
            value = kwargs.get("value")

            if element is None:
                return ToolResult(success=False, output="", error="element number is required for act")
            if not interaction:
                return ToolResult(success=False, output="", error="interaction is required for act")

            try:
                result = await self.manager.act(int(element), interaction, value)
                return ToolResult(success=True, output=result)
            except Exception as e:
                return ToolResult(success=False, output="", error=str(e))

        if action == "tabs":
            try:
                tabs = await self.manager.get_tabs()
                lines = [f"[{t['id']}] {'*' if t['active'] else ' '} {t['url']} — {t['title']}" for t in tabs]
                return ToolResult(
                    success=True,
                    output="\n".join(lines) or "No tabs open",
                    data={"tabs": tabs},
                )
            except Exception as e:
                return ToolResult(success=False, output="", error=str(e))

        return ToolResult(success=False, output="", error=f"Unknown action: {action}")
