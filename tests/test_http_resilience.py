"""
Tests for HTTP resilience: shared client, timeouts, browser UA, CSL redirect detection.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

# ---------------------------------------------------------------------------
# Shared client lifecycle
# ---------------------------------------------------------------------------


class TestSharedClient:
    """Tests for the shared HTTP client in tool_definitions."""

    def test_lazy_init(self):
        """_get_shared_client() returns a live client."""
        from tools.tool_definitions import _get_shared_client
        client = _get_shared_client()
        assert client is not None
        assert not client.is_closed

    def test_reuse(self):
        """Repeated calls return the same client instance."""
        from tools.tool_definitions import _get_shared_client
        c1 = _get_shared_client()
        c2 = _get_shared_client()
        assert c1 is c2

    def test_recreation_after_close(self):
        """After close, _get_shared_client() creates a new client."""
        from tools.tool_definitions import _get_shared_client, close_shared_client
        c1 = _get_shared_client()
        asyncio.run(close_shared_client())
        c2 = _get_shared_client()
        assert c2 is not c1
        assert not c2.is_closed

    def test_idempotent_close(self):
        """Calling close_shared_client() multiple times does not raise."""
        from tools.tool_definitions import close_shared_client

        async def _double_close():
            await close_shared_client()
            await close_shared_client()

        asyncio.run(_double_close())

    def test_close_when_none(self):
        """close_shared_client() is safe when no client was ever created."""
        import tools.tool_definitions as td
        td._shared_client = None
        asyncio.run(td.close_shared_client())  # Should not raise


# ---------------------------------------------------------------------------
# Timeout structure
# ---------------------------------------------------------------------------


class TestTimeoutStructure:
    """Verify the shared timeout has correct granular values."""

    def test_connect_timeout(self):
        from tools.tool_definitions import _WEB_FETCH_TIMEOUT
        assert _WEB_FETCH_TIMEOUT.connect == 5.0

    def test_read_timeout(self):
        from tools.tool_definitions import _WEB_FETCH_TIMEOUT
        assert _WEB_FETCH_TIMEOUT.read == 25.0

    def test_write_timeout(self):
        from tools.tool_definitions import _WEB_FETCH_TIMEOUT
        assert _WEB_FETCH_TIMEOUT.write == 10.0

    def test_pool_timeout(self):
        from tools.tool_definitions import _WEB_FETCH_TIMEOUT
        assert _WEB_FETCH_TIMEOUT.pool == 5.0


# ---------------------------------------------------------------------------
# User-Agent
# ---------------------------------------------------------------------------


class TestUserAgent:
    """Verify the shared headers use a browser-like UA."""

    def test_ua_contains_mozilla(self):
        from tools.tool_definitions import _WEB_FETCH_HEADERS
        assert "Mozilla" in _WEB_FETCH_HEADERS["User-Agent"]

    def test_ua_does_not_contain_kyc(self):
        from tools.tool_definitions import _WEB_FETCH_HEADERS
        assert "KYC" not in _WEB_FETCH_HEADERS["User-Agent"]

    def test_accept_header_present(self):
        from tools.tool_definitions import _WEB_FETCH_HEADERS
        assert "Accept" in _WEB_FETCH_HEADERS


# ---------------------------------------------------------------------------
# CSL API redirect detection
# ---------------------------------------------------------------------------


class TestCSLRedirectDetection:
    """Tests for _search_csl_api handling dead API via redirect."""

    def test_redirect_returns_empty(self):
        """301 redirect should return [] immediately, not follow."""
        mock_response = MagicMock()
        mock_response.status_code = 301
        mock_response.headers = {"location": "https://www.trade.gov/"}

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            from tools.screening_list import _search_csl_api
            results = asyncio.run(_search_csl_api("test name"))
            assert results == []

    def test_html_content_type_returns_empty(self):
        """Response with text/html content-type should return [] (not parse as JSON)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html; charset=utf-8"}

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            from tools.screening_list import _search_csl_api
            results = asyncio.run(_search_csl_api("test name"))
            assert results == []

    def test_connect_timeout_returns_empty(self):
        """ConnectTimeout should return [] gracefully."""
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=httpx.ConnectTimeout("timed out"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            from tools.screening_list import _search_csl_api
            results = asyncio.run(_search_csl_api("test name"))
            assert results == []


# ---------------------------------------------------------------------------
# search_screening_list data_source tracking
# ---------------------------------------------------------------------------


class TestScreeningListDataSource:
    """Test that data_source is set correctly when API is dead."""

    def test_data_source_api_no_results_on_empty_api(self):
        """When API returns [] for all variants, data_source should be api_no_results."""
        with patch("tools.screening_list._search_csl_api", new_callable=AsyncMock, return_value=[]):
            with patch("tools.screening_list._fuzzy_search_local", return_value=([], None)):
                from tools.screening_list import search_screening_list
                result = asyncio.run(search_screening_list("John Doe"))
                assert result["data_source"] == "api_no_results"

    def test_data_source_api_when_results_found(self):
        """When API returns results, data_source should remain 'api'."""
        api_match = [{"matched_name": "John Doe", "score": 0.95, "list_name": "SDN"}]
        with patch("tools.screening_list._search_csl_api", new_callable=AsyncMock, return_value=api_match):
            with patch("tools.screening_list._fuzzy_search_local", return_value=([], None)):
                from tools.screening_list import search_screening_list
                result = asyncio.run(search_screening_list("John Doe"))
                assert result["data_source"] == "api"


# ---------------------------------------------------------------------------
# Web fetch timeout error messages
# ---------------------------------------------------------------------------


class TestWebFetchTimeoutMessages:
    """Verify connect vs read timeout produce distinct error messages."""

    def test_connect_timeout_message(self):
        """ConnectTimeout should mention 'site may be down'."""
        from tools.tool_definitions import _get_shared_client, handle_web_fetch

        with patch.object(_get_shared_client(), "get", side_effect=httpx.ConnectTimeout("connect failed")):
            result = asyncio.run(handle_web_fetch("https://example.com"))
            assert not result["success"]
            assert "site may be down" in result["error"]

    def test_read_timeout_message(self):
        """ReadTimeout should mention 'too slow'."""
        from tools.tool_definitions import _get_shared_client, handle_web_fetch

        with patch.object(_get_shared_client(), "get", side_effect=httpx.ReadTimeout("read failed")):
            result = asyncio.run(handle_web_fetch("https://example.com"))
            assert not result["success"]
            assert "too slow" in result["error"]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestHTTPConstants:
    """Verify HTTP timeout constants exist and have expected values."""

    def test_constants_exist(self):
        from constants import (
            CSL_API_READ_TIMEOUT,
            HTTP_CONNECT_TIMEOUT,
            HTTP_POOL_TIMEOUT,
            HTTP_READ_TIMEOUT,
            HTTP_WRITE_TIMEOUT,
        )
        assert HTTP_CONNECT_TIMEOUT == 5.0
        assert HTTP_READ_TIMEOUT == 25.0
        assert HTTP_WRITE_TIMEOUT == 10.0
        assert HTTP_POOL_TIMEOUT == 5.0
        assert CSL_API_READ_TIMEOUT == 10.0

    def test_connect_less_than_read(self):
        """Connect timeout should be much shorter than read timeout."""
        from constants import HTTP_CONNECT_TIMEOUT, HTTP_READ_TIMEOUT
        assert HTTP_CONNECT_TIMEOUT < HTTP_READ_TIMEOUT
