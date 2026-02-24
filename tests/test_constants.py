"""Tests for centralized constants."""



class TestRiskTierThresholds:
    """Verify risk tier boundary constants are consistent."""

    def test_imports(self):
        from constants import (
            RISK_TIER_HIGH_MAX,
            RISK_TIER_LOW_MAX,
            RISK_TIER_MEDIUM_MAX,
        )
        assert isinstance(RISK_TIER_LOW_MAX, int)
        assert isinstance(RISK_TIER_MEDIUM_MAX, int)
        assert isinstance(RISK_TIER_HIGH_MAX, int)

    def test_tier_boundaries_ascending(self):
        from constants import (
            RISK_TIER_HIGH_MAX,
            RISK_TIER_LOW_MAX,
            RISK_TIER_MEDIUM_MAX,
        )
        assert RISK_TIER_LOW_MAX < RISK_TIER_MEDIUM_MAX
        assert RISK_TIER_MEDIUM_MAX < RISK_TIER_HIGH_MAX

    def test_tier_boundaries_positive(self):
        from constants import (
            RISK_TIER_HIGH_MAX,
            RISK_TIER_LOW_MAX,
        )
        assert RISK_TIER_LOW_MAX > 0
        assert RISK_TIER_HIGH_MAX <= 100


class TestUBOConstants:
    """Verify UBO risk weights and ownership thresholds."""

    def test_ubo_risk_points(self):
        from constants import (
            UBO_ADVERSE_MEDIA_RISK_POINTS,
            UBO_PEP_RISK_POINTS,
            UBO_SANCTIONS_RISK_POINTS,
        )
        assert UBO_SANCTIONS_RISK_POINTS > 0
        assert UBO_PEP_RISK_POINTS > 0
        assert UBO_ADVERSE_MEDIA_RISK_POINTS > 0
        # Sanctions should be highest risk
        assert UBO_SANCTIONS_RISK_POINTS >= UBO_PEP_RISK_POINTS
        assert UBO_PEP_RISK_POINTS >= UBO_ADVERSE_MEDIA_RISK_POINTS

    def test_ownership_thresholds(self):
        from constants import (
            UBO_COMPLEX_OWNERSHIP_THRESHOLD,
            UBO_OWNERSHIP_COVERAGE_CONCERN,
        )
        assert UBO_COMPLEX_OWNERSHIP_THRESHOLD > 0
        assert 0 < UBO_OWNERSHIP_COVERAGE_CONCERN <= 100


class TestTransactionRatios:
    """Verify transaction anomaly ratio constants."""

    def test_ratios_ascending(self):
        from constants import (
            TRANSACTION_REVENUE_RATIO_ELEVATED,
            TRANSACTION_REVENUE_RATIO_HIGH,
        )
        assert TRANSACTION_REVENUE_RATIO_ELEVATED < TRANSACTION_REVENUE_RATIO_HIGH

    def test_wealth_ratios_ascending(self):
        from constants import (
            WEALTH_INCOME_RATIO_ELEVATED,
            WEALTH_INCOME_RATIO_VERY_HIGH,
        )
        assert WEALTH_INCOME_RATIO_ELEVATED < WEALTH_INCOME_RATIO_VERY_HIGH


class TestTermSets:
    """Verify shared term sets."""

    def test_us_terms_is_frozenset(self):
        from constants import US_TERMS
        assert isinstance(US_TERMS, frozenset)

    def test_us_terms_contains_common_variants(self):
        from constants import US_TERMS
        assert "united states" in US_TERMS
        assert "us" in US_TERMS
        assert "usa" in US_TERMS

    def test_canada_terms_is_frozenset(self):
        from constants import CANADA_TERMS
        assert isinstance(CANADA_TERMS, frozenset)

    def test_canada_terms_contains_common_variants(self):
        from constants import CANADA_TERMS
        assert "canada" in CANADA_TERMS
        assert "ca" in CANADA_TERMS


class TestCacheConstants:
    """Verify cache configuration constants."""

    def test_cache_ttls_positive(self):
        from constants import CSL_CACHE_TTL_SECONDS, FETCH_CACHE_TTL_SECONDS
        assert FETCH_CACHE_TTL_SECONDS > 0
        assert CSL_CACHE_TTL_SECONDS > 0

    def test_cache_max_size_positive(self):
        from constants import FETCH_CACHE_MAX_SIZE
        assert FETCH_CACHE_MAX_SIZE > 0


class TestConfidenceGrades:
    """Verify confidence grade thresholds are descending."""

    def test_grades_descending(self):
        from constants import (
            CONFIDENCE_GRADE_A_THRESHOLD,
            CONFIDENCE_GRADE_B_THRESHOLD,
            CONFIDENCE_GRADE_C_THRESHOLD,
            CONFIDENCE_GRADE_D_THRESHOLD,
        )
        assert CONFIDENCE_GRADE_A_THRESHOLD > CONFIDENCE_GRADE_B_THRESHOLD
        assert CONFIDENCE_GRADE_B_THRESHOLD > CONFIDENCE_GRADE_C_THRESHOLD
        assert CONFIDENCE_GRADE_C_THRESHOLD > CONFIDENCE_GRADE_D_THRESHOLD
        assert CONFIDENCE_GRADE_D_THRESHOLD > 0
