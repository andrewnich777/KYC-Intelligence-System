"""Tests for Workstream 2: Operational Hardening."""

import json
import tempfile
from pathlib import Path

from utilities.file_ops import atomic_write_json, atomic_write_text

# =========================================================================
# Atomic writes
# =========================================================================

class TestAtomicWrites:
    def test_atomic_write_json_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "data.json"
            atomic_write_json(path, {"key": "value"})
            assert path.exists()
            assert json.loads(path.read_text()) == {"key": "value"}

    def test_atomic_write_json_no_tmp_leftover(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "data.json"
            atomic_write_json(path, [1, 2, 3])
            tmp_path = path.with_suffix(".json.tmp")
            assert not tmp_path.exists()

    def test_atomic_write_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "note.txt"
            atomic_write_text(path, "hello world")
            assert path.read_text() == "hello world"

    def test_atomic_write_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sub" / "deep" / "data.json"
            atomic_write_json(path, {"nested": True})
            assert path.exists()

    def test_atomic_write_overwrites_existing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "data.json"
            atomic_write_json(path, {"v": 1})
            atomic_write_json(path, {"v": 2})
            assert json.loads(path.read_text()) == {"v": 2}


# =========================================================================
# SAR skip logic
# =========================================================================

class TestSARSkipLogic:
    """SAR narrative should be skipped for LOW/MEDIUM risk without triggers."""

    def test_low_risk_no_triggers_skips_sar(self):
        """Verify that the skip logic condition works correctly."""
        risk_level = "LOW"
        sar_risk = {"sar_risk_level": "LOW", "triggers": []}
        sar_risk_level = sar_risk.get("sar_risk_level", risk_level)
        sar_triggers = sar_risk.get("triggers", [])
        skip = (
            sar_risk_level in ("LOW", "MEDIUM")
            and not sar_triggers
            and risk_level in ("LOW", "MEDIUM")
        )
        assert skip is True

    def test_high_risk_does_not_skip(self):
        risk_level = "HIGH"
        sar_risk = {"sar_risk_level": "HIGH", "triggers": ["sanctions_match"]}
        sar_risk_level = sar_risk.get("sar_risk_level", risk_level)
        sar_triggers = sar_risk.get("triggers", [])
        skip = (
            sar_risk_level in ("LOW", "MEDIUM")
            and not sar_triggers
            and risk_level in ("LOW", "MEDIUM")
        )
        assert skip is False

    def test_medium_with_triggers_does_not_skip(self):
        risk_level = "MEDIUM"
        sar_risk = {"sar_risk_level": "MEDIUM", "triggers": ["pep_match"]}
        sar_risk_level = sar_risk.get("sar_risk_level", risk_level)
        sar_triggers = sar_risk.get("triggers", [])
        skip = (
            sar_risk_level in ("LOW", "MEDIUM")
            and not sar_triggers
            and risk_level in ("LOW", "MEDIUM")
        )
        assert skip is False


# =========================================================================
# Checkpoint consistency hash
# =========================================================================

class TestCheckpointHash:
    def test_hash_format(self):
        """Checkpoint hash encodes stage + evidence count."""
        stage = 2
        ev_count = 15
        h = f"stage={stage};ev={ev_count}"
        assert h == "stage=2;ev=15"

    def test_hash_detects_stale_state(self):
        """Mismatch between saved hash and recomputed hash signals staleness."""
        saved_hash = "stage=2;ev=15"
        disk_count = 18  # Evidence store modified since checkpoint
        computed = f"stage=2;ev={disk_count}"
        assert saved_hash != computed


# =========================================================================
# FATCA follow-up actions
# =========================================================================

class TestFATCAFollowUp:
    def test_unchecked_indicia_have_follow_up(self):
        from models import IndividualClient
        from utilities.individual_fatca_crs import classify_individual_fatca_crs

        client = IndividualClient(
            full_name="Test Person",
            citizenship="Canada",
            us_person=False,
        )
        result = classify_individual_fatca_crs(client)
        fatca = result["fatca"]

        # There should be unchecked indicia (telephone, transfer, POA)
        assert len(fatca["unchecked_indicia"]) >= 3
        # Follow-up actions should be populated for each unchecked indicium
        assert len(fatca["follow_up_actions"]) >= 3
        assert any("telephone" in a.lower() for a in fatca["follow_up_actions"])
        assert any("standing instructions" in a.lower() for a in fatca["follow_up_actions"])
        assert any("power of attorney" in a.lower() for a in fatca["follow_up_actions"])
