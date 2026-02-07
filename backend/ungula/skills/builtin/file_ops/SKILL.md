---
name: file_ops
version: "1.0.0"
description: Read, write, edit, and search workspace files
author: ungula
enabled: true
ungula:
  module: tools
  inject_prompt: true
  emoji: "F"
requires: {}
---

# File Operations

You have access to file operation tools for working with files in the workspace.

## Available Tools

- `file_read` — Read file contents with optional line range
- `file_write` — Write or append to files
- `file_edit` — Find-and-replace text in files
- `file_search` — Search across workspace files by content

## Safety

- All file operations are restricted to the workspace directory
- Path traversal attempts (using `..`) are blocked
- Symlinks pointing outside the workspace are rejected
- Certain file extensions (.env, .key, .pem) are blocked by default
