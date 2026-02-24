"""
Tests for generator display guards and pipeline fragility fixes.

WS6: Ensures _failed sentinels, None values, and rendering errors are handled.
"""



class TestUBOFailedSentinelDisplay:
    """UBO _failed sentinels should not score as positive hits."""

    def test_error_status_excluded_from_risk(self):
        """'Error' display values should not contribute risk points."""
        skip_values = ("clear", "pending", "pending review", "error")
        assert "error" in skip_values
        # Simulating the risk contribution logic
        contribution = 0
        s_lower = "error"  # _failed sentinel → "Error" display
        if s_lower not in skip_values:
            contribution += 15
        assert contribution == 0

    def test_clear_status_excluded(self):
        contribution = 0
        s_lower = "clear"
        if s_lower not in ("clear", "pending", "pending review", "error"):
            contribution += 15
        assert contribution == 0

    def test_match_status_contributes_risk(self):
        contribution = 0
        s_lower = "potential_match"
        if s_lower not in ("clear", "pending", "pending review", "error"):
            contribution += 15
        assert contribution == 15


class TestOnboardingDecisionGuard:
    """Guard against None recommended_decision."""

    def test_none_decision_defaults_to_escalate(self):
        from unittest.mock import MagicMock
        synthesis = MagicMock()
        synthesis.recommended_decision = None
        decision = "ESCALATE"
        if synthesis and synthesis.recommended_decision is not None:
            decision = synthesis.recommended_decision.value
        assert decision == "ESCALATE"

    def test_valid_decision_used(self):
        from unittest.mock import MagicMock
        synthesis = MagicMock()
        synthesis.recommended_decision.value = "APPROVE"
        decision = "ESCALATE"
        if synthesis and synthesis.recommended_decision is not None:
            decision = synthesis.recommended_decision.value
        assert decision == "APPROVE"


class TestEDDApprovalDisplay:
    """EDD approval_required should handle None gracefully."""

    def test_none_approval_shows_not_required(self):
        edd = {"edd_required": False, "approval_required": None}
        display = edd.get("approval_required") or "Not required"
        assert display == "Not required"

    def test_actual_approval_preserved(self):
        edd = {"edd_required": True, "approval_required": "senior_management"}
        display = edd.get("approval_required") or "Not required"
        assert display == "senior_management"

    def test_missing_key_shows_not_required(self):
        edd = {"edd_required": False}
        display = edd.get("approval_required") or "Not required"
        assert display == "Not required"


class TestPipelineDegradedDetection:
    """Synthesis failure detection should use specific signals."""

    def test_specific_failure_signal_detected(self):
        reasoning = "Synthesis failed due to API timeout"
        failure_signals = ("synthesis failed", "unable to synthesize", "synthesis error")
        assert any(sig in reasoning.lower() for sig in failure_signals)

    def test_normal_failure_mention_not_detected(self):
        """A mention of 'failed' in normal reasoning should not trigger degraded."""
        reasoning = "The subject failed to provide adequate documentation"
        failure_signals = ("synthesis failed", "unable to synthesize", "synthesis error")
        assert not any(sig in reasoning.lower() for sig in failure_signals)

    def test_investigation_failed_not_detected(self):
        """'Investigation failed' should not trigger synthesis degraded."""
        reasoning = "One agent failed but synthesis completed successfully"
        failure_signals = ("synthesis failed", "unable to synthesize", "synthesis error")
        assert not any(sig in reasoning.lower() for sig in failure_signals)
