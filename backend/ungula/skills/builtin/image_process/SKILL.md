---
name: image_process
version: "1.0.0"
description: Resize, crop, rotate, convert, and inspect images
author: ungula
enabled: true
ungula:
  module: tool
  inject_prompt: true
  emoji: "I"
requires: {}
---

# Image Processing

You have access to an `image_process` tool for manipulating images in the workspace.

## Available Actions

- `info` — Get image metadata (dimensions, format, mode, file size)
- `resize` — Resize an image (aspect-ratio-safe by default)
- `crop` — Crop to specified box coordinates
- `rotate` — Rotate by a given number of degrees
- `convert` — Convert between formats (png, jpeg, webp, bmp)
- `thumbnail` — Generate a thumbnail fitting within a max dimension

## Safety

- All file paths are restricted to the workspace directory
- Path traversal attempts (using `..`) are blocked
- Certain file extensions (.env, .key, .pem) are blocked
