"""Tests for schema versioning."""

from schema_migration import SCHEMA_VERSION, check_schema_version


class TestSchemaVersion:
    def test_matching_version(self):
        data = {"schema_version": SCHEMA_VERSION}
        assert check_schema_version(data, "test") is True

    def test_missing_version_legacy(self):
        data = {"some_key": "value"}
        assert check_schema_version(data, "test") is True

    def test_version_mismatch(self):
        data = {"schema_version": "0.0.1"}
        assert check_schema_version(data, "test") is False

    def test_schema_version_on_kyc_output(self):
        from models import ClientType, InvestigationPlan, KYCOutput
        output = KYCOutput(
            client_id="test",
            client_type=ClientType.INDIVIDUAL,
            client_data={},
            intake_classification=InvestigationPlan(
                client_type=ClientType.INDIVIDUAL, client_id="test"
            ),
        )
        assert output.schema_version == "1.0.0"

    def test_roundtrip(self):
        data = {"schema_version": SCHEMA_VERSION, "completed_stage": 2}
        assert check_schema_version(data, "checkpoint") is True
