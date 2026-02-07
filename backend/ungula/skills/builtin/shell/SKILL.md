---
name: shell
version: "1.0.0"
description: Execute shell commands on the local system
author: ungula
enabled: true
ungula:
  module: tool
  inject_prompt: true
  emoji: ">"
requires: {}
---

# Shell Execution

You have access to a `shell_exec` tool that can execute shell commands on the local system.

## When to Use

- When the user asks you to **run a command** or check system status
- When you need to **read files**, list directories, or check disk usage
- When performing **system administration** tasks the user requests
- When a ClawHub skill requires running a CLI tool (e.g., `himalaya` for email)

## How to Use

Call the `shell_exec` tool with:
- `command` (required): The shell command to execute
- `timeout` (optional): Timeout in seconds (default 10, max 30)

## Safety

- Commands are executed with the same permissions as the Ungula process
- Some dangerous commands are blocked by default (destructive operations)
- Always confirm with the user before running commands that modify the system
- Prefer read-only commands unless the user explicitly requests changes
