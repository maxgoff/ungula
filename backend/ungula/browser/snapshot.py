"""
DOM snapshot — creates a numbered list of interactive elements.

Filters to visible, interactive elements to keep the output concise
and useful for LLM-driven browser interaction.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Elements we consider interactive/important
INTERACTIVE_TAGS = {
    "a", "button", "input", "select", "textarea", "option",
    "details", "summary", "label",
}

# Roles that indicate interactivity
INTERACTIVE_ROLES = {
    "button", "link", "textbox", "checkbox", "radio", "combobox",
    "menuitem", "tab", "switch", "slider", "searchbox",
}


async def create_snapshot(page: Any) -> str:
    """Create a numbered snapshot of interactive page elements.

    Returns a string like:
        [1] <button> "Submit"
        [2] <input name="email" placeholder="Enter email">
        [3] <a href="/about"> "About Us"
    """
    elements = await page.evaluate("""() => {
        const results = [];
        const interactiveTags = new Set([
            'a', 'button', 'input', 'select', 'textarea', 'option',
            'details', 'summary', 'label'
        ]);
        const interactiveRoles = new Set([
            'button', 'link', 'textbox', 'checkbox', 'radio', 'combobox',
            'menuitem', 'tab', 'switch', 'slider', 'searchbox'
        ]);

        const allElements = document.querySelectorAll('*');
        let index = 0;

        for (const el of allElements) {
            const tag = el.tagName.toLowerCase();
            const role = el.getAttribute('role');

            // Check if element is interactive
            const isInteractive = interactiveTags.has(tag)
                || (role && interactiveRoles.has(role))
                || el.hasAttribute('onclick')
                || el.hasAttribute('tabindex');

            if (!isInteractive) continue;

            // Check visibility
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            if (rect.width === 0 && rect.height === 0) continue;
            if (style.display === 'none' || style.visibility === 'hidden') continue;

            index++;
            const info = {
                index: index,
                tag: tag,
                text: (el.textContent || '').trim().slice(0, 80),
                type: el.getAttribute('type'),
                name: el.getAttribute('name'),
                placeholder: el.getAttribute('placeholder'),
                href: tag === 'a' ? el.getAttribute('href') : null,
                value: ['input', 'textarea', 'select'].includes(tag)
                    ? (el.value || '').slice(0, 50) : null,
                role: role,
                checked: el.checked,
                disabled: el.disabled,
            };

            // Store xpath for later reference
            el.setAttribute('data-snap-id', String(index));
            results.push(info);
        }
        return results;
    }""")

    if not elements:
        # Fallback: show page title and text content
        title = await page.title()
        text = await page.evaluate("() => document.body?.innerText?.slice(0, 500) || ''")
        return f"Page: {title}\nNo interactive elements found.\n\nPage text:\n{text}"

    lines = []
    for el in elements:
        parts = [f"[{el['index']}]", f"<{el['tag']}>"]

        if el.get("type"):
            parts.append(f'type="{el["type"]}"')
        if el.get("name"):
            parts.append(f'name="{el["name"]}"')
        if el.get("placeholder"):
            parts.append(f'placeholder="{el["placeholder"]}"')
        if el.get("href"):
            parts.append(f'href="{el["href"]}"')
        if el.get("value"):
            parts.append(f'value="{el["value"]}"')
        if el.get("role"):
            parts.append(f'role="{el["role"]}"')
        if el.get("checked"):
            parts.append("[checked]")
        if el.get("disabled"):
            parts.append("[disabled]")
        if el.get("text"):
            parts.append(f'"{el["text"]}"')

        lines.append(" ".join(parts))

    title = await page.title()
    url = page.url
    header = f"Page: {title}\nURL: {url}\n\n"
    return header + "\n".join(lines)
