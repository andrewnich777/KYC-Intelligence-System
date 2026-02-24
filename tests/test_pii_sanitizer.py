"""Tests for PII sanitizer and encryption utilities."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from evidence_store import EvidenceStore
from utilities.pii_sanitizer import REDACTED, sanitize, sanitize_dict

# =========================================================================
# sanitize() — free-text redaction
# =========================================================================

class TestSanitizeText:
    """Regex-based PII redaction in free-text."""

    def test_sin_pattern_with_dashes(self):
        assert REDACTED in sanitize("SIN is 123-456-789 on file")

    def test_sin_pattern_with_spaces(self):
        assert REDACTED in sanitize("SIN: 123 456 789")

    def test_sin_pattern_no_separators(self):
        assert REDACTED in sanitize("SIN 123456789 found")

    def test_dob_redacted(self):
        result = sanitize("Born on 1985-03-15 in Toronto")
        assert "1985-03-15" not in result
        assert REDACTED in result

    def test_email_redacted(self):
        result = sanitize("Contact: sarah.thompson@example.com")
        assert "sarah.thompson@example.com" not in result
        assert REDACTED in result

    def test_phone_redacted(self):
        result = sanitize("Call 416-555-1234 for details")
        assert "416-555-1234" not in result
        assert REDACTED in result

    def test_phone_with_country_code(self):
        result = sanitize("Phone: +1 416-555-1234")
        assert "416-555-1234" not in result

    def test_no_pii_unchanged(self):
        text = "Risk level HIGH, 45 points"
        assert sanitize(text) == text

    def test_multiple_patterns(self):
        text = "Name DOB 1990-01-01 email john@test.com SIN 123-456-789"
        result = sanitize(text)
        assert "1990-01-01" not in result
        assert "john@test.com" not in result
        assert "123-456-789" not in result


# =========================================================================
# sanitize_dict() — model-aware masking
# =========================================================================

class TestSanitizeDict:
    """Dict field masking using PII field names."""

    def test_masks_known_pii_fields(self):
        d = {"full_name": "Sarah Thompson", "risk_level": "LOW"}
        result = sanitize_dict(d)
        assert result["full_name"] == REDACTED
        assert result["risk_level"] == "LOW"

    def test_masks_sin_last4(self):
        d = {"sin_last4": "7890", "client_type": "individual"}
        result = sanitize_dict(d)
        assert result["sin_last4"] == REDACTED
        assert result["client_type"] == "individual"

    def test_masks_date_of_birth(self):
        d = {"date_of_birth": "1985-03-15", "citizenship": "Canada"}
        result = sanitize_dict(d)
        assert result["date_of_birth"] == REDACTED
        assert result["citizenship"] == "Canada"

    def test_masks_us_tin(self):
        d = {"us_tin": "123-45-6789"}
        result = sanitize_dict(d)
        assert result["us_tin"] == REDACTED

    def test_preserves_none_values(self):
        d = {"full_name": None, "risk_level": "HIGH"}
        result = sanitize_dict(d)
        assert result["full_name"] is None

    def test_nested_dict_masked(self):
        d = {
            "client": {
                "full_name": "John Smith",
                "employer": "Acme Corp",
            },
            "risk": "LOW",
        }
        result = sanitize_dict(d)
        assert result["client"]["full_name"] == REDACTED
        assert result["client"]["employer"] == REDACTED
        assert result["risk"] == "LOW"

    def test_list_of_dicts_masked(self):
        d = {
            "owners": [
                {"full_name": "Owner A", "role": "Director"},
                {"full_name": "Owner B", "role": "CEO"},
            ]
        }
        result = sanitize_dict(d)
        assert result["owners"][0]["full_name"] == REDACTED
        assert result["owners"][0]["role"] == "Director"
        assert result["owners"][1]["full_name"] == REDACTED

    def test_with_model_class(self):
        """sanitize_dict respects pii=True metadata on model fields."""
        from models import IndividualClient
        d = {"full_name": "Test", "citizenship": "Canada"}
        result = sanitize_dict(d, model_class=IndividualClient)
        assert result["full_name"] == REDACTED
        # citizenship is not tagged pii=True
        assert result["citizenship"] == "Canada"


# =========================================================================
# EvidenceStore.to_redacted_list()
# =========================================================================

class TestEvidenceStoreRedaction:
    """to_redacted_list masks PII in evidence records."""

    def test_redacts_entity_screened(self):
        """entity_screened contains client names — often PII-bearing field names."""
        store = EvidenceStore()
        store.append({
            "evidence_id": "E001",
            "source_type": "agent",
            "source_name": "IndividualSanctions",
            "entity_screened": "Sarah Thompson",
            "full_name": "Sarah Thompson",
            "date_of_birth": "1985-03-15",
            "claim": "Clear screen",
            "evidence_level": "I",
            "disposition": "CLEAR",
        })
        redacted = store.to_redacted_list()
        assert len(redacted) == 1
        # full_name and date_of_birth are PII fields
        assert redacted[0]["full_name"] == REDACTED
        assert redacted[0]["date_of_birth"] == REDACTED
        # entity_screened is NOT in PII_FIELD_NAMES by default
        assert redacted[0]["entity_screened"] == "Sarah Thompson"
        # Non-PII preserved
        assert redacted[0]["evidence_id"] == "E001"

    def test_empty_store_returns_empty(self):
        store = EvidenceStore()
        assert store.to_redacted_list() == []


# =========================================================================
# Encryption round-trip
# =========================================================================

class TestEncryption:
    """Optional at-rest encryption round-trip."""

    def test_encrypt_decrypt_roundtrip(self):
        pytest.importorskip("cryptography")
        from utilities.encryption import decrypt_file, encrypt_file

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test_data.json"
            original = json.dumps({"client": "Sarah Thompson", "risk": "HIGH"})
            test_file.write_text(original, encoding="utf-8")

            # Set a test key
            from cryptography.fernet import Fernet
            test_key = Fernet.generate_key()
            os.environ["ENCRYPTION_KEY"] = test_key.decode()

            try:
                encrypt_file(test_file)
                # Original file should be gone
                assert not test_file.exists()
                enc_path = test_file.with_suffix(".json.enc")
                assert enc_path.exists()

                # Decrypt and verify
                plaintext = decrypt_file(enc_path)
                assert json.loads(plaintext) == json.loads(original)
            finally:
                os.environ.pop("ENCRYPTION_KEY", None)

    def test_encryption_enabled_env_var(self):
        from utilities.encryption import encryption_enabled
        os.environ["ENCRYPT_RESULTS"] = "true"
        try:
            assert encryption_enabled() is True
        finally:
            os.environ.pop("ENCRYPT_RESULTS", None)

        assert encryption_enabled() is False
