"""
URL Fetch Tool.

Fetches content from URLs with SSRF protection against private IPs.
"""

import ipaddress
import logging
import re
import socket
from urllib.parse import urlparse

import httpx

from ungula.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)

# Private/reserved IP ranges to block (SSRF protection)
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _is_private_ip(hostname: str) -> bool:
    """Check if a hostname resolves to a private/reserved IP address."""
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
        for family, _, _, _, sockaddr in addr_infos:
            ip = ipaddress.ip_address(sockaddr[0])
            for network in _BLOCKED_NETWORKS:
                if ip in network:
                    return True
    except (socket.gaierror, ValueError):
        # If we can't resolve, allow (will fail on connect anyway)
        return False
    return False


def _strip_html(html: str) -> str:
    """Strip HTML tags and normalize whitespace."""
    text = _HTML_TAG_RE.sub(" ", html)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


class UrlFetchTool(Tool):
    """Fetch content from a URL."""

    name = "url_fetch"
    description = "Fetch content from a URL. Supports GET and POST methods."
    cacheable = True
    cache_ttl = 120
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch",
            },
            "method": {
                "type": "string",
                "enum": ["GET", "POST"],
                "description": "HTTP method (default: GET)",
            },
            "headers": {
                "type": "object",
                "description": "HTTP headers to send",
                "additionalProperties": {"type": "string"},
            },
            "body": {
                "type": "string",
                "description": "Request body for POST requests",
            },
            "max_length": {
                "type": "integer",
                "description": "Max response length in characters (default: 8000)",
            },
        },
        "required": ["url"],
    }

    async def execute(
        self,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: str | None = None,
        max_length: int = 8000,
        **kwargs,
    ) -> ToolResult:
        """Fetch content from a URL."""
        # Validate scheme
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return ToolResult(
                success=False,
                output="",
                error=f"Unsupported URL scheme: {parsed.scheme}. Only http and https are allowed.",
            )

        # SSRF protection: block private IPs
        hostname = parsed.hostname
        if not hostname:
            return ToolResult(success=False, output="", error="Invalid URL: no hostname")

        if _is_private_ip(hostname):
            return ToolResult(
                success=False,
                output="",
                error="Blocked: URL resolves to a private/reserved IP address.",
            )

        # Validate method
        method = method.upper()
        if method not in ("GET", "POST"):
            return ToolResult(
                success=False, output="", error=f"Unsupported method: {method}"
            )

        # Clamp max_length
        max_length = min(max(max_length, 100), 100_000)

        try:
            async with httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
                max_redirects=5,
            ) as client:
                if method == "POST":
                    resp = await client.post(
                        url, headers=headers, content=body
                    )
                else:
                    resp = await client.get(url, headers=headers)

                resp.raise_for_status()

                content_type = resp.headers.get("content-type", "")
                text = resp.text

                # Strip HTML tags for text/html responses
                if "text/html" in content_type:
                    text = _strip_html(text)

                # Truncate
                if len(text) > max_length:
                    text = text[:max_length] + f"\n\n[Truncated at {max_length} characters]"

                return ToolResult(
                    success=True,
                    output=text,
                    metadata={
                        "status_code": resp.status_code,
                        "content_type": content_type,
                        "url": str(resp.url),
                    },
                )

        except httpx.TimeoutException:
            return ToolResult(
                success=False, output="", error=f"Request timed out after 15 seconds: {url}"
            )
        except httpx.HTTPStatusError as e:
            return ToolResult(
                success=False,
                output="",
                error=f"HTTP {e.response.status_code}: {e.response.reason_phrase}",
            )
        except Exception as e:
            return ToolResult(
                success=False, output="", error=f"Fetch failed: {e}"
            )
