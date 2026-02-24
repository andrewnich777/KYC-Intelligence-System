"""
Jurisdiction Risk Assessment Agent.
Shared agent for FATF status, OFAC programs, FINTRAC directives, CRS participation.
"""

from agents.base import BaseAgent, _safe_parse_enum, load_prompt_template
from logger import get_logger
from models import Confidence, DispositionStatus, EvidenceClass, EvidenceRecord, JurisdictionRiskResult, RiskLevel

logger = get_logger(__name__)


class JurisdictionRiskAgent(BaseAgent):
    """Assess jurisdiction-level AML/CFT risk."""

    @property
    def name(self) -> str:
        return "JurisdictionRisk"

    @property
    def system_prompt(self) -> str:
        return load_prompt_template("jurisdiction_risk")

    @property
    def tools(self) -> list[str]:
        return ["web_search", "web_fetch"]

    async def research(self, jurisdictions: list[str]) -> JurisdictionRiskResult:
        """Assess risk for a list of jurisdictions."""
        # Provide known Basel AML Index scores as structured context
        from utilities.reference_data import BASEL_AML_INDEX, EU_HIGH_RISK_THIRD_COUNTRIES
        known_scores = {j: BASEL_AML_INDEX[j] for j in jurisdictions if j in BASEL_AML_INDEX}
        eu_flagged = [j for j in jurisdictions if j in EU_HIGH_RISK_THIRD_COUNTRIES]
        context_lines = []
        if known_scores:
            context_lines.append("Basel AML Index scores (0-10, higher=more risk):")
            for country, score in known_scores.items():
                context_lines.append(f"  - {country}: {score}")
        if eu_flagged:
            context_lines.append(f"EU High-Risk Third Countries on this list: {', '.join(eu_flagged)}")
        context_block = chr(10).join(context_lines) if context_lines else ""

        prompt = f"""Assess AML/CFT risk for these jurisdictions:

{chr(10).join(f'- {j}' for j in jurisdictions)}

{context_block}

For EACH jurisdiction:
1. Check current FATF grey/black list status
2. Check active OFAC sanctions programs
3. Check for FINTRAC directives
4. Look up Corruption Perception Index (CPI) score and rank
5. Look up Basel AML Index score if available (reference scores provided above)
6. Check if the jurisdiction is on the EU High-Risk Third Countries list
7. Assess overall AML framework strength

Include per-jurisdiction details with CPI and Basel scores.
Provide an overall jurisdiction risk level."""

        result = await self.run(prompt)
        return self._parse_result(result, jurisdictions)

    def _parse_result(self, result: dict, jurisdictions: list) -> JurisdictionRiskResult:
        data = result.get("json", {})
        if not data:
            # Check text for clear signals before defaulting
            text = result.get("text", "").lower()
            clear_signals = ["low risk", "standard risk", "no elevated",
                             "standard jurisdiction", "clean jurisdiction"]
            is_clear = any(s in text for s in clear_signals)
            if is_clear:
                record = self._build_clear_record(
                    "jur_clear", ", ".join(jurisdictions),
                    "All jurisdictions assessed as standard risk",
                    disposition_reasoning="Agent prose indicates standard jurisdiction risk",
                )
                level = RiskLevel.LOW
            else:
                record = EvidenceRecord(
                    evidence_id="jur_no_json",
                    source_type="agent",
                    source_name=self.name,
                    entity_screened=", ".join(jurisdictions),
                    claim="Jurisdiction risk assessment completed — agent did not return structured data",
                    evidence_level=EvidenceClass.INFERRED,
                    disposition=DispositionStatus.PENDING_REVIEW,
                    confidence=Confidence.LOW,
                    disposition_reasoning="Agent did not return structured data and prose lacks clear signals — manual review required",
                )
                level = RiskLevel.MEDIUM
            jr = JurisdictionRiskResult(
                jurisdictions_assessed=jurisdictions,
                overall_jurisdiction_risk=level,
                evidence_records=[record],
            )
            self._attach_search_queries(jr, result)
            self._attach_fetched_urls(jr.evidence_records, result)
            return jr

        def _country_key(c: str) -> str:
            return c.lower().replace(" ", "_")[:20]

        records = []
        fetched = list(self._fetched_urls) if self._fetched_urls else []

        # FATF evidence records
        ai_grey = set(data.get("fatf_grey_list", []))
        ai_black = set(data.get("fatf_black_list", []))
        for country in ai_grey:
            records.append(self._build_finding_record(
                f"jur_grey_{_country_key(country)}", country,
                f"{country} is on FATF grey list (increased monitoring)",
                [{"source": "FATF", "list": "grey_list", "country": country}],
                evidence_level=EvidenceClass.SOURCED,
                confidence=Confidence.HIGH,
                source_urls=fetched,
            ))
        for country in ai_black:
            records.append(self._build_finding_record(
                f"jur_black_{_country_key(country)}", country,
                f"{country} is on FATF black list (call for action)",
                [{"source": "FATF", "list": "black_list", "country": country}],
                evidence_level=EvidenceClass.SOURCED,
                confidence=Confidence.HIGH,
                source_urls=fetched,
            ))

        # OFAC sanctions program evidence records
        for prog in data.get("sanctions_programs", []):
            if isinstance(prog, dict):
                prog_name = prog.get("program", prog.get("name", "Unknown"))
                prog_country = prog.get("country", "Unknown")
            else:
                prog_name = str(prog)
                prog_country = "Unknown"
            records.append(self._build_finding_record(
                f"jur_ofac_{_country_key(prog_country)}", prog_country,
                f"OFAC sanctions program: {prog_name}",
                [prog] if isinstance(prog, dict) else [{"program": prog_name}],
                evidence_level=EvidenceClass.SOURCED,
                confidence=Confidence.HIGH,
                source_urls=fetched,
            ))

        # FINTRAC directive evidence records
        for directive in data.get("fintrac_directives", []):
            d_str = str(directive)
            records.append(self._build_finding_record(
                f"jur_fintrac_{_country_key(d_str)}", d_str,
                f"FINTRAC directive: {d_str}",
                [{"directive": d_str}],
                evidence_level=EvidenceClass.SOURCED,
                confidence=Confidence.HIGH,
                source_urls=fetched,
            ))

        # Deterministic cross-check: inject reference data the AI may have missed
        from utilities.reference_data import (
            FATF_BLACK_LIST,
            FATF_GREY_LIST,
            OFAC_SANCTIONED_COUNTRIES,
        )
        assessed = set(data.get("jurisdictions_assessed", jurisdictions))
        for country in assessed:
            if country in FATF_BLACK_LIST and country not in ai_black:
                ai_black.add(country)
                records.append(self._build_finding_record(
                    f"jur_black_{_country_key(country)}", country,
                    f"{country} is on FATF black list (injected from reference data)",
                    [{"source": "FATF_reference", "list": "black_list", "country": country}],
                    evidence_level=EvidenceClass.SOURCED,
                    confidence=Confidence.HIGH,
                ))
            elif country in FATF_GREY_LIST and country not in ai_grey:
                ai_grey.add(country)
                records.append(self._build_finding_record(
                    f"jur_grey_{_country_key(country)}", country,
                    f"{country} is on FATF grey list (injected from reference data)",
                    [{"source": "FATF_reference", "list": "grey_list", "country": country}],
                    evidence_level=EvidenceClass.SOURCED,
                    confidence=Confidence.HIGH,
                ))
            if country in OFAC_SANCTIONED_COUNTRIES:
                # Check if we already have an OFAC record for this country
                existing_ofac = any(
                    f"jur_ofac_{_country_key(country)}" in getattr(r, 'evidence_id', '')
                    for r in records
                )
                if not existing_ofac:
                    records.append(self._build_finding_record(
                        f"jur_ofac_{_country_key(country)}", country,
                        f"{country} has active OFAC sanctions program (from reference data)",
                        [{"source": "OFAC_reference", "country": country}],
                        evidence_level=EvidenceClass.SOURCED,
                        confidence=Confidence.HIGH,
                    ))

        if not records:
            records.append(self._build_clear_record(
                "jur_clear", ", ".join(jurisdictions),
                "All jurisdictions assessed as standard risk",
                source_urls=fetched,
            ))

        # Derive jurisdiction risk level: if any findings exist, use AI level; else LOW
        if records and any(
            getattr(r, 'disposition', DispositionStatus.CLEAR) != DispositionStatus.CLEAR
            for r in records
        ):
            level = _safe_parse_enum(RiskLevel, data.get("overall_jurisdiction_risk", "MEDIUM"), RiskLevel.MEDIUM)
        else:
            level = _safe_parse_enum(RiskLevel, data.get("overall_jurisdiction_risk", "LOW"), RiskLevel.LOW)

        # Build jurisdiction_details from agent response or fallback from FATF lists
        jurisdiction_details = data.get("jurisdiction_details", [])
        if not jurisdiction_details:
            for country in data.get("jurisdictions_assessed", jurisdictions):
                fatf_status = "clean"
                if country in ai_black:
                    fatf_status = "black_list"
                elif country in ai_grey:
                    fatf_status = "grey_list"
                jurisdiction_details.append({
                    "country": country,
                    "fatf_status": fatf_status,
                    "cpi_score": None,
                    "basel_aml_score": None,
                })

        # Merge reference data grey/black with AI lists
        final_grey = sorted(ai_grey)
        final_black = sorted(ai_black)

        jr = JurisdictionRiskResult(
            jurisdictions_assessed=data.get("jurisdictions_assessed", jurisdictions),
            fatf_grey_list=final_grey,
            fatf_black_list=final_black,
            sanctions_programs=data.get("sanctions_programs", []),
            fintrac_directives=data.get("fintrac_directives", []),
            overall_jurisdiction_risk=level,
            jurisdiction_details=jurisdiction_details,
            evidence_records=records,
        )
        self._attach_search_queries(jr, result)
        self._attach_fetched_urls(jr.evidence_records, result)
        return jr
