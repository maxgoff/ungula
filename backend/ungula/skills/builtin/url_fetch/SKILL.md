---
name: url-fetch
version: "1.0.0"
description: Fetch content from URLs via HTTP
author: ungula
enabled: true
ungula:
  module: tool
  inject_prompt: true
  emoji: "U"
requires: {}
---

# URL Fetch

You have access to a `url_fetch` tool that retrieves content from URLs.

## When to Use

- When you need to fetch the contents of a web page or API endpoint
- When the user provides a URL and asks you to read or summarize its content
- When you need to call a REST API endpoint to get data

## How to Use

Call the `url_fetch` tool with:
- `url` (required): The URL to fetch
- `method` (optional): HTTP method, GET (default) or POST
- `headers` (optional): Dict of HTTP headers to send
- `body` (optional): Request body for POST requests
- `max_length` (optional): Max response length in characters (default 8000)

## Limitations

- Private/internal IP addresses are blocked (SSRF protection)
- Only http:// and https:// schemes are allowed
- Responses are truncated to `max_length` characters
- HTML tags are stripped from text/html responses
- 15 second timeout per request
