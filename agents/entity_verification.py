"""
Entity Verification Agent.
Business registration + beneficial ownership verification.
"""

from agents.base import BaseAgent, load_prompt_template
from logger import get_logger
from models import Confidence, DispositionStatus, EntityVerification, EvidenceClass, EvidenceRecord

logger = get_logger(__name__)


class EntityVerificationAgent(BaseAgent):
    """Verify business entity registration and ownership structure."""

    @property
    def name(self) -> str:
        return "EntityVerification"

    @property
    def system_prompt(self) -> str:
        return load_prompt_template("entity_verification")

    @property
    def tools(self) -> list[str]:
        return ["web_search", "web_fetch"]

    async def research(self, legal_name: str, jurisdiction: str = None,
                       business_number: str = None,
                       declared_ubos: list = None) -> EntityVerification:
        """Verify a business entity."""
        ubo_str = ""
        if declared_ubos:
            ubo_lines = []
            for u in declared_ubos:
                name = u.get("full_name", u) if isinstance(u, dict) else u
                ubo_lines.append(f"  - {name}")
            ubo_str = "\nDeclared Beneficial Owners:\n" + "\n".join(ubo_lines)

        prompt = f"""Verify this business entity:

Legal Name: {legal_name}
Jurisdiction: {jurisdiction or 'Not provided'}
Business Number: {business_number or 'Not provided'}""" + ubo_str + """

Steps:
1. Search Canadian corporate registries:
   - Corporations Canada / CBCA beneficial ownership registry (federal)
   - Provincial: ONBIS (Ontario), BC Registry Services, REQ (Quebec), Alberta Corporate Registry
   - SEDAR+ if reporting issuer; FINTRAC MSB Registry if MSB; CIRO NRD for registrant verification
2. Search OpenCorporates for the entity
3. Verify registration status and details
4. Cross-reference beneficial ownership if public records available
5. Flag any discrepancies"""

        result = await self.run(prompt)
        return self._parse_result(result, legal_name)

    def _parse_result(self, result: dict, entity_name: str) -> EntityVerification:
        data = result.get("json", {})
        if not data:
            # Check text for clear signals before defaulting
            text = result.get("text", "").lower()
            clear_signals = ["verified", "registration confirmed", "entity confirmed",
                             "active registration", "good standing"]
            is_clear = any(s in text for s in clear_signals)
            if is_clear:
                record = self._build_clear_record(
                    "ev_clear", entity_name,
                    "Entity verification completed — no discrepancies identified",
                    disposition_reasoning="Agent prose indicates entity verified",
                )
            else:
                record = EvidenceRecord(
                    evidence_id="ev_no_json",
                    source_type="agent",
                    source_name=self.name,
                    entity_screened=entity_name,
                    claim="Entity verification completed — agent did not return structured data",
                    evidence_level=EvidenceClass.INFERRED,
                    disposition=DispositionStatus.PENDING_REVIEW,
                    confidence=Confidence.LOW,
                    disposition_reasoning="Agent did not return structured data and prose lacks clear signals — manual review required",
                )
            ev = EntityVerification(
                entity_name=entity_name,
                evidence_records=[record],
            )
            self._attach_search_queries(ev, result)
            self._attach_fetched_urls(ev.evidence_records, result)
            return ev

        verified = data.get("verified_registration", False)
        fetched = list(self._fetched_urls) if self._fetched_urls else []

        records = []
        records.append(self._build_finding_record(
            "ev_reg_0", entity_name,
            "Entity registration: " + ("Verified" if verified else "Not verified"),
            [data.get("registration_details", {})],
            evidence_level=EvidenceClass.SOURCED if verified else EvidenceClass.UNKNOWN,
            disposition=DispositionStatus.CLEAR if verified else DispositionStatus.PENDING_REVIEW,
            confidence=Confidence.HIGH if verified else Confidence.LOW,
            source_urls=fetched,
        ))

        for i, disc in enumerate(data.get("discrepancies", [])):
            records.append(self._build_finding_record(
                f"ev_disc_{i}", entity_name,
                f"Discrepancy: {disc}",
                source_urls=fetched,
            ))

        # UBO structure verification evidence record
        ubo_verified = data.get("ubo_structure_verified", False)
        if ubo_verified:
            records.append(self._build_finding_record(
                "ev_ubo_verified", entity_name,
                "UBO structure verified against corporate registry",
                [{"ubo_structure_verified": True}],
                evidence_level=EvidenceClass.SOURCED,
                disposition=DispositionStatus.CLEAR,
                confidence=Confidence.MEDIUM,
                source_urls=fetched,
            ))
        elif data.get("discrepancies") or not verified:
            records.append(self._build_finding_record(
                "ev_ubo_unverified", entity_name,
                "UBO structure could not be independently verified",
                [{"ubo_structure_verified": False}],
                evidence_level=EvidenceClass.INFERRED,
                disposition=DispositionStatus.PENDING_REVIEW,
                confidence=Confidence.LOW,
                source_urls=fetched,
            ))

        ev = EntityVerification(
            entity_name=data.get("entity_name", entity_name),
            verified_registration=verified,
            registry_sources=data.get("registry_sources", []),
            registration_details=data.get("registration_details", {}),
            ubo_structure_verified=data.get("ubo_structure_verified", False),
            discrepancies=data.get("discrepancies", []),
            evidence_records=records,
        )
        self._attach_search_queries(ev, result)
        self._attach_fetched_urls(ev.evidence_records, result)
        return ev
