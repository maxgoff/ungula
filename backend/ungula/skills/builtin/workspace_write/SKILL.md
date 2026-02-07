---
name: workspace_write
version: "1.0.0"
description: Update workspace files (USER.md, MEMORY.md, etc.) and daily memory notes
author: ungula
enabled: true
ungula:
  module: tool
  inject_prompt: true
  emoji: "W"
requires: {}
---

# Workspace Write

You can update workspace files to remember things about the user, adjust your identity,
and maintain daily memory notes.

## Available Tool

- `workspace_write` — Write or append to a workspace file

## Allowed Files

- `USER.md` — User context and preferences
- `MEMORY.md` — Long-term memory and learnings
- `IDENTITY.md` — Your identity configuration
- `SOUL.md` — Your persona and boundaries
- `TOOLS.md` — Local tool notes
- `HEARTBEAT.md` — Periodic task checklist
- `BOOT.md` — Startup tasks
- `memory/*.md` — Daily memory files (e.g. `memory/2026-01-15-bug-fix.md`)

## Not Allowed

- `AGENTS.md` — Too critical to overwrite without user approval
- `BOOTSTRAP.md` — Can only be deleted, not modified

## When to Write

- After learning something important about the user → update USER.md
- After a significant session → create a memory file in memory/
- When the user asks you to remember something → update MEMORY.md
- During bootstrap → update IDENTITY.md, USER.md, SOUL.md
