"""Pytest configuration and fixtures for KYC system tests."""

import json
import os
import sys

import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def reset_config():
    """Reset configuration before each test."""
    import config
    config._config = None
    yield
    config._config = None


@pytest.fixture
def case1_individual_low():
    """Load Case 1: Sarah Thompson — LOW risk individual."""
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "test_cases", "case1_individual_low.json"
    )
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def case2_individual_pep():
    """Load Case 2: Maria Chen-Dubois — HIGH risk PEP individual."""
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "test_cases", "case2_individual_pep.json"
    )
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def case3_business_critical():
    """Load Case 3: Northern Maple Trading Corp — CRITICAL risk business."""
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "test_cases", "case3_business_critical.json"
    )
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def individual_client_low(case1_individual_low):
    """Create IndividualClient from Case 1."""
    from models import IndividualClient
    return IndividualClient(**case1_individual_low)


@pytest.fixture
def individual_client_pep(case2_individual_pep):
    """Create IndividualClient from Case 2."""
    from models import IndividualClient
    return IndividualClient(**case2_individual_pep)


@pytest.fixture
def business_client_critical(case3_business_critical):
    """Create BusinessClient from Case 3."""
    from models import BusinessClient
    return BusinessClient(**case3_business_critical)
