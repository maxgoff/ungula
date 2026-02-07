---
name: node_invoke
version: "1.0.0"
description: Execute commands on connected companion device nodes
author: ungula
enabled: true
ungula:
  module: tool
  inject_prompt: true
  emoji: "N"
requires: {}
---

# Node Invoke

Execute commands on connected companion devices (nodes).

## Available Commands

Depends on each node's registered capabilities:
- `camera.capture` — Capture a photo (requires "camera" capability)
- `screen.capture` — Screenshot the screen (requires "screen" capability)
- `location.get` — Get GPS coordinates (requires "location" capability)
- `notify.send` — Send OS notification (requires "notify" capability)
- `system.run` — Run a shell command on the node (requires "system.run" capability)
- `sms.send` — Send an SMS (requires "sms.send" capability)

## Usage

Specify the target node by ID, or use `node_id="any"` to pick the first capable node.
