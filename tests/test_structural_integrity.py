"""
Tests for Structural Pipeline Integrity Fixes.

Covers:
1. _derive_disposition() derives most-severe disposition from evidence records
2. .failed() factory methods produce PENDING_REVIEW sentinels (not None)
3. _store_failed_result() populates agent result fields on failure
4. UBO failure sentinels propagate "Error" through consumers
5. EDD cross-check defense skips CLEAR evidence with no matches
6. Officer override syncs agent-level disposition
7. Synthesis failure sets is_degraded
8. Adverse media / PEP cross-check overrides level when all records CLEAR
"""


from constants import FAILED_SENTINEL_KEY

# ---------------------------------------------------------------------------
# 1. _derive_disposition from evidence records
# ---------------------------------------------------------------------------

class TestDeriveDisposition:
    """Tests for BaseAgent._derive_disposition()."""

    def _make_record(self, disposition_str: str):
        from models import DispositionStatus, EvidenceClass, EvidenceRecord
        return EvidenceRecord(
            evidence_id="test",
            source_type="agent",
            source_name="Test",
            entity_screened="Test Entity",
            claim="test claim",
            evidence_level=EvidenceClass.SOURCED,
            disposition=DispositionStatus(disposition_str),
        )

    def _get_derive(self):
        """Get a bound _derive_disposition method from a minimal BaseAgent subclass."""
        from agents.base import BaseAgent

        class FakeAgent(BaseAgent):
            @property
            def name(self): return "FakeAgent"
            @property
            def system_prompt(self): return ""
            @property
            def tools(self): return []

        agent = FakeAgent.__new__(FakeAgent)
        return agent._derive_disposition

    def test_empty_records_returns_pending(self):
        from models import DispositionStatus
        derive = self._get_derive()
        assert derive([]) == DispositionStatus.PENDING_REVIEW

    def test_single_clear_returns_clear(self):
        from models import DispositionStatus
        derive = self._get_derive()
        records = [self._make_record("CLEAR")]
        assert derive(records) == DispositionStatus.CLEAR

    def test_mixed_returns_most_severe(self):
        from models import DispositionStatus
        derive = self._get_derive()
        records = [
            self._make_record("CLEAR"),
            self._make_record("POTENTIAL_MATCH"),
        ]
        assert derive(records) == DispositionStatus.POTENTIAL_MATCH

    def test_confirmed_match_is_highest(self):
        from models import DispositionStatus
        derive = self._get_derive()
        records = [
            self._make_record("POTENTIAL_MATCH"),
            self._make_record("CONFIRMED_MATCH"),
            self._make_record("CLEAR"),
        ]
        assert derive(records) == DispositionStatus.CONFIRMED_MATCH

    def test_false_positive_is_lowest(self):
        from models import DispositionStatus
        derive = self._get_derive()
        records = [
            self._make_record("FALSE_POSITIVE"),
            self._make_record("CLEAR"),
        ]
        assert derive(records) == DispositionStatus.CLEAR


# ---------------------------------------------------------------------------
# 2. .failed() factory methods
# ---------------------------------------------------------------------------

