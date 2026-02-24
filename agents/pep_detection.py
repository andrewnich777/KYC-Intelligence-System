"""
PEP Detection Agent.
Classifies individuals per FINTRAC PEP categories.
"""

import re as _re

from agents.base import BaseAgent, _safe_parse_enum, load_prompt_template
from logger import get_logger
from models import Confidence, DispositionStatus, EvidenceClass, EvidenceRecord, PEPClassification, PEPLevel
from utilities.ai_coercion import coerce_dict_values

logger = get_logger(__name__)


class PEPDetectionAgent(BaseAgent):
    """Detect and classify Politically Exposed Persons."""

    @property
    def name(self) -> str:
        return "PEPDetection"

    @property
    def system_prompt(self) -> str:
        return load_prompt_template("pep_detection")

    @property
    def tools(self) -> list[str]:
        return ["web_search", "web_fetch"]

    async def research(self, full_name: str, citizenship: str = None,
                       pep_self_declaration: bool = False,
                       pep_details: str = None) -> PEPClassification:
        """Detect PEP status for an individual."""
        verify_msg = "Verify the self-declaration — search for their political role"
        search_msg = "Search for any political positions held"
        step1 = verify_msg if pep_self_declaration else search_msg

        prompt = f"""Determine the PEP (Politically Exposed Person) status of this individual:

Name: {full_name}
Citizenship: {citizenship or 'Not provided'}
Self-declared PEP: {pep_self_declaration}
Self-declared details: {pep_details or 'None provided'}

Steps:
1. {step1}
2. Search for government positions, political appointments, military rank
3. Search for connections to known PEPs (family/associate)
4. Classify per FINTRAC categories
5. Determine if EDD is required

For domestic PEPs: check if they left office within the last 5 years.
For foreign PEPs: EDD is permanent regardless of when they left office."""

        result = await self.run(prompt)
        return self._parse_result(result, full_name, pep_self_declaration)

    def _parse_result(self, result: dict, entity_name: str, self_declared: bool) -> PEPClassification:
        """Parse agent response into PEPClassification."""
        data = result.get("json", {})
        if not data:
            # Check text for clear signals before defaulting
            text = result.get("text", "").lower()
            clear_signals = ["not a pep", "no political", "no pep status",
                             "not politically exposed", "no government position"]
            is_clear = any(s in text for s in clear_signals)
            if is_clear:
                record = self._build_clear_record(
                    "pep_clear", entity_name,
                    "PEP screening completed — no PEP status detected",
                    disposition_reasoning="Agent prose indicates no PEP status found",
                )
                disposition = DispositionStatus.CLEAR
            else:
                record = EvidenceRecord(
                    evidence_id="pep_no_json",
                    source_type="agent",
                    source_name=self.name,
                    entity_screened=entity_name,
                    claim="PEP screening completed — agent did not return structured data",
                    evidence_level=EvidenceClass.INFERRED,
                    disposition=DispositionStatus.PENDING_REVIEW,
                    confidence=Confidence.LOW,
                    disposition_reasoning="Agent did not return structured data and prose lacks clear signals — manual review required",
                )
                disposition = DispositionStatus.PENDING_REVIEW
            return PEPClassification(
                entity_screened=entity_name,
                self_declared=self_declared,
                detected_level=PEPLevel.NOT_PEP,
                edd_required=disposition != DispositionStatus.CLEAR,
                evidence_records=[record],
            )

        level = _safe_parse_enum(PEPLevel, data.get("detected_level", "NOT_PEP"), PEPLevel.NOT_PEP)

        # EDD timeline calculation
        edd_permanent = False
        edd_expiry_date = None
        if level == PEPLevel.FOREIGN_PEP:
            edd_permanent = True
        elif level in (PEPLevel.DOMESTIC_PEP, PEPLevel.HIO):
            positions = data.get("positions_found", [])
            latest_end = None
            for pos in positions:
                dates = str(pos.get("dates", ""))
                if "present" in dates.lower() or "current" in dates.lower():
                    edd_permanent = True
                    break
                years = _re.findall(r'\b(?:19|20)\d{2}\b', dates)
                if years:
                    end_year = max(int(y) for y in years)
                    if latest_end is None or end_year > latest_end:
                        latest_end = end_year
            if not edd_permanent and latest_end:
                edd_expiry_date = f"{latest_end + 5}-01-01"
        elif level in (PEPLevel.PEP_FAMILY, PEPLevel.PEP_ASSOCIATE):
            edd_permanent = True

        records = self._build_evidence_records(data, entity_name, level)
        # Cross-check: if all evidence records are CLEAR, override level to NOT_PEP
        if records and all(
            getattr(r, 'disposition', None) == DispositionStatus.CLEAR for r in records
        ):
            level = PEPLevel.NOT_PEP

        # Bidirectional cross-check: if NOT_PEP but evidence has non-CLEAR records,
        # require EDD as a precaution
        edd_default = level != PEPLevel.NOT_PEP
        if level == PEPLevel.NOT_PEP and records and any(
            getattr(r, 'disposition', DispositionStatus.CLEAR) != DispositionStatus.CLEAR
            for r in records
        ):
            edd_default = True

        pep = PEPClassification(
            entity_screened=data.get("entity_screened", entity_name),
            self_declared=data.get("self_declared", self_declared),
            detected_level=level,
            positions_found=[
                coerce_dict_values(pos)
                for pos in data.get("positions_found", [])
                if isinstance(pos, dict)
            ],
            family_associations=data.get("family_associations", []),
            edd_required=data.get("edd_required", edd_default),
            edd_expiry_date=edd_expiry_date,
            edd_permanent=edd_permanent,
            evidence_records=records,
        )
        self._attach_search_queries(pep, result)
        self._attach_fetched_urls(pep.evidence_records, result)
        return pep

    def _build_evidence_records(self, data: dict, entity_name: str, level: PEPLevel) -> list[EvidenceRecord]:
        records = []
        fetched = list(self._fetched_urls) if self._fetched_urls else []

        if level != PEPLevel.NOT_PEP:
            for i, pos in enumerate(data.get("positions_found", [])):
                # Extract claim-specific URL from position data if available
                pos_urls = []
                if isinstance(pos, dict):
                    for key in ("url", "source_url", "link"):
                        if pos.get(key):
                            pos_urls.append(pos[key])
                urls = pos_urls or fetched
                records.append(self._build_finding_record(
                    f"pep_{i}", entity_name,
                    f"PEP position: {pos.get('position', 'unknown')} at {pos.get('organization', 'unknown')}",
                    [pos],
                    source_urls=urls,
                ))
            # Build evidence records for family associations
            for j, assoc in enumerate(data.get("family_associations", [])):
                assoc_urls = []
                if isinstance(assoc, dict):
                    for key in ("url", "source_url", "link"):
                        if assoc.get(key):
                            assoc_urls.append(assoc[key])
                    name = assoc.get("name", assoc.get("full_name", "unknown"))
                    relationship = assoc.get("relationship", "unknown")
                else:
                    name = str(assoc)
                    relationship = "unknown"
                records.append(self._build_finding_record(
                    f"pep_family_{j}", entity_name,
                    f"PEP family association: {name} ({relationship})",
                    [assoc] if isinstance(assoc, dict) else [{"name": name}],
                    source_urls=assoc_urls or fetched,
                ))
        else:
            records.append(self._build_clear_record(
                "pep_clear", entity_name,
                "No PEP status detected",
                source_urls=fetched,
            ))
        return records
