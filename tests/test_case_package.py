"""Tests for case package export (Feature 6)."""

import json
import os
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generators.case_package import _build_metadata, _build_readme, export_case_package

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _mock_output():
    output = MagicMock()
    output.client_id = "test_pkg_001"
    output.client_type.value = "individual"
    output.client_data = {"full_name": "Test User"}
    output.generated_at = datetime(2026, 3, 1, 12, 0, 0)
    output.duration_seconds = 120
    output.final_decision.value = "APPROVE"
    output.is_degraded = False
    output.schema_version = "3.0"
    output.metrics = {"total_duration": 120}
    output.synthesis.revised_risk_assessment.risk_level.value = "LOW"
    output.intake_classification.preliminary_risk.risk_level.value = "LOW"
    output.intake_classification.model_dump.return_value = {"client_id": "test_pkg_001"}
    output.review_session.model_dump.return_value = {"client_id": "test_pkg_001", "actions": []}
    return output


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBuildReadme:
    def test_contains_client_info(self):
        output = _mock_output()
        readme = _build_readme(output, ["01_aml_operations_brief.pdf"], [])
        assert "Test User" in readme
        assert "test_pkg_001" in readme

    def test_contains_package_contents(self):
        included = [
            "01_aml_operations_brief.pdf       - Full AML investigation (incl. executive summary page)",
            "05_screening_results.xlsx          - Multi-sheet Excel workbook (filterable)",
        ]
        readme = _build_readme(_mock_output(), included, [])
        assert "PACKAGE CONTENTS" in readme
        assert "aml_operations_brief.pdf" in readme
        assert "screening_results.xlsx" in readme

    def test_contains_retention_notice(self):
        readme = _build_readme(_mock_output(), [], [])
        assert "5-year" in readme


class TestBuildMetadata:
    def test_required_fields(self):
        meta = _build_metadata(_mock_output())
        assert meta["client_id"] == "test_pkg_001"
        assert meta["client_type"] == "individual"
        assert "generated_at" in meta
        assert "package_created_at" in meta

    def test_includes_pipeline_metrics(self):
        meta = _build_metadata(_mock_output())
        assert "pipeline_metrics" in meta


class TestExportCasePackage:
    def test_creates_zip_file(self):
        output = _mock_output()
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            zip_path = export_case_package(output, output_dir=td_path)
            assert zip_path.exists()
            assert zip_path.suffix == ".zip"

    def test_zip_contains_readme(self):
        output = _mock_output()
        with tempfile.TemporaryDirectory() as td:
            zip_path = export_case_package(output, output_dir=Path(td))
            with zipfile.ZipFile(str(zip_path), "r") as zf:
                assert "README.txt" in zf.namelist()

    def test_zip_contains_metadata(self):
        output = _mock_output()
        with tempfile.TemporaryDirectory() as td:
            zip_path = export_case_package(output, output_dir=Path(td))
            with zipfile.ZipFile(str(zip_path), "r") as zf:
                assert "11_pipeline_metadata.json" in zf.namelist()
                meta = json.loads(zf.read("11_pipeline_metadata.json"))
                assert meta["client_id"] == "test_pkg_001"

    def test_zip_contains_review_session(self):
        output = _mock_output()
        with tempfile.TemporaryDirectory() as td:
            zip_path = export_case_package(output, output_dir=Path(td))
            with zipfile.ZipFile(str(zip_path), "r") as zf:
                assert "10_review_session.json" in zf.namelist()

    def test_zip_contains_evidence_store(self):
        output = _mock_output()
        evidence = [{"evidence_id": "E-001", "claim": "test"}]
        with tempfile.TemporaryDirectory() as td:
            zip_path = export_case_package(output, output_dir=Path(td), evidence_store=evidence)
            with zipfile.ZipFile(str(zip_path), "r") as zf:
                assert "09_evidence_store.json" in zf.namelist()
                data = json.loads(zf.read("09_evidence_store.json"))
                assert len(data) == 1

    def test_zip_contains_sar_narrative(self):
        output = _mock_output()
        sar = {"narrative_text": "Test SAR narrative content"}
        with tempfile.TemporaryDirectory() as td:
            zip_path = export_case_package(output, output_dir=Path(td), sar_narrative=sar)
            with zipfile.ZipFile(str(zip_path), "r") as zf:
                assert "06_sar_narrative_draft.txt" in zf.namelist()
                content = zf.read("06_sar_narrative_draft.txt").decode()
                assert "Test SAR narrative content" in content

    def test_zip_contains_filing_jsons(self):
        output = _mock_output()
        fincen = {"form": "FinCEN SAR", "client_id": "test"}
        fintrac = {"form": "FINTRAC STR", "client_id": "test"}
        with tempfile.TemporaryDirectory() as td:
            zip_path = export_case_package(
                output, output_dir=Path(td),
                fincen_filing=fincen, fintrac_filing=fintrac,
            )
            with zipfile.ZipFile(str(zip_path), "r") as zf:
                assert "07_sar_filing_fincen.json" in zf.namelist()
                assert "08_str_filing_fintrac.json" in zf.namelist()

    def test_no_duplicate_aml_pdf(self):
        """Bug fix: AML brief should not appear twice in ZIP."""
        output = _mock_output()
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            # Create a fake AML PDF so it gets picked up
            (td_path / "aml_operations_brief.pdf").write_bytes(b"%PDF-fake")
            zip_path = export_case_package(output, output_dir=td_path)
            with zipfile.ZipFile(str(zip_path), "r") as zf:
                names = zf.namelist()
                aml_count = sum(1 for n in names if "aml_operations" in n)
                assert aml_count == 1

    def test_pdfs_included_when_exist(self):
        output = _mock_output()
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            for name in ("aml_operations_brief.pdf", "risk_assessment_brief.pdf"):
                (td_path / name).write_bytes(b"%PDF-fake")
            zip_path = export_case_package(output, output_dir=td_path)
            with zipfile.ZipFile(str(zip_path), "r") as zf:
                names = zf.namelist()
                assert "01_aml_operations_brief.pdf" in names
                assert "02_risk_assessment_brief.pdf" in names

    def test_excel_included_when_exists(self):
        output = _mock_output()
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            (td_path / "screening_results.xlsx").write_bytes(b"PK-fake-xlsx")
            zip_path = export_case_package(output, output_dir=td_path)
            with zipfile.ZipFile(str(zip_path), "r") as zf:
                assert "05_screening_results.xlsx" in zf.namelist()

    def test_missing_pdfs_not_fatal(self):
        """ZIP should still be created even if no PDFs exist."""
        output = _mock_output()
        with tempfile.TemporaryDirectory() as td:
            zip_path = export_case_package(output, output_dir=Path(td))
            assert zip_path.exists()
            with zipfile.ZipFile(str(zip_path), "r") as zf:
                # Should have at least README + metadata + review session
                assert len(zf.namelist()) >= 3