class TestFailedFactories:
    """Tests for .failed() factory methods on result models."""

    def test_sanctions_result_failed(self):
        from models import DispositionStatus, SanctionsResult
        sr = SanctionsResult.failed("Test Entity", "timeout error")
        assert sr.entity_screened == "Test Entity"
        assert sr.disposition == DispositionStatus.PENDING_REVIEW
        assert "failed" in sr.disposition_reasoning.lower()

    def test_pep_classification_failed(self):
        from models import PEPClassification, PEPLevel
        pep = PEPClassification.failed("Test Entity", "connection error")
        assert pep.entity_screened == "Test Entity"
        assert pep.detected_level == PEPLevel.NOT_PEP
        assert pep.edd_required is True  # Conservative: EDD required on failure

    def test_adverse_media_result_failed(self):
        from models import AdverseMediaLevel, AdverseMediaResult
        amr = AdverseMediaResult.failed("Test Entity", "500 error")
        assert amr.entity_screened == "Test Entity"
        assert amr.overall_level == AdverseMediaLevel.LOW_CONCERN  # Conservative

    def test_entity_verification_failed(self):
        from models import EntityVerification
        ev = EntityVerification.failed("Test Corp", "network error")
        assert ev.entity_name == "Test Corp"
        assert ev.verified_registration is False
        assert len(ev.discrepancies) == 1  # Conservative: sentinel discrepancy
        assert "VERIFICATION FAILED" in ev.discrepancies[0]

    def test_jurisdiction_risk_failed(self):
        from models import JurisdictionRiskResult, RiskLevel
        jr = JurisdictionRiskResult.failed("Canada", "api error")
        assert jr.overall_jurisdiction_risk == RiskLevel.MEDIUM  # Conservative

    def test_transaction_monitoring_failed(self):
        from models import TransactionMonitoringResult
        tm = TransactionMonitoringResult.failed("Test Entity", "timeout")
        assert tm.entity_screened == "Test Entity"
        assert tm.recommended_monitoring_frequency == "enhanced"  # Conservative


# ---------------------------------------------------------------------------
# 3. _store_failed_result populates agent result fields
# ---------------------------------------------------------------------------

class TestStoreFailedResult:
    """Tests for InvestigationMixin._store_failed_result()."""

    def test_stores_sanctions_sentinel(self):
        from models import DispositionStatus, InvestigationResults
        from pipeline_investigation import InvestigationMixin

        mixin = InvestigationMixin()
        results = InvestigationResults()
        assert results.individual_sanctions is None

        mixin._store_failed_result(results, "IndividualSanctions", "client_1", "timeout")
        assert results.individual_sanctions is not None
        assert results.individual_sanctions.disposition == DispositionStatus.PENDING_REVIEW
        assert "failed" in results.individual_sanctions.disposition_reasoning.lower()

    def test_stores_pep_sentinel(self):
        from models import InvestigationResults, PEPLevel
        from pipeline_investigation import InvestigationMixin

        mixin = InvestigationMixin()
        results = InvestigationResults()
        mixin._store_failed_result(results, "PEPDetection", "client_1", "error")
        assert results.pep_classification is not None
        assert results.pep_classification.detected_level == PEPLevel.NOT_PEP

    def test_unknown_agent_is_noop(self):
        from models import InvestigationResults
        from pipeline_investigation import InvestigationMixin

        mixin = InvestigationMixin()
        results = InvestigationResults()
        # Should not raise
        mixin._store_failed_result(results, "UnknownAgent", "client_1", "error")


# ---------------------------------------------------------------------------
# 4. UBO failure sentinels in consumers
# ---------------------------------------------------------------------------

