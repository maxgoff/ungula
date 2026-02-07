"""
Tests for the url_fetch tool.

Covers GET/POST, SSRF protection, scheme validation, HTML stripping,
response truncation, timeouts, and HTTP error codes.
"""

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock missing third-party LLM provider SDKs before importing tools.
# ---------------------------------------------------------------------------

_MOCK_MODULES = ["anthropic", "openai"]
_MOCK_GOOGLE_SUBS = ["google.generativeai", "google.genai", "google.genai.types"]

for _mod in _MOCK_MODULES:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

if "google" not in sys.modules:
    _google_mock = types.ModuleType("google")
    _google_mock.__path__ = []  # type: ignore[attr-defined]
    sys.modules["google"] = _google_mock

for _sub in _MOCK_GOOGLE_SUBS:
    if _sub not in sys.modules:
        sys.modules[_sub] = MagicMock()


from ungula.skills.builtin.url_fetch.tool import (
    UrlFetchTool,
    _is_private_ip,
    _strip_html,
)


# ---------------------------------------------------------------------------
# Helper: mock httpx response
# ---------------------------------------------------------------------------


def _mock_response(
    status_code: int = 200,
    text: str = "OK",
    content_type: str = "text/plain",
    url: str = "https://example.com",
):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.headers = {"content-type": content_type}
    resp.url = url
    resp.raise_for_status = MagicMock()
    return resp


def _mock_error_response(status_code: int, reason: str = "Not Found"):
    import httpx

    resp = MagicMock()
    resp.status_code = status_code
    resp.reason_phrase = reason
    resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=resp,
        )
    )
    return resp


# ---------------------------------------------------------------------------
# _is_private_ip tests
# ---------------------------------------------------------------------------


class TestIsPrivateIp:
    def test_localhost_is_private(self):
        assert _is_private_ip("127.0.0.1") is True

    def test_localhost_hostname(self):
        assert _is_private_ip("localhost") is True

    @patch("ungula.skills.builtin.url_fetch.tool.socket.getaddrinfo")
    def test_private_10_range(self, mock_getaddr):
        mock_getaddr.return_value = [
            (2, 1, 6, "", ("10.0.0.1", 0)),
        ]
        assert _is_private_ip("internal.example.com") is True

    @patch("ungula.skills.builtin.url_fetch.tool.socket.getaddrinfo")
    def test_private_192_168_range(self, mock_getaddr):
        mock_getaddr.return_value = [
            (2, 1, 6, "", ("192.168.1.1", 0)),
        ]
        assert _is_private_ip("router.local") is True

    @patch("ungula.skills.builtin.url_fetch.tool.socket.getaddrinfo")
    def test_private_172_16_range(self, mock_getaddr):
        mock_getaddr.return_value = [
            (2, 1, 6, "", ("172.16.0.1", 0)),
        ]
        assert _is_private_ip("internal.example.com") is True

    @patch("ungula.skills.builtin.url_fetch.tool.socket.getaddrinfo")
    def test_public_ip_is_not_private(self, mock_getaddr):
        mock_getaddr.return_value = [
            (2, 1, 6, "", ("93.184.216.34", 0)),
        ]
        assert _is_private_ip("example.com") is False

    @patch("ungula.skills.builtin.url_fetch.tool.socket.getaddrinfo")
    def test_dns_failure_returns_false(self, mock_getaddr):
        import socket
        mock_getaddr.side_effect = socket.gaierror("Name resolution failed")
        assert _is_private_ip("nonexistent.invalid") is False


# ---------------------------------------------------------------------------
# _strip_html tests
# ---------------------------------------------------------------------------


class TestStripHtml:
    def test_strips_tags(self):
        assert _strip_html("<p>Hello</p>") == "Hello"

    def test_normalizes_whitespace(self):
        assert _strip_html("<p>Hello</p>  <p>World</p>") == "Hello World"

    def test_no_tags(self):
        assert _strip_html("plain text") == "plain text"

    def test_nested_tags(self):
        result = _strip_html("<div><span>nested</span></div>")
        assert "nested" in result

    def test_empty_string(self):
        assert _strip_html("") == ""


# ---------------------------------------------------------------------------
# UrlFetchTool tests
# ---------------------------------------------------------------------------


@pytest.fixture
def tool():
    return UrlFetchTool()


class TestUrlFetchSchemeValidation:
    async def test_rejects_ftp_scheme(self, tool):
        result = await tool.execute(url="ftp://example.com/file.txt")
        assert result.success is False
        assert "Unsupported URL scheme" in result.error

    async def test_rejects_file_scheme(self, tool):
        result = await tool.execute(url="file:///etc/passwd")
        assert result.success is False
        assert "Unsupported URL scheme" in result.error

    async def test_rejects_empty_scheme(self, tool):
        result = await tool.execute(url="://example.com")
        assert result.success is False


