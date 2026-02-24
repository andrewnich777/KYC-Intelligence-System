"""Tests for KYC configuration management."""

import os
from unittest.mock import patch


class TestConfig:
    def test_default_values(self):
        with patch.dict(os.environ, {}, clear=True):
            import importlib

            import config as config_module
            importlib.reload(config_module)

            cfg = config_module.Config()
            assert cfg.log_level == "INFO"
            assert cfg.output_dir == "results"
            assert cfg.max_retries == 5
            assert cfg.initial_backoff == 30
            assert cfg.agent_delay == 0  # No inter-agent delay (Claude Max)

    def test_env_var_override(self):
        test_env = {
            "LOG_LEVEL": "DEBUG",
            "OUTPUT_DIR": "/custom/path",
            "MAX_RETRIES": "10",
            "AGENT_DELAY": "5",
        }
        with patch.dict(os.environ, test_env, clear=True):
            import importlib

            import config as config_module
            importlib.reload(config_module)

            cfg = config_module.Config()
            assert cfg.log_level == "DEBUG"
            assert cfg.output_dir == "/custom/path"
            assert cfg.max_retries == 10
            assert cfg.agent_delay == 5

    def test_invalid_log_level_defaults_to_info(self):
        with patch.dict(os.environ, {"LOG_LEVEL": "INVALID"}, clear=True):
            import importlib

            import config as config_module
            importlib.reload(config_module)

            cfg = config_module.Config()
            assert cfg.log_level == "INFO"

    def test_get_log_level_returns_int(self):
        import importlib
        import logging

        import config as config_module
        importlib.reload(config_module)

        cfg = config_module.Config()
        cfg.log_level = "WARNING"
        assert cfg.get_log_level() == logging.WARNING


class TestAgentModels:
    def test_kyc_agent_model_routing(self):
        from config import get_model_for_agent
        assert get_model_for_agent("KYCSynthesis") == "claude-opus-4-6"
        assert get_model_for_agent("ReviewSession") == "claude-opus-4-6"
        assert get_model_for_agent("IndividualSanctions") == "claude-sonnet-4-6"
        assert get_model_for_agent("PEPDetection") == "claude-sonnet-4-6"
        assert get_model_for_agent("EntitySanctions") == "claude-sonnet-4-6"
        assert get_model_for_agent("UnknownAgent") == "claude-sonnet-4-6"  # default

    def test_tool_limits(self):
        from config import get_tool_limit_for_agent
        assert get_tool_limit_for_agent("IndividualSanctions") == 20
        assert get_tool_limit_for_agent("EntitySanctions") == 20
        assert get_tool_limit_for_agent("TransactionMonitoring") == 15
        assert get_tool_limit_for_agent("PEPDetection") == 12
        assert get_tool_limit_for_agent("KYCSynthesis") == 5
        assert get_tool_limit_for_agent("UnknownAgent") == 12  # default

    def test_transaction_monitoring_model(self):
        from config import get_model_for_agent
        assert get_model_for_agent("TransactionMonitoring") == "claude-sonnet-4-6"