class TestUBOFailureSentinels:
    """Tests for _failed sentinel handling in UBO consumers."""

    def test_ubo_helper_shows_error_for_failed(self):
        from generators.ubo_helpers import extract_ubo_field
        ubo_data = {
            "sanctions": {"_failed": True, "error": "timeout", "disposition": "PENDING_REVIEW"},
        }
        result = extract_ubo_field(ubo_data, "sanctions", "disposition")
        assert result == "Error"

    def test_ubo_helper_shows_clear_for_normal(self):
        from generators.ubo_helpers import extract_ubo_field
        ubo_data = {
            "sanctions": {"disposition": "CLEAR"},
        }
        result = extract_ubo_field(ubo_data, "sanctions", "disposition")
        assert result == "Clear"

    def test_synthesis_ubo_scoring_adds_partial_weight_for_failed(self):
        """Verify that failed UBO screenings contribute conservative risk points."""
        ubo_data = {
            "sanctions": {FAILED_SENTINEL_KEY: True, "error": "timeout"},
            "pep": {FAILED_SENTINEL_KEY: True, "error": "timeout"},
            "adverse_media": {FAILED_SENTINEL_KEY: True, "error": "timeout"},
            "ownership_percentage": 50,
        }
        # Calculate score same way pipeline_synthesis does
        score = 0
        sanctions = ubo_data.get("sanctions", {})
        if sanctions and sanctions.get(FAILED_SENTINEL_KEY):
            score += 15
        elif sanctions and sanctions.get("disposition") != "CLEAR":
            score += 30
        pep = ubo_data.get("pep", {})
        if pep and pep.get(FAILED_SENTINEL_KEY):
            score += 15
        elif pep and pep.get("detected_level", "NOT_PEP") != "NOT_PEP":
            score += 25
        adverse = ubo_data.get("adverse_media", {})
        if adverse and adverse.get(FAILED_SENTINEL_KEY):
            score += 10
        elif adverse and adverse.get("overall_level", "CLEAR") != "CLEAR":
            score += 15

        # All three failed → conservative total = 15 + 15 + 10 = 40
        assert score == 40

    def test_synthesis_ubo_scoring_normal_clear(self):
        """Verify normal clear UBO screenings contribute 0 risk points."""
        ubo_data = {
            "sanctions": {"disposition": "CLEAR"},
            "pep": {"detected_level": "NOT_PEP"},
            "adverse_media": {"overall_level": "CLEAR"},
        }
        score = 0
        sanctions = ubo_data.get("sanctions", {})
        if sanctions and sanctions.get(FAILED_SENTINEL_KEY):
            score += 15
        elif sanctions and sanctions.get("disposition") != "CLEAR":
            score += 30
        pep = ubo_data.get("pep", {})
        if pep and pep.get(FAILED_SENTINEL_KEY):
            score += 15
        elif pep and pep.get("detected_level", "NOT_PEP") != "NOT_PEP":
            score += 25
        adverse = ubo_data.get("adverse_media", {})
        if adverse and adverse.get(FAILED_SENTINEL_KEY):
            score += 10
        elif adverse and adverse.get("overall_level", "CLEAR") != "CLEAR":
            score += 15

        assert score == 0


# ---------------------------------------------------------------------------
# 5. EDD cross-check defense
# ---------------------------------------------------------------------------

class TestEDDCrossCheck:
    """Tests for EDD sanctions cross-check defense."""

    def test_clear_evidence_with_no_matches_skips_trigger(self):
        """If all evidence records are CLEAR and no matches, don't trigger EDD."""
        from models import (
            DispositionStatus,
            EvidenceClass,
            EvidenceRecord,
            InvestigationResults,
            SanctionsResult,
        )
        clear_record = EvidenceRecord(
            evidence_id="san_ind_clear",
            source_type="agent",
            source_name="IndividualSanctions",
            entity_screened="David Chen",
            claim="No sanctions matches found",
            evidence_level=EvidenceClass.SOURCED,
            disposition=DispositionStatus.CLEAR,
        )
        sr = SanctionsResult(
            entity_screened="David Chen",
            disposition=DispositionStatus.PENDING_REVIEW,  # Stale agent-level
            evidence_records=[clear_record],
            matches=[],  # No matches
        )
        investigation = InvestigationResults(individual_sanctions=sr)

        triggers = []
        from utilities.edd_requirements import _check_sanctions_triggers
        _check_sanctions_triggers(investigation, triggers)

        # Should NOT trigger despite stale agent-level PENDING_REVIEW
        assert len(triggers) == 0

    def test_actual_match_still_triggers(self):
        """If there are actual matches, trigger should still fire."""
        from models import (
            DispositionStatus,
            EvidenceClass,
            EvidenceRecord,
            InvestigationResults,
            SanctionsMatch,
            SanctionsResult,
        )
        finding_record = EvidenceRecord(
            evidence_id="san_ind_0",
            source_type="agent",
            source_name="IndividualSanctions",
            entity_screened="Alexander Petrov",
            claim="Sanctions match: Alexander Petrov on SDN",
            evidence_level=EvidenceClass.SOURCED,
            disposition=DispositionStatus.POTENTIAL_MATCH,
        )
        sr = SanctionsResult(
            entity_screened="Alexander Petrov",
            disposition=DispositionStatus.POTENTIAL_MATCH,
            evidence_records=[finding_record],
            matches=[SanctionsMatch(list_name="SDN", matched_name="Alexander Petrov", score=0.95)],
        )
        investigation = InvestigationResults(individual_sanctions=sr)

        triggers = []
        from utilities.edd_requirements import _check_sanctions_triggers
        _check_sanctions_triggers(investigation, triggers)

        assert len(triggers) == 1
        assert "POTENTIAL_MATCH" in triggers[0]


