"""
Browser actions — resolve element references and perform interactions.

Uses the data-snap-id attribute set during snapshot to locate elements.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def perform_action(page: Any, element: int, interaction: str, value: str | None = None) -> str:
    """Perform an action on a snapshot-numbered element.

    Args:
        page: Playwright page object
        element: Element number from snapshot
        interaction: One of: click, type, select, scroll, hover, clear
        value: Value for type/select interactions

    Returns:
        Description of what happened.
    """
    selector = f'[data-snap-id="{element}"]'

    # Check element exists
    el = await page.query_selector(selector)
    if not el:
        return f"Element [{element}] not found. Try taking a new snapshot."

    try:
        if interaction == "click":
            await el.click()
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
            return f"Clicked element [{element}]. Page: {await page.title()}"

        elif interaction == "type":
            if value is None:
                return "Error: value is required for type interaction"
            await el.fill(value)
            return f"Typed '{value}' into element [{element}]"

        elif interaction == "select":
            if value is None:
                return "Error: value is required for select interaction"
            await el.select_option(value)
            return f"Selected '{value}' in element [{element}]"

        elif interaction == "scroll":
            direction = (value or "down").lower()
            if direction == "up":
                await page.evaluate("window.scrollBy(0, -500)")
            elif direction == "down":
                await page.evaluate("window.scrollBy(0, 500)")
            elif direction == "top":
                await page.evaluate("window.scrollTo(0, 0)")
            elif direction == "bottom":
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            else:
                await page.evaluate("window.scrollBy(0, 500)")
            return f"Scrolled {direction}"

        elif interaction == "hover":
            await el.hover()
            return f"Hovered over element [{element}]"

        elif interaction == "clear":
            await el.fill("")
            return f"Cleared element [{element}]"

        else:
            return f"Unknown interaction: {interaction}. Use: click, type, select, scroll, hover, clear"

    except Exception as e:
        return f"Action failed on element [{element}]: {e}"
