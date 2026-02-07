---
name: web-search
version: "1.0.0"
description: Search the web for current information using Brave Search API
author: ungula
enabled: true
ungula:
  module: tool
  inject_prompt: true
  emoji: "S"
requires:
  config:
    - tools.brave_search.api_key
---

# Web Search

You have access to a `web_search` tool that searches the web using the Brave Search API.

## When to Use

- When the user asks about **current events, news, or recent information**
- When asked about **prices, availability, or time-sensitive data**
- When you need to **verify facts** or look up something you're unsure about
- When the user explicitly asks you to **search for something**

## How to Use

Call the `web_search` tool with:
- `query` (required): A specific search query with relevant keywords
- `num_results` (optional): Number of results (1-10, default 5)

## Tips

- Be specific with search queries -- include relevant keywords, dates, and context
- For prices, include the current date in your query for better results
- The tool returns both search snippets and full page content from top results
- Quote specific data and sources from the results in your response
