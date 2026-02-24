"""Tests for risk config YAML loading."""

from pathlib import Path

from risk_config_loader import apply_risk_config_overrides, load_risk_config


class TestRiskConfig:
    def test_no_yaml_file_returns_empty(self):
        result = load_risk_config(Path("/nonexistent/path.yaml"))
        assert result == {}

    def test_valid_yaml_override(self, tmp_path):
        yaml_file = tmp_path / "risk.yaml"
        yaml_file.write_text("RISK_TIER_LOW_MAX: 20\n", encoding="utf-8")

        import constants
        original = constants.RISK_TIER_LOW_MAX
        try:
            count = apply_risk_config_overrides(yaml_file)
            assert count == 1
            assert constants.RISK_TIER_LOW_MAX == 20
        finally:
            constants.RISK_TIER_LOW_MAX = original

    def test_type_mismatch_rejected(self, tmp_path):
        yaml_file = tmp_path / "risk.yaml"
        yaml_file.write_text('RISK_TIER_LOW_MAX: "not_an_int"\n', encoding="utf-8")

        import constants
        original = constants.RISK_TIER_LOW_MAX
        count = apply_risk_config_overrides(yaml_file)
        assert count == 0
        assert original == constants.RISK_TIER_LOW_MAX

    def test_unknown_key_warned(self, tmp_path):
        yaml_file = tmp_path / "risk.yaml"
        yaml_file.write_text("NONEXISTENT_CONSTANT: 42\n", encoding="utf-8")

        count = apply_risk_config_overrides(yaml_file)
        assert count == 0

    def test_protected_constant_rejected(self, tmp_path):
        yaml_file = tmp_path / "risk.yaml"
        yaml_file.write_text("US_TERMS: [\"us\"]\n", encoding="utf-8")

        count = apply_risk_config_overrides(yaml_file)
        assert count == 0

    def test_defaults_unchanged_no_file(self):
        import constants
        original = constants.RISK_TIER_LOW_MAX
        count = apply_risk_config_overrides(Path("/nonexistent.yaml"))
        assert count == 0
        assert original == constants.RISK_TIER_LOW_MAX