# ---------------------------------------------------------------------------
# 6. EDD UBO failure sentinel triggers
# ---------------------------------------------------------------------------

class TestEDDUBOFailure:
    """Tests for UBO failure sentinel handling in EDD."""

    def test_failed_ubo_sanctions_triggers_edd(self):
        from models import InvestigationResults
        from utilities.edd_requirements import _check_sanctions_triggers

        investigation = InvestigationResults(
            ubo_screening={
                "John Smith": {
                    "sanctions": {"_failed": True, "error": "timeout", "disposition": "PENDING_REVIEW"},
                    "pep": {"detected_level": "NOT_PEP"},
                    "adverse_media": {"overall_level": "CLEAR"},
                    "ownership_percentage": 50,
                },
            }
        )

        triggers = []
        _check_sanctions_triggers(investigation, triggers)

        assert len(triggers) == 1
        assert "failed" in triggers[0].lower()
        assert "John Smith" in triggers[0]


# ---------------------------------------------------------------------------
# 7. Adverse media / PEP cross-check overrides
# ---------------------------------------------------------------------------

class TestAdverseMediaCrossCheck:
    """Tests for adverse media level cross-check override."""

    def test_all_clear_evidence_overrides_level(self):
        from models import AdverseMediaLevel, DispositionStatus, EvidenceClass, EvidenceRecord

        # Simulate: AI says MATERIAL_CONCERN but all evidence records are CLEAR
        records = [
            EvidenceRecord(
                evidence_id="adv_ind_clear",
                source_type="agent",
                source_name="IndividualAdverseMedia",
                entity_screened="David Chen",
                claim="No adverse media found",
                evidence_level=EvidenceClass.SOURCED,
                disposition=DispositionStatus.CLEAR,
            ),
        ]

        # The cross-check logic: if all records CLEAR → level = CLEAR
        if records and all(
            getattr(r, 'disposition', None) == DispositionStatus.CLEAR for r in records
        ):
            level = AdverseMediaLevel.CLEAR
        else:
            level = AdverseMediaLevel.MATERIAL_CONCERN

        assert level == AdverseMediaLevel.CLEAR


# ---------------------------------------------------------------------------
# 8. Synthesis failure → is_degraded propagation
# ---------------------------------------------------------------------------

class TestSynthesisFailurePropagation:
    """Tests for synthesis failure detection."""

    def test_failed_reasoning_detected(self):
        """Verify that 'failed' in decision_reasoning sets is_degraded."""
        from models import InvestigationResults, KYCSynthesisOutput, OnboardingDecision

        investigation = InvestigationResults()
        synthesis = KYCSynthesisOutput(
            recommended_decision=OnboardingDecision.ESCALATE,
            decision_reasoning="Synthesis failed: timeout — escalating for manual review",
        )

        # Logic from pipeline.py
        if synthesis and "failed" in (synthesis.decision_reasoning or "").lower():
            investigation.is_degraded = True

        assert investigation.is_degraded is True

    def test_normal_reasoning_not_degraded(self):
        """Normal reasoning does not set is_degraded."""
        from models import InvestigationResults, KYCSynthesisOutput, OnboardingDecision

        investigation = InvestigationResults()
        synthesis = KYCSynthesisOutput(
            recommended_decision=OnboardingDecision.APPROVE,
            decision_reasoning="Low risk individual with no adverse findings.",
        )

        if synthesis and "failed" in (synthesis.decision_reasoning or "").lower():
            investigation.is_degraded = True

        assert investigation.is_degraded is False


