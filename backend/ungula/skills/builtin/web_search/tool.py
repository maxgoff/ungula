"""
Web Search Tool using Brave Search API with Tavily fallback.

Re-exports the WebSearchTool from the tools package for use as a skill.
"""

from ungula.tools.web_search import BraveSearchConfig, TavilySearchConfig, WebSearchTool

__all__ = ["WebSearchTool", "BraveSearchConfig", "TavilySearchConfig"]
