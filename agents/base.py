"""
Base agent class for Claude API interactions with tool use.
"""

import asyncio
import json
import os
import random
import time
from abc import ABC, abstractmethod
from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from models import DispositionStatus

import anthropic

from config import get_config, get_model_for_agent, get_tool_limit_for_agent
from constants import (
    API_CONCURRENCY_BY_FAMILY,
    RATE_LIMIT_BACKPRESSURE_DELAY,
    RATE_LIMIT_BACKPRESSURE_THRESHOLD_ITPM,
    RATE_LIMIT_BACKPRESSURE_THRESHOLD_RPM,
    RATE_LIMIT_DEFAULT_WAIT,
    RATE_LIMIT_MAX_RETRIES,
    RATE_LIMIT_RECOVERY_BUFFER,
    TRANSIENT_BASE_WAIT,
    TRANSIENT_MAX_RETRIES,
    TRANSIENT_MAX_WAIT,
)
from logger import get_logger
from tools.tool_definitions import execute_tool, get_tools_for_agent

# Module logger
logger = get_logger(__name__)


# =============================================================================
# Shared Prompt Sections - Reduce token usage by standardizing common instructions
# =============================================================================

KYC_EVIDENCE_RULES = """## Evidence Classification (V/S/I/U)
All findings MUST include evidence classification:
- [V] Verified: URL + direct quote from Tier 0/1 source (government registry, official sanctions list, regulatory database)
- [S] Sourced: URL + excerpt from Tier 1/2 source (major news, corporate filings)
- [I] Inferred: Derived from multiple signals (explain reasoning chain)
- [U] Unknown: Searched but information not found

## Source Tier Taxonomy
- TIER_0 (Government/Court): Government registries, official sanctions lists, court filings, regulatory enforcement databases
- TIER_1 (Major/Authoritative): Reuters, AP, Bloomberg, ICIJ, OCCRP, Financial Times, WSJ, NYT, BBC, official corporate filings, OFAC SDN, OpenSanctions, ICIJ Offshore Leaks
- TIER_2 (Regional/Trade): Regional newspapers, trade publications, industry journals, local business registries
- TIER_3 (Low-Reliability): Blogs, social media, forums, unverified aggregators, self-published content — cap at SOURCED (never VERIFIED); without URL = INFERRED

Every claim must have a disposition:
- CLEAR: No match or concern found after thorough search
- POTENTIAL_MATCH: Possible match requiring human review (include similarity score)
- CONFIRMED_MATCH: Definitive match with strong evidence
- FALSE_POSITIVE: Initial match determined to be different entity (explain why)
- PENDING_REVIEW: Cannot determine — requires human judgment"""

KYC_OUTPUT_RULES = """## Output Format
Return findings as valid JSON in a ```json code block. Ensure all strings are properly escaped.
Include evidence_records array with each finding linked to sources."""

KYC_FALSE_POSITIVE_RULES = """## False Positive Analysis
When screening returns a potential match:
1. Compare full name, date of birth, citizenship, and any other identifiers
2. Check for common name disambiguation (different person with same name)
3. Score confidence: >0.95 = POTENTIAL_MATCH, 0.70-0.95 = investigate secondary identifiers, <0.70 = likely CLEAR
4. Document your reasoning for every disposition decision
5. When in doubt, flag as PENDING_REVIEW for human decision"""

KYC_REGULATORY_CONTEXT = """## Canadian Regulatory Context
This screening supports compliance with:
- FINTRAC (Financial Transactions and Reports Analysis Centre of Canada) — PCMLTFA
- CIRO (Canadian Investment Regulatory Organization) — KYC Rule 3202
- OFAC (if US nexus) — SDN List, 50% Rule
- FATCA (if US indicia) — IRS reporting
- CRS (Common Reporting Standard) — OECD automatic exchange"""


# =============================================================================
# Prompt Template Loader
# =============================================================================

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_PROMPT_VARIABLES = {
    "KYC_EVIDENCE_RULES": KYC_EVIDENCE_RULES,
    "KYC_OUTPUT_RULES": KYC_OUTPUT_RULES,
    "KYC_FALSE_POSITIVE_RULES": KYC_FALSE_POSITIVE_RULES,
    "KYC_REGULATORY_CONTEXT": KYC_REGULATORY_CONTEXT,
}