class TestUrlFetchHostnameValidation:
    async def test_rejects_missing_hostname(self, tool):
        result = await tool.execute(url="http://")
        assert result.success is False
        assert "no hostname" in result.error.lower()


class TestUrlFetchSSRF:
    @patch("ungula.skills.builtin.url_fetch.tool._is_private_ip", return_value=True)
    async def test_blocks_private_ip(self, mock_ip, tool):
        result = await tool.execute(url="http://192.168.1.1/admin")
        assert result.success is False
        assert "private" in result.error.lower() or "Blocked" in result.error


class TestUrlFetchGET:
    @patch("ungula.skills.builtin.url_fetch.tool._is_private_ip", return_value=False)
    @patch("httpx.AsyncClient")
    async def test_successful_get(self, mock_client_class, mock_ip, tool):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_response(text="Hello World"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_class.return_value = mock_client

        result = await tool.execute(url="https://example.com")
        assert result.success is True
        assert "Hello World" in result.output
        assert result.data["status_code"] == 200

    @patch("ungula.skills.builtin.url_fetch.tool._is_private_ip", return_value=False)
    @patch("httpx.AsyncClient")
    async def test_html_stripping(self, mock_client_class, mock_ip, tool):
        html = "<html><body><p>Hello</p></body></html>"
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            return_value=_mock_response(text=html, content_type="text/html; charset=utf-8")
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_class.return_value = mock_client

        result = await tool.execute(url="https://example.com")
        assert result.success is True
        assert "<p>" not in result.output
        assert "Hello" in result.output

    @patch("ungula.skills.builtin.url_fetch.tool._is_private_ip", return_value=False)
    @patch("httpx.AsyncClient")
    async def test_response_truncation(self, mock_client_class, mock_ip, tool):
        long_text = "x" * 10000
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_response(text=long_text))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_class.return_value = mock_client

        result = await tool.execute(url="https://example.com", max_length=500)
        assert result.success is True
        assert len(result.output) < 10000
        assert "Truncated" in result.output


class TestUrlFetchPOST:
    @patch("ungula.skills.builtin.url_fetch.tool._is_private_ip", return_value=False)
    @patch("httpx.AsyncClient")
    async def test_successful_post(self, mock_client_class, mock_ip, tool):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=_mock_response(text='{"ok": true}'))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_class.return_value = mock_client

        result = await tool.execute(
            url="https://api.example.com/data",
            method="POST",
            body='{"key": "value"}',
        )
        assert result.success is True
        assert '{"ok": true}' in result.output
        mock_client.post.assert_called_once()


class TestUrlFetchErrors:
    @patch("ungula.skills.builtin.url_fetch.tool._is_private_ip", return_value=False)
    @patch("httpx.AsyncClient")
    async def test_timeout(self, mock_client_class, mock_ip, tool):
        import httpx

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_class.return_value = mock_client

        result = await tool.execute(url="https://slow.example.com")
        assert result.success is False
        assert "timed out" in result.error.lower()

    @patch("ungula.skills.builtin.url_fetch.tool._is_private_ip", return_value=False)
    @patch("httpx.AsyncClient")
    async def test_http_404(self, mock_client_class, mock_ip, tool):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_error_response(404, "Not Found"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_class.return_value = mock_client

        result = await tool.execute(url="https://example.com/missing")
        assert result.success is False
        assert "404" in result.error

    @patch("ungula.skills.builtin.url_fetch.tool._is_private_ip", return_value=False)
    @patch("httpx.AsyncClient")
    async def test_http_500(self, mock_client_class, mock_ip, tool):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            return_value=_mock_error_response(500, "Internal Server Error")
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_class.return_value = mock_client

        result = await tool.execute(url="https://example.com/error")
        assert result.success is False
        assert "500" in result.error

    async def test_unsupported_method(self, tool):
        result = await tool.execute(url="https://example.com", method="DELETE")
        # DELETE is not in valid enum, but url validation happens first for some URLs
        # The tool normalizes then checks method
        # For a valid URL with a public IP, method check should happen
        # We need to mock _is_private_ip to get past SSRF check
        pass

    @patch("ungula.skills.builtin.url_fetch.tool._is_private_ip", return_value=False)
    async def test_unsupported_method_with_valid_url(self, mock_ip, tool):
        result = await tool.execute(url="https://example.com", method="DELETE")
        assert result.success is False
        assert "Unsupported method" in result.error
