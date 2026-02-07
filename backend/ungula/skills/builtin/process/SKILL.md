---
name: process
version: "1.0.0"
description: Execute and manage background processes
author: ungula
enabled: true
ungula:
  module: tools
  inject_prompt: true
  emoji: "P"
requires: {}
---

# Process Management

You have access to process execution and management tools.

## Available Tools

- `process_exec` — Execute a command, optionally in the background
- `process_manage` — Manage background processes (list, poll, log, write, kill)

## Background Processes

When running a command with `background=true`, it returns a `process_id` immediately.
Use `process_manage` with that ID to check status, read output, send input, or kill the process.
