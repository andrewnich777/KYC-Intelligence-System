"""Tests for the screening list tool.

Note: These tests use the Trade.gov CSL API and may be skipped
if network is unavailable.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestScreeningListTool:
    def test_import(self):
        from tools.screening_list import search_screening_list
        assert callable(search_screening_list)

    def test_tool_definitions_include_screening(self):
        from tools.tool_definitions import TOOL_DEFINITIONS
        assert "screening_list_lookup" in TOOL_DEFINITIONS

    def test_tool_handler_registered(self):
        from tools.tool_definitions import TOOL_HANDLERS
        assert "screening_list_lookup" in TOOL_HANDLERS

    @pytest.mark.skipif(
        os.environ.get("SKIP_NETWORK_TESTS", "").lower() not in ("false", "0", ""),
        reason="Network tests disabled"
    )
    def test_search_common_name(self):
        """Test searching for a name — async function, just verify it's callable."""
        import asyncio

        from tools.screening_list import search_screening_list
        # search_screening_list is async, just verify it returns a coroutine
        coro = search_screening_list("Test Name XYZ123")
        assert asyncio.iscoroutine(coro)
        coro.close()  # Clean up

    def test_fuzzy_matching_import(self):
        """Test that fuzzy matching logic is available."""
        from tools.screening_list import _simple_name_similarity
        score = _simple_name_similarity("John Smith", "Jon Smith")
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_similarity_identical_names(self):
        from tools.screening_list import _simple_name_similarity
        score = _simple_name_similarity("Viktor Petrov", "Viktor Petrov")
        assert score == 1.0

    def test_similarity_different_names(self):
        from tools.screening_list import _simple_name_similarity
        score = _simple_name_similarity("John Smith", "Maria Garcia")
        assert score < 0.5
