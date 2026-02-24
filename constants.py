"""
Centralized constants for the KYC Client Onboarding Intelligence System.

Replaces magic numbers scattered across 10+ files with named constants.
"""

# =============================================================================
# Risk Tier Thresholds
# =============================================================================
RISK_TIER_LOW_MAX = 15
RISK_TIER_MEDIUM_MAX = 35
RISK_TIER_HIGH_MAX = 60

# =============================================================================
# UBO Risk Contribution Weights (used in risk_assessment_brief, risk_scoring)
# =============================================================================
UBO_SANCTIONS_RISK_POINTS = 30
UBO_PEP_RISK_POINTS = 25
UBO_ADVERSE_MEDIA_RISK_POINTS = 15

# =============================================================================
# Ownership Thresholds
# =============================================================================
UBO_COMPLEX_OWNERSHIP_THRESHOLD = 5
UBO_OWNERSHIP_COVERAGE_CONCERN = 75

# =============================================================================
# Transaction Anomaly Ratios
# =============================================================================
WEALTH_INCOME_RATIO_VERY_HIGH = 50
WEALTH_INCOME_RATIO_ELEVATED = 20
DEPOSIT_INCOME_RATIO_SUSPICIOUS = 10
TRANSACTION_REVENUE_RATIO_HIGH = 10
TRANSACTION_REVENUE_RATIO_ELEVATED = 5

# =============================================================================
# Cache TTLs (seconds)
# =============================================================================
FETCH_CACHE_TTL_SECONDS = 3600       # 1 hour
CSL_CACHE_TTL_SECONDS = 86400        # 24 hours
FETCH_CACHE_MAX_SIZE = 500           # max entries in fetch cache

# =============================================================================
# HTTP Client Timeouts (seconds)
# =============================================================================
HTTP_CONNECT_TIMEOUT = 5.0        # Fail-fast on dead/unreachable sites
HTTP_READ_TIMEOUT = 25.0          # Generous for slow government sites
HTTP_WRITE_TIMEOUT = 10.0
HTTP_POOL_TIMEOUT = 5.0
CSL_API_READ_TIMEOUT = 10.0       # API should respond faster than web pages

# =============================================================================
# Confidence Grade Thresholds (percentage of V+S evidence)
# =============================================================================
CONFIDENCE_GRADE_A_THRESHOLD = 70
CONFIDENCE_GRADE_B_THRESHOLD = 50
CONFIDENCE_GRADE_C_THRESHOLD = 30
CONFIDENCE_GRADE_D_THRESHOLD = 15

# Weight factor for VERIFIED records when computing confidence grade.
# V records count 1.5x in the strong_pct calculation, rewarding
# investigations that achieve actual government-source verification.
VERIFIED_WEIGHT_FACTOR = 1.5

# =============================================================================
# EDD Risk Score Threshold
# =============================================================================
EDD_RISK_SCORE_THRESHOLD = 36

# =============================================================================
# Cash Reporting Thresholds (CAD)
# =============================================================================
LARGE_CASH_TRANSACTION_THRESHOLD = 10_000

# =============================================================================
# Virtual Currency & EFT Reporting Thresholds (CAD)
# =============================================================================
LARGE_VIRTUAL_CURRENCY_THRESHOLD = 10_000
LARGE_EFT_THRESHOLD = 10_000

# =============================================================================
# Suitability Thresholds
# =============================================================================
SUITABILITY_HIGH_INCOME_THRESHOLD = 200_000
SUITABILITY_LOW_INCOME_THRESHOLD = 50_000
SUITABILITY_LOW_NET_WORTH_THRESHOLD = 50_000
SUITABILITY_LEVERAGE_NET_WORTH_MIN = 100_000
SUITABILITY_DEPOSIT_INCOME_RATIO_HIGH = 5
SUITABILITY_DEPOSIT_INCOME_RATIO_ELEVATED = 2
SUITABILITY_BIZ_LEVERAGE_REVENUE_MIN = 500_000
SUITABILITY_BIZ_VOLUME_REVENUE_CONCERN = 5
SUITABILITY_BIZ_VOLUME_REVENUE_ELEVATED = 2