def load_prompt_template(name: str) -> str:
    """Load a prompt template from the prompts/ directory and inject shared variables.

    Args:
        name: Template name (without .txt extension).

    Returns:
        Formatted prompt string with all variables injected.

    Raises:
        FileNotFoundError: If the template file doesn't exist.
    """
    template_path = _PROMPTS_DIR / f"{name}.txt"
    template = template_path.read_text(encoding="utf-8")
    return template.format(**_PROMPT_VARIABLES)


# Global API key storage - set once at startup
_API_KEY: str | None = None


def set_api_key(key: str):
    """Set the API key globally for all agents."""
    global _API_KEY
    _API_KEY = key
    os.environ["ANTHROPIC_API_KEY"] = key
    logger.debug("API key set globally")


def get_api_key() -> str | None:
    """Get the current API key."""
    return _API_KEY or os.environ.get("ANTHROPIC_API_KEY")


def _extract_retry_after(error: Exception, default_wait: int) -> int:
    """Parse the ``retry-after`` header from an API error response.

    Returns *default_wait* if the header is missing or unparseable.
    Adds a 5-second buffer to the parsed value.
    """
    try:
        if hasattr(error, 'response') and error.response is not None:
            retry_after = error.response.headers.get('retry-after')
            if retry_after:
                return int(float(retry_after)) + 5
    except (ValueError, AttributeError, TypeError):
        pass
    return default_wait


def _safe_parse_enum(enum_class, raw_value: str, default, fallback=None):
    """Parse a string into an enum, returning default/fallback on failure.

    Args:
        enum_class: The enum type (e.g. DispositionStatus).
        raw_value: Raw string to parse (will be uppercased).
        default: Default enum value if raw_value is empty/None.
        fallback: Value to return on ValueError. If None, returns default.
    """
    try:
        return enum_class(raw_value.upper() if raw_value else default.value)
    except (ValueError, AttributeError):
        return fallback if fallback is not None else default


def _model_family(model_id: str) -> str:
    """Map a model ID (e.g. 'claude-sonnet-4-20250514') to its rate-limit pool family."""
    if "opus" in model_id:
        return "opus"
    if "haiku" in model_id:
        return "haiku"
    return "sonnet"  # default — covers sonnet and any unknown models