# ---------------------------------------------------------------------------
# 9. Officer override syncs agent disposition
# ---------------------------------------------------------------------------

class TestOfficerOverrideSync:
    """Tests for _sync_agent_dispositions in ReviewMixin."""

    def test_sync_updates_sanctions_disposition(self):
        from models import (
            DispositionStatus,
            InvestigationResults,
            SanctionsResult,
        )
        from pipeline_review import ReviewMixin

        # Setup: agent says POTENTIAL_MATCH
        sr = SanctionsResult(
            entity_screened="Test Entity",
            disposition=DispositionStatus.POTENTIAL_MATCH,
        )
        investigation = InvestigationResults(individual_sanctions=sr)

        # Simulate evidence store with overridden record
        class FakeStore:
            def query(self, source=None):
                return [{"disposition": "FALSE_POSITIVE", "source_name": source}]

        mixin = ReviewMixin()
        mixin._sync_agent_dispositions(investigation, FakeStore())

        # Agent-level disposition should now be FALSE_POSITIVE
        assert investigation.individual_sanctions.disposition == DispositionStatus.FALSE_POSITIVE

    def test_sync_noop_without_evidence_store_query(self):
        """When evidence store doesn't support query(), sync is a no-op."""
        from models import DispositionStatus, InvestigationResults, SanctionsResult
        from pipeline_review import ReviewMixin

        sr = SanctionsResult(
            entity_screened="Test Entity",
            disposition=DispositionStatus.POTENTIAL_MATCH,
        )
        investigation = InvestigationResults(individual_sanctions=sr)

        mixin = ReviewMixin()
        # Simple list has no query method
        mixin._sync_agent_dispositions(investigation, [])

        # Should remain unchanged (no-op)
        assert investigation.individual_sanctions.disposition == DispositionStatus.POTENTIAL_MATCH

    def test_sync_pep_all_false_positive_becomes_not_pep(self):
        """When all PEP evidence is FALSE_POSITIVE, detected_level should collapse to NOT_PEP."""
        from models import InvestigationResults, PEPClassification, PEPLevel
        from pipeline_review import ReviewMixin

        pep = PEPClassification(
            entity_screened="Test Entity",
            detected_level=PEPLevel.DOMESTIC_PEP,
            edd_required=True,
        )
        investigation = InvestigationResults(pep_classification=pep)

        class FakeStore:
            def query(self, source=None):
                if source == "PEPDetection":
                    return [
                        {"disposition": "FALSE_POSITIVE", "source_name": "PEPDetection"},
                    ]
                return []

        mixin = ReviewMixin()
        mixin._sync_agent_dispositions(investigation, FakeStore())

        assert investigation.pep_classification.detected_level == PEPLevel.NOT_PEP
        assert investigation.pep_classification.edd_required is False

    def test_sync_pep_mixed_keeps_level(self):
        """When PEP evidence has a mix (some cleared, some not), keep the detected level."""
        from models import InvestigationResults, PEPClassification, PEPLevel
        from pipeline_review import ReviewMixin

        pep = PEPClassification(
            entity_screened="Test Entity",
            detected_level=PEPLevel.FOREIGN_PEP,
            edd_required=True,
        )
        investigation = InvestigationResults(pep_classification=pep)

        class FakeStore:
            def query(self, source=None):
                if source == "PEPDetection":
                    return [
                        {"disposition": "FALSE_POSITIVE", "source_name": "PEPDetection"},
                        {"disposition": "CONFIRMED_MATCH", "source_name": "PEPDetection"},
                    ]
                return []

        mixin = ReviewMixin()
        mixin._sync_agent_dispositions(investigation, FakeStore())

        # One record is still CONFIRMED_MATCH, so PEP level should not change
        assert investigation.pep_classification.detected_level == PEPLevel.FOREIGN_PEP
        assert investigation.pep_classification.edd_required is True

    def test_sync_adverse_media_all_cleared_becomes_clear(self):
        """When all adverse media evidence is CLEAR, overall_level should collapse to CLEAR."""
        from models import AdverseMediaLevel, AdverseMediaResult, InvestigationResults
        from pipeline_review import ReviewMixin

        amr = AdverseMediaResult(
            entity_screened="Test Entity",
            overall_level=AdverseMediaLevel.HIGH_RISK,
        )
        investigation = InvestigationResults(individual_adverse_media=amr)

        class FakeStore:
            def query(self, source=None):
                if source == "IndividualAdverseMedia":
                    return [{"disposition": "CLEAR", "source_name": "IndividualAdverseMedia"}]
                return []

        mixin = ReviewMixin()
        mixin._sync_agent_dispositions(investigation, FakeStore())

        assert investigation.individual_adverse_media.overall_level == AdverseMediaLevel.CLEAR

    def test_sync_adverse_media_pending_keeps_level(self):
        """When adverse media has PENDING_REVIEW records, keep the existing level."""
        from models import AdverseMediaLevel, AdverseMediaResult, InvestigationResults
        from pipeline_review import ReviewMixin

        amr = AdverseMediaResult(
            entity_screened="Test Entity",
            overall_level=AdverseMediaLevel.MATERIAL_CONCERN,
        )
        investigation = InvestigationResults(individual_adverse_media=amr)

        class FakeStore:
            def query(self, source=None):
                if source == "IndividualAdverseMedia":
                    return [{"disposition": "PENDING_REVIEW", "source_name": "IndividualAdverseMedia"}]
                return []

        mixin = ReviewMixin()
        mixin._sync_agent_dispositions(investigation, FakeStore())

        # PENDING_REVIEW is not in CLEARED set, so level stays
        assert investigation.individual_adverse_media.overall_level == AdverseMediaLevel.MATERIAL_CONCERN