# =============================================================================
# Shared Term Sets (US/Canada country name variations)
# =============================================================================
US_TERMS = frozenset({
    "united states", "us", "usa", "u.s.", "u.s.a.", "america",
})

CANADA_TERMS = frozenset({
    "canada", "ca",
})

# =============================================================================
# UBO Risk Contribution Factor
# =============================================================================
# Factor applied to highest-risk UBO score when computing entity risk.
# PCMLTFA requires entity risk to reflect beneficial owner risk.
# 0.75 accounts for legitimate corporate insulation while maintaining
# regulatory compliance. Configurable via risk_config.yaml.
UBO_RISK_CONTRIBUTION_FACTOR = 0.75

# =============================================================================
# PEP Decay — Residual risk points after EDD expiry
# =============================================================================
PEP_EXPIRED_RESIDUAL_POINTS = 5

# =============================================================================
# API Rate Limits (Tier 3 baseline: 2,000 RPM / 800K ITPM / 160K OTPM per model family)
# =============================================================================

# Per-model-family concurrent API call limits.
# Sonnet and Opus have independent rate limit pools — separate semaphores
# prevent Sonnet research agents from blocking Opus synthesis/review.
API_CONCURRENCY_BY_FAMILY = {
    "sonnet": 5,   # 5 in-flight allows good parallelism without burst spikes
    "opus": 2,     # synthesis + review never overlap, but safe headroom
    "haiku": 3,    # not currently used, sensible default
    "default": 3,
}

# Retry on 429 (RateLimitError)
RATE_LIMIT_MAX_RETRIES = 10
RATE_LIMIT_DEFAULT_WAIT = 30          # seconds (Tier 3 bucket refills faster than low tiers)
RATE_LIMIT_RECOVERY_BUFFER = 10       # seconds after recovery (less conservative at Tier 3)

# Proactive backpressure — slow down before hitting 429
RATE_LIMIT_BACKPRESSURE_THRESHOLD_RPM = 100      # start slowing at 100 RPM remaining
RATE_LIMIT_BACKPRESSURE_THRESHOLD_ITPM = 100_000  # start slowing at 100K ITPM remaining
RATE_LIMIT_BACKPRESSURE_DELAY = 2.0               # seconds to pause

# Retry on transient errors (timeout, connection, 5xx)
TRANSIENT_MAX_RETRIES = 3
TRANSIENT_BASE_WAIT = 5
TRANSIENT_MAX_WAIT = 60

# =============================================================================
# Synthesis Token Budget
# =============================================================================
SYNTHESIS_MIN_TOKENS = 16384        # Floor — complex cases need room for decision points
SYNTHESIS_MAX_TOKENS = 65536        # Ceiling — prevents exceeding model context on large stores
SYNTHESIS_TOKENS_PER_RECORD = 512   # Scale with evidence store size

# =============================================================================
# Agent Gather Timeout (seconds)
# =============================================================================
AGENT_GATHER_TIMEOUT = 600          # 10 minutes — prevents indefinite hangs on network issues

# =============================================================================
# Failed Agent Sentinel Key
# =============================================================================
FAILED_SENTINEL_KEY = "_failed"     # Constant for the sentinel key used in UBO screening dicts

# =============================================================================
# Evidence Store Soft Cap
# =============================================================================
EVIDENCE_STORE_WARN_THRESHOLD = 500  # Warn when evidence store exceeds this count

# =============================================================================
# EU High-Risk Third Countries — risk points
# =============================================================================
EU_HIGH_RISK_THIRD_COUNTRY_POINTS = 10

# =============================================================================
# Risk Amplification — bonus points for compounding factor combinations
# =============================================================================
AMPLIFICATION_YOUNG_OFFSHORE_COMPLEX = 15     # <1yr + offshore + complex ownership
AMPLIFICATION_MULTI_FATF_CONNECTIONS = 10      # >=2 distinct FATF grey/black hits
AMPLIFICATION_PEP_HIGH_RISK_JURISDICTION = 10  # PEP + high-risk jurisdiction

# =============================================================================
# Screening List Thresholds
# =============================================================================
SCREENING_HIGH_CONFIDENCE = 0.95
SCREENING_CACHE_STALENESS_HOURS = 24
