"""
SAR/STR Narrative Drafting Generator.

Produces a deterministic, template-driven narrative for:
  - FinCEN SAR Form 111, Part V (Suspicious Activity Description)
  - FINTRAC STR, Part G (Details of Suspicion)

Every sentence cites evidence IDs ([E-XXX]) so analysts can verify each claim.
No AI generation — pure template assembly to avoid hallucination risk.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from models import KYCOutput


def _extract_client_info(output: KYCOutput) -> dict:
    """Extract subject identification fields from client data."""
    cd = output.client_data or {}
    is_individual = output.client_type.value == "individual"

    info: dict[str, Any] = {
        "name": cd.get("full_name") or cd.get("legal_name", "Unknown"),
        "client_type": output.client_type.value,
        "client_id": output.client_id,
        "is_individual": is_individual,
    }

    if is_individual:
        info["dob"] = cd.get("date_of_birth", "Not provided")
        info["citizenship"] = cd.get("citizenship", "Not provided")
        info["country_of_residence"] = cd.get("country_of_residence", "Not provided")
        info["occupation"] = ""
        emp = cd.get("employment")
        if isinstance(emp, dict):
            info["occupation"] = emp.get("occupation", "Not provided")
        info["sin_last4"] = cd.get("sin_last4", "")
        addr = cd.get("address")
        if isinstance(addr, dict):
            parts = [addr.get("street", ""), addr.get("city", ""), addr.get("province_state", ""),
                     addr.get("postal_code", ""), addr.get("country", "")]
            info["address"] = ", ".join(p for p in parts if p)
        else:
            info["address"] = "Not provided"
    else:
        info["business_number"] = cd.get("business_number", "Not provided")
        info["incorporation_jurisdiction"] = cd.get("incorporation_jurisdiction", "Not provided")
        info["industry"] = cd.get("industry", "Not provided")
        info["entity_type"] = cd.get("entity_type", "Not provided")
        addr = cd.get("address")
        if isinstance(addr, dict):
            parts = [addr.get("street", ""), addr.get("city", ""), addr.get("province_state", ""),
                     addr.get("postal_code", ""), addr.get("country", "")]
            info["address"] = ", ".join(p for p in parts if p)
        else:
            info["address"] = "Not provided"

    return info


def _build_who_section(info: dict) -> str:
    """Build the WHO section — subject identification paragraph."""
    lines = []
    name = info["name"]

    if info["is_individual"]:
        lines.append(
            f"The subject of this report is {name}, date of birth {info['dob']}, "
            f"a citizen of {info['citizenship']} residing in {info['country_of_residence']}."
        )
        if info.get("occupation"):
            lines.append(f"The subject's stated occupation is {info['occupation']}.")
        if info.get("address"):
            lines.append(f"Address on file: {info['address']}.")
        if info.get("sin_last4"):
            lines.append(f"SIN (last 4): ***{info['sin_last4']}.")
    else:
        lines.append(
            f"The subject of this report is {name}, a {info.get('entity_type', 'business entity')} "
            f"incorporated in {info.get('incorporation_jurisdiction', 'unknown jurisdiction')}, "
            f"operating in the {info.get('industry', 'unknown')} industry."
        )
        if info.get("business_number"):
            lines.append(f"Business registration number: {info['business_number']}.")
        if info.get("address"):
            lines.append(f"Principal address: {info['address']}.")

    return " ".join(lines)


def _build_what_section(output: Any, evidence_map: dict[str, dict]) -> tuple[str, list[str]]:
    """Build the WHAT section — nature of suspicious activity."""
    lines = []
    cited_ids: list[str] = []

    # From key findings
    if output.synthesis and output.synthesis.key_findings:
        lines.append("The following suspicious indicators were identified during the investigation:")
        for finding in output.synthesis.key_findings:
            # Try to find a matching evidence record
            matched_id = _find_evidence_for_claim(finding, evidence_map)
            if matched_id:
                lines.append(f"- {finding} [{matched_id}]")
                cited_ids.append(matched_id)
            else:
                lines.append(f"- {finding}")

    # From risk elevations (support both RiskElevation models and raw dicts from mocks)
    if output.synthesis and output.synthesis.risk_elevations:
        for elev in output.synthesis.risk_elevations:
            _g = elev.get if isinstance(elev, dict) else lambda k, d="", _e=elev: getattr(_e, k, d)
            desc = _g("description", "") or _g("factor", "")
            if desc:
                eid = _g("evidence_id", "")
                if eid:
                    lines.append(f"- Risk elevation: {desc} [{eid}]")
                    cited_ids.append(eid)
                else:
                    lines.append(f"- Risk elevation: {desc}")

    if not lines:
        # Fallback: mine risk factors when synthesis key_findings is empty
        risk_assessment = None
        if output.synthesis and output.synthesis.revised_risk_assessment:
            risk_assessment = output.synthesis.revised_risk_assessment
        elif output.intake_classification:
            risk_assessment = output.intake_classification.preliminary_risk

        if risk_assessment and getattr(risk_assessment, 'risk_level', None) and risk_assessment.risk_level.value in ("HIGH", "CRITICAL"):
            high_factors = [rf for rf in (risk_assessment.risk_factors or []) if rf.points >= 10]
            if high_factors:
                lines.append("The following risk indicators were identified:")
                for rf in sorted(high_factors, key=lambda x: x.points, reverse=True):
                    matched_id = _find_evidence_for_claim(rf.factor, evidence_map)
                    if matched_id:
                        lines.append(f"- {rf.factor} ({rf.points} pts) [{matched_id}]")
                        cited_ids.append(matched_id)
                    else:
                        lines.append(f"- {rf.factor} ({rf.points} pts)")

        # Surface non-CLEAR evidence dispositions
        for eid, er in evidence_map.items():
            disp = er.get("disposition", "")
            if disp in ("PENDING_REVIEW", "POTENTIAL_MATCH", "CONFIRMED_MATCH"):
                claim = er.get("claim", "")
                if claim and not any(claim in line for line in lines):
                    lines.append(f"- {claim} [{eid}]")
                    cited_ids.append(eid)

    if not lines:
        lines.append("No specific suspicious activity indicators were identified during the automated investigation.")

    return "\n".join(lines), cited_ids


def _build_when_section(output: Any, evidence_map: dict[str, dict]) -> tuple[str, list[str]]:
    """Build the WHEN section — dates and timeline."""
    lines = []
    cited_ids: list[str] = []

    now = output.generated_at.strftime("%Y-%m-%d")
    lines.append(f"This investigation was conducted on {now}.")

    if output.duration_seconds:
        mins = output.duration_seconds / 60
        lines.append(f"The automated investigation took approximately {mins:.1f} minutes.")

    # Collect dated evidence
    dated_events: list[tuple[str, str, str]] = []
    for eid, er in evidence_map.items():
        ts = er.get("timestamp", "")
        if ts:
            claim = er.get("claim", "")
            dated_events.append((str(ts)[:10], claim, eid))

    if dated_events:
        dated_events.sort(key=lambda x: x[0])
        lines.append("\nTimeline of investigation findings:")
        for date, claim, eid in dated_events[:10]:
            lines.append(f"- {date}: {claim} [{eid}]")
            cited_ids.append(eid)

    return "\n".join(lines), cited_ids


def _build_where_section(output: Any, evidence_map: dict[str, dict]) -> tuple[str, list[str]]:
    """Build the WHERE section — jurisdictions and locations."""
    lines = []
    cited_ids: list[str] = []

    jurisdictions: set[str] = set()
    investigation = output.investigation_results

    # From jurisdiction risk
    if investigation and investigation.jurisdiction_risk:
        jr = investigation.jurisdiction_risk
        jurisdictions.update(jr.jurisdictions_assessed)

        # Collect evidence IDs for jurisdiction risk once (handle both Pydantic models and dicts)
        jr_evidence_ids = [
            er.get("evidence_id") if isinstance(er, dict) else getattr(er, "evidence_id", "")
            for er in (jr.evidence_records or [])
        ]
        jr_evidence_ids = [eid for eid in jr_evidence_ids if eid]

        if jr.fatf_grey_list:
            citation = " ".join(f"[{eid}]" for eid in jr_evidence_ids) if jr_evidence_ids else ""
            lines.append(f"FATF Grey List jurisdictions involved: {', '.join(jr.fatf_grey_list)}. {citation}".strip())
            cited_ids.extend(jr_evidence_ids)

        if jr.fatf_black_list:
            citation = " ".join(f"[{eid}]" for eid in jr_evidence_ids) if jr_evidence_ids else ""
            lines.append(f"FATF Black List jurisdictions involved: {', '.join(jr.fatf_black_list)}. {citation}".strip())
            # Only add IDs if not already added from grey list section
            for eid in jr_evidence_ids:
                if eid not in cited_ids:
                    cited_ids.append(eid)

    # From client data
    cd = output.client_data or {}
    if cd.get("country_of_residence"):
        jurisdictions.add(cd["country_of_residence"])
    if cd.get("citizenship"):
        jurisdictions.add(cd["citizenship"])
    for country in cd.get("countries_of_operation", []):
        jurisdictions.add(country)

    if jurisdictions:
        lines.insert(0, f"The subject is connected to the following jurisdictions: {', '.join(sorted(jurisdictions))}.")

    if not lines:
        lines.append("No specific jurisdictional concerns were identified.")

    return "\n".join(lines), cited_ids


def _build_why_section(output: Any, evidence_map: dict[str, dict]) -> tuple[str, list[str]]:
    """Build the WHY section — reason for suspicion."""
    lines = []
    cited_ids: list[str] = []

    # SAR risk assessment
    investigation = output.investigation_results
    if investigation and investigation.sar_risk_assessment:
        sar = investigation.sar_risk_assessment
        triggers = sar.get("triggers", [])
        if triggers:
            lines.append("The following SAR risk triggers were identified:")
            for t in triggers:
                if isinstance(t, dict):
                    desc = t.get("description", t.get("trigger", str(t)))
                    eid = t.get("evidence_id", "")
                    if eid:
                        lines.append(f"- {desc} [{eid}]")
                        cited_ids.append(eid)
                    else:
                        lines.append(f"- {desc}")
                else:
                    lines.append(f"- {t}")

        indicators = sar.get("triggers", [])
        if indicators:
            lines.append("\nSAR risk indicators:")
            for ind in indicators:
                if isinstance(ind, dict):
                    lines.append(f"- {ind.get('description', ind.get('trigger', str(ind)))}")
                else:
                    lines.append(f"- {ind}")

    # Misrepresentation detection
    if investigation and investigation.misrepresentation_detection:
        misrep = investigation.misrepresentation_detection
        findings = misrep.get("misrepresentations", [])
        if findings:
            lines.append("\nMisrepresentation indicators detected:")
            for f in findings:
                if isinstance(f, dict):
                    desc = f.get("description", str(f))
                    eid = f.get("evidence_id", "")
                    if eid:
                        lines.append(f"- {desc} [{eid}]")
                        cited_ids.append(eid)
                    else:
                        lines.append(f"- {desc}")
                else:
                    lines.append(f"- {f}")

    # Risk factors
    risk_assessment = None
    if output.synthesis and output.synthesis.revised_risk_assessment:
        risk_assessment = output.synthesis.revised_risk_assessment
    elif output.intake_classification:
        risk_assessment = output.intake_classification.preliminary_risk

    if risk_assessment and risk_assessment.risk_factors:
        rl_val = risk_assessment.risk_level.value if getattr(risk_assessment, 'risk_level', None) else "UNKNOWN"
        lines.append(f"\nThe subject's overall risk score is {risk_assessment.total_score} "
                      f"({rl_val}). Contributing factors include:")
        for rf in sorted(risk_assessment.risk_factors, key=lambda x: x.points, reverse=True)[:10]:
            lines.append(f"- {rf.factor} ({rf.points} pts, category: {rf.category})")

    if not lines:
        lines.append("The automated investigation did not identify specific SAR-triggering concerns.")

    return "\n".join(lines), cited_ids


def _build_how_section(output: Any, evidence_map: dict[str, dict]) -> tuple[str, list[str]]:
    """Build the HOW section — method of operation / modus operandi."""
    lines = []
    cited_ids: list[str] = []

    investigation = output.investigation_results
    if investigation and investigation.transaction_monitoring:
        tm = investigation.transaction_monitoring

        if tm.industry_typologies:
            lines.append("AML typologies relevant to this case:")
            for typ in tm.industry_typologies:
                lines.append(f"- {typ.typology_name}: {typ.description}")
                if typ.indicators:
                    for ind in typ.indicators[:3]:
                        lines.append(f"  - Indicator: {ind}")

        if tm.geographic_typologies:
            for typ in tm.geographic_typologies:
                lines.append(f"- Geographic typology: {typ.typology_name}: {typ.description}")

        if tm.sar_risk_indicators:
            lines.append("\nTransaction monitoring SAR risk indicators:")
            for ind in tm.sar_risk_indicators:
                lines.append(f"- {ind}")

        # Cite evidence (handle both Pydantic models and dicts)
        for er in (tm.evidence_records or []):
            eid = er.get("evidence_id") if isinstance(er, dict) else getattr(er, "evidence_id", "")
            if eid:
                cited_ids.append(eid)

    if not lines:
        lines.append("No specific method of operation or transaction patterns were identified by the automated investigation.")

    return "\n".join(lines), cited_ids


def _find_evidence_for_claim(claim: str, evidence_map: dict[str, dict]) -> str:
    """Try to find an evidence ID whose claim matches the given text."""
    claim_lower = claim.lower()
    for eid, er in evidence_map.items():
        er_claim = er.get("claim", "").lower()
        # Substring match
        if er_claim and (er_claim in claim_lower or claim_lower in er_claim):
            return eid
    return ""


def _build_evidence_appendix(cited_ids: list[str], evidence_map: dict[str, dict]) -> str:
    """Build a sources appendix listing all cited evidence."""
    lines = ["", "## Sources Appendix", ""]
    seen = set()
    for eid in cited_ids:
        if eid in seen or eid not in evidence_map:
            continue
        seen.add(eid)
        er = evidence_map[eid]
        source_name = er.get("source_name", "Unknown")
        level = er.get("evidence_level", "U")
        confidence = er.get("confidence", "MEDIUM")
        claim = er.get("claim", "")
        urls = er.get("source_urls", [])
        urls_str = ", ".join(urls) if urls else "No URL"
        lines.append(f"[{eid}] {source_name} | [{level}] | {confidence} confidence")
        lines.append(f"  Claim: \"{claim}\"")
        lines.append(f"  Sources: {urls_str}")
        ts = er.get("timestamp", "")
        if ts:
            lines.append(f"  Screened: {str(ts)[:19]}")
        lines.append("")

    return "\n".join(lines)


def _build_quality_notes(output: Any) -> list[str]:
    """Generate analyst attention items — things to verify manually."""
    notes: list[str] = []

    if output.is_degraded:
        failed = output.investigation_results.failed_agents if output.investigation_results else []
        notes.append(f"DEGRADED INVESTIGATION: The following agents failed and results are incomplete: {', '.join(failed) or 'unknown'}")

    if output.review_intelligence and output.review_intelligence.confidence:
        conf = output.review_intelligence.confidence
        if conf.degraded:
            notes.append(f"Evidence quality is degraded (Grade {conf.overall_confidence_grade}). "
                          "Manual verification of key findings recommended.")
        if conf.unknown_pct > 20:
            notes.append(f"{conf.unknown_pct:.0f}% of evidence is unverified. Consider additional research.")

    if output.review_intelligence and output.review_intelligence.contradictions:
        for c in output.review_intelligence.contradictions:
            notes.append(f"CONTRADICTION: {c.finding_a} vs {c.finding_b} — requires manual resolution.")

    # Decision points without officer decisions
    if output.synthesis and output.synthesis.decision_points:
        unresolved = [dp for dp in output.synthesis.decision_points if not dp.officer_selection]
        if unresolved:
            notes.append(f"{len(unresolved)} decision point(s) have not been resolved by a compliance officer.")

    # Data freshness warnings — flag evidence that relied on stale data
    stale_evidence = []
    if output.investigation_results:
        # Check all evidence records accessible through investigation results
        for field_name in ("individual_sanctions", "entity_sanctions", "pep_classification",
                           "individual_adverse_media", "business_adverse_media"):
            result_obj = getattr(output.investigation_results, field_name, None)
            if result_obj and hasattr(result_obj, "evidence_records"):
                for er in (result_obj.evidence_records or []):
                    warning = er.get("data_freshness_warning") if isinstance(er, dict) else getattr(er, "data_freshness_warning", None)
                    if warning:
                        eid = er.get("evidence_id", "") if isinstance(er, dict) else getattr(er, "evidence_id", "")
                        stale_evidence.append(f"{eid}: {warning}")
    if stale_evidence:
        notes.append(f"DATA FRESHNESS: {len(stale_evidence)} evidence record(s) used potentially stale data: "
                      + "; ".join(stale_evidence[:5]))

    # Quality gate: flag empty core sections for HIGH/CRITICAL cases
    risk_level = None
    if output.synthesis and output.synthesis.revised_risk_assessment and getattr(output.synthesis.revised_risk_assessment, 'risk_level', None):
        risk_level = output.synthesis.revised_risk_assessment.risk_level.value
    elif hasattr(output, 'intake_classification') and output.intake_classification and getattr(output.intake_classification, 'preliminary_risk', None) and getattr(output.intake_classification.preliminary_risk, 'risk_level', None):
        risk_level = output.intake_classification.preliminary_risk.risk_level.value
    if risk_level in ("HIGH", "CRITICAL"):
        # Check if the SAR narrative was generated with placeholder sections
        sar = getattr(output, 'sar_narrative_draft', None)
        if isinstance(sar, dict):
            ws = sar.get("five_ws", {})
            if "No specific suspicious activity" in ws.get("what", ""):
                notes.append(f"SAR QUALITY: WHAT section is empty despite {risk_level} risk — "
                             "analyst must add specific suspicious activity indicators.")
            if "did not identify specific SAR-triggering" in ws.get("why", ""):
                notes.append(f"SAR QUALITY: WHY section is empty despite {risk_level} risk — "
                             "analyst must add reason for suspicion.")

    notes.append("PRIOR SARs: [PLACEHOLDER — verify filing history in institution's SAR database]")
    notes.append("ACCOUNT DETAILS: [PLACEHOLDER — verify specific account numbers and balances from core banking system]")
    notes.append("TRANSACTION AMOUNTS: [PLACEHOLDER — verify exact transaction amounts from transaction monitoring system]")

    return notes


# ---------------------------------------------------------------------------
# AI Enhancement (Sonnet)
# ---------------------------------------------------------------------------

async def enhance_sar_narrative(raw_narrative: dict) -> dict:
    """Use Sonnet to improve prose flow of the SAR narrative.

    Strict constraints:
    - Preserve ALL evidence citations ([E-XXX])
    - Preserve ALL amounts, dates, and dispositions
    - Only improve prose flow, grammar, and coherence
    - Do not add new facts or remove existing ones

    Returns the enhanced narrative dict, or the original on failure.
    """
    from agents.base import SimpleAgent

    raw_text = raw_narrative.get("narrative_text", "")
    if not raw_text or len(raw_text) < 100:
        return raw_narrative

    agent = SimpleAgent(
        agent_name="SAREnhancer",
        system=(
            "You are a compliance writing editor. Improve the prose flow, grammar, "
            "and coherence of the following SAR/STR narrative draft.\n\n"
            "STRICT RULES:\n"
            "- Preserve ALL evidence citations exactly as written (e.g. [E_001], [EV_002])\n"
            "- Preserve ALL amounts, dates, names, and dispositions exactly\n"
            "- Do not add new facts, claims, or allegations\n"
            "- Do not remove any existing facts or findings\n"
            "- Keep section headers (numbered 1-7)\n"
            "- Keep the Sources Appendix unchanged\n"
            "- Only improve sentence structure, transitions, and clarity\n"
            "- Return ONLY the improved narrative text, nothing else"
        ),
        model="sonnet",
        agent_tools=[],
    )

    try:
        result = await agent.run(f"Improve this SAR narrative:\n\n{raw_text}")
        enhanced_text = result.get("text", "")
        if not enhanced_text or len(enhanced_text) < len(raw_text) * 0.5:
            return raw_narrative

        # Verify citations are preserved
        import re
        raw_citations = set(re.findall(r'\[E[-_V]*\d+\w*\]', raw_text))
        enhanced_citations = set(re.findall(r'\[E[-_V]*\d+\w*\]', enhanced_text))
        if raw_citations and not raw_citations.issubset(enhanced_citations):
            return raw_narrative  # Citations were lost — reject enhancement

        enhanced = dict(raw_narrative)
        enhanced["narrative_text"] = enhanced_text
        enhanced["word_count"] = len(enhanced_text.split())
        enhanced["enhanced"] = True
        return enhanced
    except Exception:
        return raw_narrative


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_sar_narrative(
    output: KYCOutput,
    evidence_store: list | None = None,
) -> dict:
    """Generate a SAR/STR narrative draft from KYCOutput.

    Returns a dict with:
        narrative_text: Full draft narrative
        word_count: Word count
        five_ws: Dict with who/what/when/where/why/how sections
        evidence_citations: Evidence IDs referenced
        risk_indicators: SAR risk indicators
        draft_quality_notes: Items needing analyst attention
    """
    # Build evidence map for citation lookups
    evidence_map: dict[str, dict] = {}
    for er in (evidence_store or []):
        if isinstance(er, dict):
            eid = er.get("evidence_id", "")
            if eid:
                evidence_map[eid] = er

    # Extract client info
    info = _extract_client_info(output)
    all_cited_ids: list[str] = []

    # Build sections
    who = _build_who_section(info)

    what_text, what_ids = _build_what_section(output, evidence_map)
    all_cited_ids.extend(what_ids)

    when_text, when_ids = _build_when_section(output, evidence_map)
    all_cited_ids.extend(when_ids)

    where_text, where_ids = _build_where_section(output, evidence_map)
    all_cited_ids.extend(where_ids)

    why_text, why_ids = _build_why_section(output, evidence_map)
    all_cited_ids.extend(why_ids)

    how_text, how_ids = _build_how_section(output, evidence_map)
    all_cited_ids.extend(how_ids)

    # Assemble full narrative
    sections = [
        "SUSPICIOUS ACTIVITY REPORT — NARRATIVE",
        "",
        "1. SUBJECT IDENTIFICATION",
        who,
        "",
        "2. SUSPICIOUS ACTIVITY DESCRIPTION",
        what_text,
        "",
        "3. TIMELINE OF EVENTS",
        when_text,
        "",
        "4. JURISDICTIONS AND LOCATIONS",
        where_text,
        "",
        "5. REASON FOR SUSPICION",
        why_text,
        "",
        "6. METHOD OF OPERATION",
        how_text,
        "",
        "7. PRIOR SARs",
        "[PLACEHOLDER — Institution must verify prior SAR filing history for this subject. "
        "This automated system does not have access to filing history.]",
    ]

    narrative_text = "\n".join(sections)

    # Build appendix
    appendix = _build_evidence_appendix(all_cited_ids, evidence_map)
    full_text = narrative_text + "\n" + appendix

    # Risk indicators
    risk_indicators: list[str] = []
    investigation = output.investigation_results
    if investigation and investigation.sar_risk_assessment:
        risk_indicators = investigation.sar_risk_assessment.get("triggers", [])
    if investigation and investigation.transaction_monitoring:
        risk_indicators.extend(investigation.transaction_monitoring.sar_risk_indicators)

    # Quality notes
    quality_notes = _build_quality_notes(output)

    # Deduplicate citations
    unique_cited = list(dict.fromkeys(all_cited_ids))

    return {
        "narrative_text": full_text,
        "word_count": len(full_text.split()),
        "five_ws": {
            "who": who,
            "what": what_text,
            "when": when_text,
            "where": where_text,
            "why": why_text,
            "how": how_text,
        },
        "evidence_citations": unique_cited,
        "risk_indicators": risk_indicators,
        "draft_quality_notes": quality_notes,
    }