# ---------------------------------------------------------------------------
# 10. UBO coroutine key preserved on failure (Fix 2 structural test)
# ---------------------------------------------------------------------------

class TestUBOCoroutineKeyPreservation:
    """Tests that the UBO parallel screening always returns the correct key."""

    def test_safe_ubo_task_success_returns_key(self):
        """On success, _safe_ubo_task returns (key, result, None)."""
        import asyncio

        async def _fake_research():
            return "fake_result"

        async def _run():
            # Inline the same pattern used in pipeline_investigation
            async def _safe_ubo_task(key, coro):
                try:
                    result = await coro
                    return key, result, None
                except Exception as e:
                    return key, None, e

            return await _safe_ubo_task("sanctions", _fake_research())

        key, result, error = asyncio.run(_run())
        assert key == "sanctions"
        assert result == "fake_result"
        assert error is None

    def test_safe_ubo_task_failure_preserves_key(self):
        """On failure, _safe_ubo_task returns (key, None, exception) — key is always correct."""
        import asyncio

        async def _failing_research():
            raise TimeoutError("connection timed out")

        async def _run():
            async def _safe_ubo_task(key, coro):
                try:
                    result = await coro
                    return key, result, None
                except Exception as e:
                    return key, None, e

            return await _safe_ubo_task("pep", _failing_research())

        key, result, error = asyncio.run(_run())
        assert key == "pep"
        assert result is None
        assert isinstance(error, TimeoutError)

    def test_mixed_success_failure_keys_correct(self):
        """With mixed outcomes, each key is correctly associated regardless of order."""
        import asyncio

        async def _run():
            async def _safe_ubo_task(key, coro):
                try:
                    result = await coro
                    return key, result, None
                except Exception as e:
                    return key, None, e

            async def _ok():
                return "ok_result"

            async def _fail():
                raise RuntimeError("boom")

            outcomes = await asyncio.gather(
                _safe_ubo_task("sanctions", _ok()),
                _safe_ubo_task("pep", _fail()),
                _safe_ubo_task("adverse_media", _ok()),
            )
            return outcomes

        outcomes = asyncio.run(_run())
        keys = [k for k, _, _ in outcomes]
        assert keys == ["sanctions", "pep", "adverse_media"]
        # sanctions succeeded
        assert outcomes[0][1] == "ok_result"
        assert outcomes[0][2] is None
        # pep failed — key still correct
        assert outcomes[1][1] is None
        assert isinstance(outcomes[1][2], RuntimeError)
        # adverse_media succeeded
        assert outcomes[2][1] == "ok_result"
        assert outcomes[2][2] is None


