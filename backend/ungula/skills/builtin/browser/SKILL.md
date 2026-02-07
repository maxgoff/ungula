---
name: browser
version: "1.0.0"
description: Control a web browser via CDP (Playwright)
author: ungula
enabled: true
ungula:
  module: tool
  inject_prompt: true
  emoji: "B"
requires:
  bins: ["playwright"]
---

# Browser Automation

You have access to a `browser` tool for web browsing and automation.

## Workflow

1. **Start** the browser: `action="start"`
2. **Navigate** to a URL: `action="navigate", url="https://example.com"`
3. **Snapshot** the page: `action="snapshot"` — returns numbered list of interactive elements
4. **Act** on an element: `action="act", element=3, interaction="click"`
5. **Screenshot** for visual check: `action="screenshot"`
6. **Stop** when done: `action="stop"`

## Available Interactions

- `click` — Click an element
- `type` — Type text into an input (`value` required)
- `select` — Select dropdown option (`value` required)
- `scroll` — Scroll page (value: "up", "down", "top", "bottom")
- `hover` — Hover over element
- `clear` — Clear input field
