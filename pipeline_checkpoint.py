"""
Checkpoint mixin for KYC Pipeline.

Handles checkpoint save/load and investigation serialization/deserialization.
"""

import json
from pathlib import Path

from logger import get_logger
from models import (
    AdverseMediaResult,
    EntityVerification,
    InvestigationResults,
    JurisdictionRiskResult,
    PEPClassification,
    SanctionsResult,
    TransactionMonitoringResult,
)
from schema_migration import check_schema_version

logger = get_logger(__name__)


class CheckpointMixin:
    """Checkpoint persistence for pipeline state."""

    def _get_checkpoint_path(self, client_id: str) -> Path:
        return self.output_dir / client_id / "checkpoint.json"

    def _load_checkpoint(self, client_id: str) -> dict:
        if not self.resume:
            return {}
        cp_path = self._get_checkpoint_path(client_id)
        if cp_path.exists():
            try:
                data = json.loads(cp_path.read_text(encoding="utf-8"))
                check_schema_version(data, source=f"checkpoint:{client_id}")
                self.log(f"  [green]Loaded checkpoint (stage {data.get('completed_stage', 0)})[/green]")
                # Validate consistency hash against evidence store on disk
                saved_hash = data.get("_consistency_hash", "")
                if saved_hash and hasattr(self, "evidence_store"):
                    es_path = self.output_dir / client_id / "02_investigation" / "evidence_store.json"
                    if es_path.exists():
                        try:
                            disk_records = json.loads(es_path.read_text(encoding="utf-8"))
                            expected = f"stage={data.get('completed_stage', 0)};ev={len(disk_records)}"
                            if saved_hash != expected:
                                self.log(
                                    "  [yellow]Checkpoint may be stale — evidence store "
                                    "modified since last save[/yellow]"
                                )
                                logger.warning(
                                    "Checkpoint hash mismatch: saved=%s, computed=%s",
                                    saved_hash, expected,
                                )
                        except (json.JSONDecodeError, OSError) as e:
                            logger.debug("Checkpoint hash validation skipped: %s", e)
                return data
            except Exception as e:
                self.log(f"  [yellow]Could not load checkpoint: {e}[/yellow]")
        return {}

    def _save_checkpoint(self, client_id: str, data: dict):
        from utilities.file_ops import atomic_write_json
        cp_path = self._get_checkpoint_path(client_id)
        # Store consistency hash for stale-checkpoint detection
        ev_count = 0
        if hasattr(self, "evidence_store"):
            ev_count = len(self.evidence_store)
        data["_consistency_hash"] = f"stage={data.get('completed_stage', 0)};ev={ev_count}"
        atomic_write_json(cp_path, data)

    def _serialize_investigation(self, investigation: InvestigationResults) -> dict:
        """Serialize investigation results for checkpoint."""
        data = {}
        for field_name in [
            "individual_sanctions", "pep_classification", "individual_adverse_media",
            "entity_verification", "entity_sanctions", "business_adverse_media",
            "jurisdiction_risk", "transaction_monitoring",
        ]:
            val = getattr(investigation, field_name, None)
            data[field_name] = val.model_dump(mode="json") if val else None

        for field_name in [
            "id_verification", "suitability_assessment", "fatca_crs",
            "edd_requirements", "compliance_actions", "business_risk_assessment",
            "document_requirements", "misrepresentation_detection", "sar_risk_assessment",
        ]:
            data[field_name] = getattr(investigation, field_name, None)

        data["ubo_screening"] = investigation.ubo_screening
        data["failed_agents"] = investigation.failed_agents
        data["is_degraded"] = investigation.is_degraded
        return data

    def _deserialize_investigation(self, data: dict) -> InvestigationResults:
        """Deserialize investigation results from checkpoint."""
        results = InvestigationResults()

        model_map = {
            "individual_sanctions": SanctionsResult,
            "pep_classification": PEPClassification,
            "individual_adverse_media": AdverseMediaResult,
            "entity_verification": EntityVerification,
            "entity_sanctions": SanctionsResult,
            "business_adverse_media": AdverseMediaResult,
            "jurisdiction_risk": JurisdictionRiskResult,
            "transaction_monitoring": TransactionMonitoringResult,
        }

        for field_name, model_class in model_map.items():
            val = data.get(field_name)
            if val:
                try:
                    setattr(results, field_name, model_class(**val))
                except Exception as e:
                    logger.warning(f"Could not deserialize {field_name}: {e}")

        for field_name in [
            "id_verification", "suitability_assessment", "fatca_crs",
            "edd_requirements", "compliance_actions", "business_risk_assessment",
            "document_requirements", "misrepresentation_detection", "sar_risk_assessment",
        ]:
            setattr(results, field_name, data.get(field_name))

        results.ubo_screening = data.get("ubo_screening", {})
        results.failed_agents = data.get("failed_agents", [])
        results.is_degraded = data.get("is_degraded", False)
        return results