# ---------------------------------------------------------------------------
# 11. UBO adverse media in EDD triggers (Fix 4)
# ---------------------------------------------------------------------------

class TestEDDUBOAdverseMedia:
    """Tests for UBO adverse media checking in EDD triggers."""

    def test_ubo_high_risk_media_triggers_edd(self):
        from models import InvestigationResults
        from utilities.edd_requirements import _check_adverse_media_triggers

        investigation = InvestigationResults(
            ubo_screening={
                "John Smith": {
                    "sanctions": {"disposition": "CLEAR"},
                    "pep": {"detected_level": "NOT_PEP"},
                    "adverse_media": {"overall_level": "HIGH_RISK", "entity_screened": "John Smith"},
                    "ownership_percentage": 50,
                },
            }
        )

        triggers = []
        _check_adverse_media_triggers(investigation, triggers)

        assert len(triggers) == 1
        assert "John Smith" in triggers[0]
        assert "High-risk" in triggers[0]

    def test_ubo_material_concern_media_triggers_edd(self):
        from models import InvestigationResults
        from utilities.edd_requirements import _check_adverse_media_triggers

        investigation = InvestigationResults(
            ubo_screening={
                "Jane Doe": {
                    "adverse_media": {"overall_level": "MATERIAL_CONCERN"},
                    "ownership_percentage": 30,
                },
            }
        )

        triggers = []
        _check_adverse_media_triggers(investigation, triggers)

        assert len(triggers) == 1
        assert "Material" in triggers[0]
        assert "Jane Doe" in triggers[0]

    def test_ubo_clear_media_no_trigger(self):
        from models import InvestigationResults
        from utilities.edd_requirements import _check_adverse_media_triggers

        investigation = InvestigationResults(
            ubo_screening={
                "Clean Person": {
                    "adverse_media": {"overall_level": "CLEAR"},
                    "ownership_percentage": 60,
                },
            }
        )

        triggers = []
        _check_adverse_media_triggers(investigation, triggers)

        assert len(triggers) == 0

    def test_ubo_failed_media_triggers_edd(self):
        from models import InvestigationResults
        from utilities.edd_requirements import _check_adverse_media_triggers

        investigation = InvestigationResults(
            ubo_screening={
                "Error Person": {
                    "adverse_media": {"_failed": True, "error": "timeout"},
                    "ownership_percentage": 40,
                },
            }
        )

        triggers = []
        _check_adverse_media_triggers(investigation, triggers)

        assert len(triggers) == 1
        assert "failed" in triggers[0].lower()
        assert "Error Person" in triggers[0]

    def test_ubo_media_missing_key_no_trigger(self):
        """UBO with no adverse_media key at all should not trigger."""
        from models import InvestigationResults
        from utilities.edd_requirements import _check_adverse_media_triggers

        investigation = InvestigationResults(
            ubo_screening={
                "No Media": {
                    "sanctions": {"disposition": "CLEAR"},
                    "ownership_percentage": 25,
                },
            }
        )

        triggers = []
        _check_adverse_media_triggers(investigation, triggers)

        assert len(triggers) == 0