class BaseAgent(ABC):
    """
    Base class for all research agents.

    Handles Claude API communication and tool use loops.
    Subclasses define the system prompt and which tools to use.
    """

    # Default idle timeout in seconds — agent is killed only if no progress
    # (no API response, no tool completion) for this duration.  An agent
    # actively working through many tool calls will never hit this.
    DEFAULT_IDLE_TIMEOUT: int = 120

    # Per-model-family semaphores — Sonnet and Opus have independent rate limit
    # pools at Anthropic, so we use separate semaphores to prevent cross-family
    # blocking.  Created lazily (needs a running event loop).
    _api_semaphores: dict[str, asyncio.Semaphore] = {}

    def __init__(
        self,
        model: str | None = None,
        max_tokens: int = 4096,
        max_tool_calls: int | None = None,
        api_key: str | None = None,
        timeout: int | None = None,
    ):
        config = get_config()

        # Use provided key, global key, or environment variable
        key = api_key or get_api_key()
        # Disable SDK-level retries — our custom transient/rate-limit loops handle
        # all retries to avoid nested retry explosion (SDK retries × custom retries).
        if key:
            self.client = anthropic.Anthropic(api_key=key, max_retries=0)
        else:
            self.client = anthropic.Anthropic(max_retries=0)

        # Store explicit model override, otherwise use lazy lookup
        self._explicit_model = model
        self.max_tokens = max_tokens
        # Store explicit tool limit override, otherwise use lazy lookup
        self._explicit_tool_limit = max_tool_calls
        self._config = config
        self._hit_rate_limit = False  # Track if rate limit was encountered

        # Search monitoring
        self._web_search_count = 0
        self._web_fetch_count = 0
        self._search_queries = []  # Track actual queries for monitoring
        self._fetched_urls: list[str] = []  # Track URLs fetched during investigation

        # Search context from pipeline (to avoid duplicate queries)
        self._search_context = ""

        # Activity-based idle timeout (seconds of no progress before kill)
        self._idle_timeout = timeout or self.DEFAULT_IDLE_TIMEOUT
        self._last_activity: float = 0.0  # monotonic timestamp, set at run start

        # Risk level — set after Stage 1 to scale tool limits
        self._risk_level: str | None = None

        # Token usage from last API call (preserved for pipeline metrics)
        self._last_usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }

        # Rate limit state from most recent API response headers
        self._rate_limit_snapshot: dict | None = None

    @property
    def model(self) -> str:
        """Get the model for this agent - uses routing based on agent name."""
        if self._explicit_model:
            return self._explicit_model
        # Use agent-specific model routing (Haiku for data gathering, Sonnet for reasoning)
        return get_model_for_agent(self.name)

    @model.setter
    def model(self, value: str):
        """Allow explicit model override."""
        self._explicit_model = value

    @property
    def max_tool_calls(self) -> int:
        """Get the max tool calls for this agent - uses routing based on agent name.

        If ``_risk_level`` is set (after Stage 1), tool limits are scaled:
        HIGH → 1.5x, CRITICAL → 2x.
        """
        if self._explicit_tool_limit is not None:
            return self._explicit_tool_limit
        # Use agent-specific tool limit routing, scaled by risk level
        return get_tool_limit_for_agent(self.name, risk_level=self._risk_level)

    @max_tool_calls.setter
    def max_tool_calls(self, value: int):
        """Allow explicit tool limit override."""
        self._explicit_tool_limit = value

    @property
    @abstractmethod
    def name(self) -> str:
        """Agent name for logging."""
        pass

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """System prompt for this agent."""
        pass

    @property
    @abstractmethod
    def tools(self) -> list[str]:
        """List of tool names this agent can use."""
        pass

    def get_tool_definitions(self) -> list[dict]:
        """Get Claude API tool definitions for this agent's tools."""
        tools = get_tools_for_agent(self.tools)

        # Add Claude's native web search if agent requested web_search
        if "web_search" in self.tools:
            tools.append({
                "type": "web_search_20250305",
                "name": "web_search"
            })

        return tools

    def reset_search_stats(self):
        """Reset search monitoring counters before a new run."""
        self._web_search_count = 0
        self._web_fetch_count = 0
        self._search_queries = []
        self._fetched_urls = []

    @property
    def search_stats(self) -> dict:
        """Get current search statistics."""
        return {
            "web_search_count": self._web_search_count,
            "web_fetch_count": self._web_fetch_count,
            "search_queries": self._search_queries.copy(),
            "fetched_urls": self._fetched_urls.copy(),
        }

    @property
    def search_context(self) -> str:
        """Get search context from pipeline (previously searched queries)."""
        return self._search_context or ""

    @search_context.setter
    def search_context(self, value: str):
        """Set search context (called by pipeline to share queries between agents)."""
        self._search_context = value

    # =========================================================================
    # Evidence Record Helpers
    # =========================================================================

    # TIER_0 source patterns — government registries, official sanctions lists,
    # regulatory databases.  Used to auto-elevate evidence to VERIFIED when a
    # finding comes from one of these authoritative sources with URLs.
    _TIER0_PATTERNS: tuple[str, ...] = (
        "OFAC", "SDN", "CSL", "OpenSanctions", "FATF", "FINTRAC",
        "Global Affairs", "UN SC", "EU FSF", "HMT", "SEMA",
        "Public Safety", "Interpol",
    )

    # Recognised screening sources for CLEAR record elevation — if a clear
    # record's supporting_data includes a sources_checked list containing any
    # of these, the record is elevated to SOURCED even without URLs (the
    # screening tool call itself is the source).
    _SCREENING_SOURCES: frozenset[str] = frozenset({
        "CSL", "OpenSanctions", "OFAC SDN", "Trade.gov CSL",
        "Canadian SEMA", "UN SCSL", "EU FSF", "UK HMT",
        "Global Affairs Canada", "ICIJ Offshore Leaks",
        "Interpol Red Notices", "FCA Warning List",
    })

    @staticmethod
    def _is_tier0_source(source_name: str) -> bool:
        """Check if a source name matches a TIER_0 (government/authoritative) pattern."""
        upper = source_name.upper()
        return any(pat.upper() in upper for pat in BaseAgent._TIER0_PATTERNS)

    def _build_finding_record(
        self,
        evidence_id: str,
        entity: str,
        claim: str,
        supporting_data: list = None,
        *,
        evidence_level=None,
        disposition=None,
        confidence=None,
        source_urls: list[str] | None = None,
        claim_urls: list[str] | None = None,
    ):
        """Build a standard evidence record for a finding.

        Imports are done at call time to avoid circular imports at module level.

        Evidence-level validation:
        - [V] VERIFIED requires at least one source URL; downgraded to [S] otherwise.
        - [V] or [S] require supporting_data; downgraded to [I] if empty.
        - If no evidence_level is provided, it is inferred:
          SOURCED if source_urls are present, INFERRED otherwise.
        """
        from datetime import datetime

        from models import Confidence as Conf
        from models import DispositionStatus, EvidenceClass, EvidenceRecord

        urls = claim_urls or source_urls or []
        data = supporting_data or []
        level = evidence_level

        # Infer evidence level when not explicitly provided
        if level is None:
            level = EvidenceClass.SOURCED if urls else EvidenceClass.INFERRED

        # Validate: V requires URLs
        if level == EvidenceClass.VERIFIED and not urls:
            logger.warning(
                "[%s] Evidence %s claimed VERIFIED but has no source URLs — downgrading to SOURCED",
                self.name, evidence_id,
            )
            level = EvidenceClass.SOURCED

        # Validate: V or S requires supporting_data
        if level in (EvidenceClass.VERIFIED, EvidenceClass.SOURCED) and not data:
            logger.warning(
                "[%s] Evidence %s claimed %s but has no supporting data — downgrading to INFERRED",
                self.name, evidence_id, level.value,
            )
            level = EvidenceClass.INFERRED

        # Auto-elevate: TIER_0 source + URLs → VERIFIED (when level was inferred, not explicit)
        if evidence_level is None and level != EvidenceClass.VERIFIED and urls and data:
            has_tier0 = any(
                self._is_tier0_source(str(v))
                for entry in data
                if isinstance(entry, dict)
                for v in entry.values()
                if isinstance(v, str)
            ) or self._is_tier0_source(self.name)
            if has_tier0:
                logger.info(
                    "[%s] Evidence %s auto-elevated to VERIFIED (TIER_0 source + URLs)",
                    self.name, evidence_id,
                )
                level = EvidenceClass.VERIFIED

        # Enforce TIER_3 cap: TIER_3 sources cannot be VERIFIED
        if level == EvidenceClass.VERIFIED and data:
            has_tier3 = any(
                isinstance(entry, dict) and entry.get("source_tier") == "TIER_3"
                for entry in data
            )
            if has_tier3:
                logger.warning(
                    "[%s] Evidence %s has TIER_3 source — capping at SOURCED",
                    self.name, evidence_id,
                )
                level = EvidenceClass.SOURCED

        return EvidenceRecord(
            evidence_id=evidence_id,
            source_type="agent",
            source_name=self.name,
            entity_screened=entity,
            claim=claim,
            evidence_level=level,
            supporting_data=data,
            disposition=disposition or DispositionStatus.PENDING_REVIEW,
            confidence=confidence or Conf.MEDIUM,
            source_urls=urls,
            data_as_of=datetime.now(UTC),
        )

    def _build_clear_record(
        self,
        evidence_id: str,
        entity: str,
        claim: str,
        supporting_data: list = None,
        *,
        disposition_reasoning: str = None,
        source_urls: list[str] | None = None,
        claim_urls: list[str] | None = None,
    ):
        """Build a standard 'no findings' evidence record."""
        from datetime import datetime

        from models import Confidence as Conf
        from models import DispositionStatus, EvidenceClass, EvidenceRecord

        urls = claim_urls or source_urls or []
        data = supporting_data or []

        # Infer level: SOURCED if URLs present, INFERRED otherwise
        level = EvidenceClass.SOURCED if urls else EvidenceClass.INFERRED

        # Elevate: screening tool calls with recognised sources → SOURCED
        # even without URLs (the screening tool call itself is the source)
        if level == EvidenceClass.INFERRED and data:
            for entry in data:
                if isinstance(entry, dict):
                    sources_checked = entry.get("sources_checked", [])
                    if isinstance(sources_checked, list) and any(
                        src in self._SCREENING_SOURCES for src in sources_checked
                    ):
                        level = EvidenceClass.SOURCED
                        break

        return EvidenceRecord(
            evidence_id=evidence_id,
            source_type="agent",
            source_name=self.name,
            entity_screened=entity,
            claim=claim,
            evidence_level=level,
            supporting_data=data,
            disposition=DispositionStatus.CLEAR,
            disposition_reasoning=disposition_reasoning,
            confidence=Conf.HIGH,
            source_urls=urls,
            data_as_of=datetime.now(UTC),
        )

    def _derive_disposition(self, records: list) -> "DispositionStatus":
        """Derive the most-severe disposition from evidence records (single source of truth).

        When evidence records exist, the agent-level disposition should reflect
        the worst-case disposition across all records rather than trusting the
        AI's top-level JSON field (which can disagree with the evidence it built).
        """
        from models import DispositionStatus
        if not records:
            return DispositionStatus.PENDING_REVIEW
        PRIORITY = {
            DispositionStatus.FALSE_POSITIVE: 0,
            DispositionStatus.CLEAR: 1,
            DispositionStatus.PENDING_REVIEW: 2,
            DispositionStatus.POTENTIAL_MATCH: 3,
            DispositionStatus.CONFIRMED_MATCH: 4,
        }
        return max(
            (getattr(r, 'disposition', DispositionStatus.PENDING_REVIEW) for r in records),
            key=lambda d: PRIORITY.get(d, 2),
        )

    @staticmethod
    def _attach_search_queries(result_obj, raw_result: dict):
        """Attach search_queries_executed from API result to a model object."""
        result_obj.search_queries_executed = raw_result.get("search_stats", {}).get("search_queries", [])

    @staticmethod
    def _attach_fetched_urls(evidence_records, raw_result: dict):
        """Attach fetched URLs from the agent run to evidence records.

        Only attaches to records that have no claim-specific URLs yet.
        Marks bulk-attached URLs with ``urls_are_global=True`` so downstream
        consumers know these are agent-wide, not claim-specific.
        """
        urls = raw_result.get("search_stats", {}).get("fetched_urls", [])
        if not urls:
            return
        for record in evidence_records:
            if hasattr(record, "source_urls"):
                # Skip records that already have claim-specific URLs
                if record.source_urls:
                    continue
                record.source_urls = list(urls)
                if hasattr(record, "urls_are_global"):
                    record.urls_are_global = True
            elif isinstance(record, dict):
                if record.get("source_urls"):
                    continue
                record["source_urls"] = list(urls)
                record["urls_are_global"] = True

    @classmethod
    def _get_api_semaphore(cls, model: str) -> asyncio.Semaphore:
        """Return the per-model-family API semaphore, creating it on first use."""
        family = _model_family(model)
        if family not in cls._api_semaphores:
            limit = API_CONCURRENCY_BY_FAMILY.get(family, API_CONCURRENCY_BY_FAMILY["default"])
            cls._api_semaphores[family] = asyncio.Semaphore(limit)
            logger.debug("Created %s semaphore with limit %d", family, limit)
        return cls._api_semaphores[family]

    def _update_rate_limit_state(self, headers):
        """Extract rate limit headers from a successful response and log remaining capacity."""
        req_remaining = headers.get("anthropic-ratelimit-requests-remaining")
        input_remaining = headers.get("anthropic-ratelimit-input-tokens-remaining")
        output_remaining = headers.get("anthropic-ratelimit-output-tokens-remaining")

        if req_remaining is not None:
            self._rate_limit_snapshot = {
                "requests_remaining": int(req_remaining),
                "input_tokens_remaining": int(input_remaining or 0),
                "output_tokens_remaining": int(output_remaining or 0),
            }
            if int(req_remaining) < 50:
                logger.warning("[%s] Low API requests remaining: %s", self.name, req_remaining)
            if input_remaining and int(input_remaining) < 50_000:
                logger.warning("[%s] Low input tokens remaining: %s", self.name, input_remaining)

    async def _await_with_heartbeat(self, coro, label: str = "operation"):
        """Await a coroutine, heartbeating every 15s so the idle watchdog doesn't fire.

        Long-running awaits — API calls with server-side web search (60-180s),
        semaphore waits when all concurrency slots are occupied — can
        legitimately take minutes.  The idle-timeout watchdog would mistake
        these for a stuck agent and cancel the run.

        This wrapper calls ``_touch_activity()`` every 15s to signal that the
        agent is alive and actively waiting, not hung.  It logs once when a
        single wait exceeds 60s for observability.

        Cancellation safety:
        - If the outer task is cancelled (watchdog fires for another reason),
          ``CancelledError`` propagates through ``asyncio.wait``, the inner
          task is cancelled, and the error re-raises to the caller.
        - ``sem.acquire()`` cancellation properly removes the waiter from the
          semaphore's internal queue (verified on Python 3.12+).
        """
        task = asyncio.create_task(coro)
        start = time.monotonic()
        logged_long_wait = False
        try:
            while not task.done():
                done, _ = await asyncio.wait({task}, timeout=15)
                if not done:
                    self._touch_activity()
                    elapsed = time.monotonic() - start
                    if not logged_long_wait and elapsed > 60:
                        logger.info(
                            "[%s] Long %s: %.0fs elapsed, still waiting...",
                            self.name, label, elapsed,
                        )
                        logged_long_wait = True
            return task.result()
        except BaseException:
            task.cancel()
            raise

    async def execute_tool_call(self, tool_name: str, tool_input: dict) -> Any:
        """
        Execute a tool call and return the result.

        Override this in subclasses to add custom tool handling.
        """
        return await execute_tool(tool_name, tool_input)

    def _touch_activity(self):
        """Mark that the agent made progress (API response or tool completion)."""
        self._last_activity = time.monotonic()

    async def run(self, user_message: str, context: dict = None) -> dict:
        """
        Run the agent with the given user message.

        Uses an activity-based idle timeout: the agent is only killed if no
        progress (API response, tool completion) occurs for ``_idle_timeout``
        seconds.  An agent actively working through many tool calls will never
        hit this, no matter how long the total run takes.
        """
        self._touch_activity()
        run_start = time.monotonic()
        inner_task = asyncio.create_task(self._run_inner(user_message, context))

        async def _watchdog():
            """Cancel the inner task if idle too long."""
            while not inner_task.done():
                await asyncio.sleep(10)
                idle = time.monotonic() - self._last_activity
                if idle > self._idle_timeout:
                    inner_task.cancel()
                    return

        watchdog_task = asyncio.create_task(_watchdog())
        try:
            return await inner_task
        except asyncio.CancelledError:
            elapsed = time.monotonic() - run_start
            idle = time.monotonic() - self._last_activity
            logger.error(
                f"[{self.name}] Idle timeout after {elapsed:.0f}s total "
                f"({idle:.0f}s since last activity, limit: {self._idle_timeout}s)"
            )
            raise TimeoutError(
                f"Agent {self.name} timed out after {elapsed:.0f}s "
                f"(no activity for {idle:.0f}s, limit: {self._idle_timeout}s)"
            ) from None
        finally:
            watchdog_task.cancel()

    async def _run_inner(self, user_message: str, context: dict = None) -> dict:
        """Inner run implementation (called with timeout wrapper)."""
        # Reset search stats for this run
        self.reset_search_stats()

        logger.debug("[%s] Using model: %s", self.name, self.model)
        messages = [{"role": "user", "content": user_message}]
        tool_definitions = self.get_tool_definitions()

        tool_call_count = 0

        while tool_call_count < self.max_tool_calls:
            # Call Claude - only include tools parameter if we have tools.
            # System prompt uses cache_control so repeated calls within the
            # 5-minute TTL read from cache (free for ITPM).
            api_kwargs = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "system": [
                    {
                        "type": "text",
                        "text": self.system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                "messages": messages,
            }
            if tool_definitions:
                api_kwargs["tools"] = tool_definitions

            # Handle rate limits + transient errors with retry.
            # Per-model semaphore limits concurrent in-flight API calls within
            # each model family (Sonnet/Opus have independent rate limit pools).
            sem = self._get_api_semaphore(self.model)
            response = None
            for transient_attempt in range(TRANSIENT_MAX_RETRIES):
                for rate_limit_attempt in range(RATE_LIMIT_MAX_RETRIES):
                    try:
                        # Phase 1: acquire semaphore slot (may wait if all
                        # slots are in use — heartbeat keeps watchdog alive)
                        await self._await_with_heartbeat(
                            sem.acquire(), label="semaphore wait",
                        )
                        try:
                            # Phase 2: API call (server-side web search can
                            # take 60-180s — heartbeat keeps watchdog alive)
                            raw = await self._await_with_heartbeat(
                                asyncio.to_thread(
                                    self.client.messages.with_raw_response.create,
                                    **api_kwargs,
                                ),
                                label="API call",
                            )
                            response = raw.parse()
                        finally:
                            sem.release()

                        # Read rate limit headers for observability + backpressure
                        self._update_rate_limit_state(raw.headers)

                        # If we recovered from rate limit, add buffer to let bucket refill
                        if rate_limit_attempt > 0:
                            self._hit_rate_limit = True
                            logger.info("[%s] Rate limit recovered, adding %ds buffer", self.name, RATE_LIMIT_RECOVERY_BUFFER)
                            await asyncio.sleep(RATE_LIMIT_RECOVERY_BUFFER)

                        break  # Success - exit rate limit retry loop

                    except anthropic.RateLimitError as e:
                        if rate_limit_attempt == RATE_LIMIT_MAX_RETRIES - 1:
                            logger.error("[%s] Rate limit exceeded after %d attempts", self.name, RATE_LIMIT_MAX_RETRIES)
                            raise

                        # Log which limit was hit from error response headers
                        if hasattr(e, 'response') and e.response is not None:
                            hdrs = e.response.headers
                            logger.warning(
                                "[%s] Rate limited — requests_remaining=%s, "
                                "input_tokens_remaining=%s, output_tokens_remaining=%s, "
                                "retry_after=%s",
                                self.name,
                                hdrs.get("anthropic-ratelimit-requests-remaining", "?"),
                                hdrs.get("anthropic-ratelimit-input-tokens-remaining", "?"),
                                hdrs.get("anthropic-ratelimit-output-tokens-remaining", "?"),
                                hdrs.get("retry-after", "?"),
                            )

                        wait_time = _extract_retry_after(e, RATE_LIMIT_DEFAULT_WAIT)

                        logger.warning("[%s] Rate limited, waiting %ds then retrying (attempt %d/%d)", self.name, wait_time, rate_limit_attempt + 1, RATE_LIMIT_MAX_RETRIES)
                        self._touch_activity()  # Rate limit wait is expected, not stuck
                        await asyncio.sleep(wait_time)

                    except (anthropic.APITimeoutError, anthropic.APIConnectionError, anthropic.InternalServerError) as e:
                        if transient_attempt == TRANSIENT_MAX_RETRIES - 1:
                            logger.error("[%s] Transient error after %d attempts: %s", self.name, TRANSIENT_MAX_RETRIES, e)
                            raise
                        wait_time = min(
                            TRANSIENT_BASE_WAIT * (2 ** transient_attempt) + random.uniform(0, 2),
                            TRANSIENT_MAX_WAIT,
                        )
                        logger.warning(
                            "[%s] Transient error (%s), retrying in %.1fs (attempt %d/%d)",
                            self.name, type(e).__name__, wait_time,
                            transient_attempt + 1, TRANSIENT_MAX_RETRIES,
                        )
                        self._touch_activity()  # Transient retry is expected, not stuck
                        await asyncio.sleep(wait_time)
                        break  # Break inner rate-limit loop to retry from transient loop

                if response is not None:
                    break  # Success — exit transient retry loop

            if response is None:
                raise RuntimeError(f"[{self.name}] Failed to get response after retries")

            # Proactive backpressure — slow down before hitting 429
            if self._rate_limit_snapshot:
                req_rem = self._rate_limit_snapshot["requests_remaining"]
                input_rem = self._rate_limit_snapshot["input_tokens_remaining"]
                if req_rem < RATE_LIMIT_BACKPRESSURE_THRESHOLD_RPM:
                    logger.info(
                        "[%s] Backpressure: %d requests remaining, pausing %.1fs",
                        self.name, req_rem, RATE_LIMIT_BACKPRESSURE_DELAY,
                    )
                    await asyncio.sleep(RATE_LIMIT_BACKPRESSURE_DELAY)
                elif input_rem < RATE_LIMIT_BACKPRESSURE_THRESHOLD_ITPM:
                    logger.info(
                        "[%s] Backpressure: %d input tokens remaining, pausing %.1fs",
                        self.name, input_rem, RATE_LIMIT_BACKPRESSURE_DELAY,
                    )
                    await asyncio.sleep(RATE_LIMIT_BACKPRESSURE_DELAY)

            # API responded — mark progress
            self._touch_activity()

            # Capture server-side tool use (native web search) from ANY response
            self._track_server_tool_use(response)

            # Check if we're done (no tool use)
            if response.stop_reason == "end_turn":
                return self._extract_response(response, messages)

            # Process tool calls
            if response.stop_reason == "tool_use":
                # Execute each tool call (skip server-side tools like web_search)
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        # Skip server-side tools - Claude handles these automatically
                        if block.name == "web_search":
                            tool_call_count += 1
                            continue

                        tool_call_count += 1
                        # Track web_fetch calls for monitoring
                        if block.name == "web_fetch":
                            self._web_fetch_count += 1
                            url = block.input.get("url", "") if hasattr(block, "input") else ""
                            if url:
                                self._fetched_urls.append(url)
                        logger.info("[%s] Calling %s", self.name, block.name)

                        result = await self.execute_tool_call(
                            block.name,
                            block.input
                        )
                        self._touch_activity()  # Tool completed — mark progress

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result) if isinstance(result, dict) else str(result)
                        })

                # Add assistant + tool results to messages only if we have client-side results
                if tool_results:
                    messages.append({
                        "role": "assistant",
                        "content": response.content
                    })
                    messages.append({
                        "role": "user",
                        "content": tool_results
                    })
                else:
                    # All tool_use blocks were server-side — no client results to send.
                    # Treat as end_turn to avoid orphaned assistant message in history.
                    return self._extract_response(response, messages)
            else:
                # Unexpected stop reason
                break

        # Max tool calls reached
        return self._extract_response(response, messages)

    def _track_server_tool_use(self, response: anthropic.types.Message):
        """Track native web search queries from server_tool_use blocks.

        Claude's native web_search_20250305 produces server_tool_use blocks
        (not regular tool_use) that are executed server-side. We scan every
        response for these to capture the actual search queries.
        """
        for block in response.content:
            if getattr(block, "type", None) == "server_tool_use" and getattr(block, "name", None) == "web_search":
                self._web_search_count += 1
                query = ""
                block_input = getattr(block, "input", None)
                if isinstance(block_input, dict):
                    query = block_input.get("query", "")
                if query:
                    self._search_queries.append(query)
                logger.info("[%s] Web search #%d: %s...", self.name, self._web_search_count, query[:80])

    def _extract_response(self, response: anthropic.types.Message, messages: list) -> dict:
        """Extract the final text response and any JSON data."""
        # Preserve cumulative token usage for pipeline metrics (including cache stats)
        cache_read = getattr(response.usage, 'cache_read_input_tokens', 0) or 0
        cache_creation = getattr(response.usage, 'cache_creation_input_tokens', 0) or 0
        self._last_usage = {
            "input_tokens": self._last_usage["input_tokens"] + response.usage.input_tokens,
            "output_tokens": self._last_usage["output_tokens"] + response.usage.output_tokens,
            "cache_read_input_tokens": self._last_usage.get("cache_read_input_tokens", 0) + cache_read,
            "cache_creation_input_tokens": self._last_usage.get("cache_creation_input_tokens", 0) + cache_creation,
        }

        text_content = ""
        for block in response.content:
            if hasattr(block, "text"):
                text_content += block.text

        # Try to extract JSON from the response using multiple patterns
        json_data = None
        try:
            import re
            # 1. Standard ```json ... ``` block
            json_match = re.search(r'```json\s*(.*?)\s*```', text_content, re.DOTALL)
            if json_match:
                json_data = json.loads(json_match.group(1))
            else:
                # 2. Any ``` ... ``` code block containing JSON
                code_match = re.search(r'```\s*([\{\[].*?)\s*```', text_content, re.DOTALL)
                if code_match:
                    json_data = json.loads(code_match.group(1))
                else:
                    # 3. Bare JSON object/array in response
                    bare_match = re.search(r'(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})', text_content, re.DOTALL)
                    if bare_match:
                        json_data = json.loads(bare_match.group(1))
                    else:
                        # 4. Try entire response as JSON
                        json_data = json.loads(text_content)
        except (json.JSONDecodeError, ValueError, AttributeError) as e:
            logger.warning("[%s] Could not extract JSON from response: %s", self.name, str(e)[:100])

        return {
            "text": text_content,
            "json": json_data,
            "messages": messages,
            "model": self.model,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
            "hit_rate_limit": self._hit_rate_limit,
            # Search monitoring stats
            "search_stats": {
                "web_search_count": self._web_search_count,
                "web_fetch_count": self._web_fetch_count,
                "search_queries": self._search_queries.copy(),
                "fetched_urls": self._fetched_urls.copy(),
            },
        }


class SimpleAgent(BaseAgent):
    """
    A simple agent that can be configured at runtime.

    Useful for one-off tasks or testing.
    """

    def __init__(
        self,
        agent_name: str,
        system: str,
        agent_tools: list[str] = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self._name = agent_name
        self._system_prompt = system
        self._tools = agent_tools or []

    @property
    def name(self) -> str:
        return self._name

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    @property
    def tools(self) -> list[str]:
        return self._tools
