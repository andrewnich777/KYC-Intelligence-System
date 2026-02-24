"""
AML Operations Brief Generator.
Full investigation deep-dive for AML Analysts.
Replaces the Compliance Officer Brief with richer detail.
"""


from generators.brief_helpers import render_brief_footer, render_brief_header, render_ubo_screening_table
from generators.markdown_utils import esc as _esc


def generate_aml_operations_brief(
    client_id: str,
    synthesis=None,
    plan=None,
    evidence_store: list = None,
    review_session=None,
    investigation=None,
    review_intelligence=None,
) -> str:
    """Generate a detailed AML operations brief in Markdown."""
    lines = render_brief_header("AML Operations Brief", client_id)

    # =========================================================================
    # 1. Client Identification Summary
    # =========================================================================
    lines.append("## Client Identification Summary")
    if plan:
        lines.append(f"- **Client Type:** {plan.client_type.value}")
        lines.append(f"- **Client ID:** {plan.client_id}")
        if plan.preliminary_risk:
            risk = plan.preliminary_risk
            lines.append(f"- **Risk Level:** {risk.risk_level.value}")
            lines.append(f"- **Risk Score:** {risk.total_score} pts")
    lines.append("")

    # =========================================================================
    # 2. Review Intelligence Summary
    # =========================================================================
    if review_intelligence:
        lines.append("## Review Intelligence Summary")
        lines.append("")

        # Investigation Quality
        conf = review_intelligence.confidence
        lines.append("### Investigation Quality")
        lines.append(f"- **Confidence Grade:** {conf.overall_confidence_grade}")
        lines.append(f"- **Verified [V]:** {conf.verified_pct:.1f}%")
        lines.append(f"- **Sourced [S]:** {conf.sourced_pct:.1f}%")
        lines.append(f"- **Inferred [I]:** {conf.inferred_pct:.1f}%")
        lines.append(f"- **Unknown [U]:** {conf.unknown_pct:.1f}%")
        if conf.degraded:
            lines.append("")
            lines.append("**DEGRADED — Follow-up actions required:**")
            for action in conf.follow_up_actions:
                lines.append(f"- {action}")
        lines.append("")

        # Contradictions
        if review_intelligence.contradictions:
            lines.append("### Contradictions Detected")
            lines.append("")
            lines.append("| Severity | Agent A | Finding A | Agent B | Finding B | Guidance |")
            lines.append("|----------|---------|-----------|---------|-----------|----------|")
            for c in review_intelligence.contradictions:
                if isinstance(c, dict):
                    sev = c.get("severity", "MEDIUM")
                    sev_val = sev.value if hasattr(sev, "value") else str(sev)
                    lines.append(f"| **{sev_val}** | {_esc(c.get('agent_a', ''))} | {_esc(c.get('finding_a', ''), 80)} | "
                                 f"{_esc(c.get('agent_b', ''))} | {_esc(c.get('finding_b', ''), 80)} | {_esc(c.get('resolution_guidance', ''), 100)} |")
                else:
                    lines.append(f"| **{c.severity.value}** | {_esc(c.agent_a)} | {_esc(c.finding_a, 80)} | "
                                 f"{_esc(c.agent_b)} | {_esc(c.finding_b, 80)} | {_esc(c.resolution_guidance, 100)} |")
            lines.append("")

        # Critical Discussion Points
        if review_intelligence.discussion_points:
            lines.append("### Critical Discussion Points")
            lines.append("")
            lines.append("| Severity | Finding | Recommended Action |")
            lines.append("|----------|---------|-------------------|")
            for dp in review_intelligence.discussion_points:
                lines.append(f"| **{dp.severity.value}** | {_esc(dp.title, 120)} | {_esc(dp.recommended_action, 100)} |")
            lines.append("")

        # Per-Finding Regulatory Obligations
        if review_intelligence.regulatory_mappings:
            lines.append("### Per-Finding Regulatory Obligations")
            lines.append("")
            lines.append("| Finding | Regulation | Obligation | Timeline |")
            lines.append("|---------|-----------|------------|----------|")
            for fm in review_intelligence.regulatory_mappings:
                for tag in fm.regulatory_tags:
                    lines.append(f"| {_esc(fm.claim, 80)} | {_esc(tag.regulation)} | {_esc(tag.obligation, 80)} | {_esc(tag.timeline)} |")
            lines.append("")

    # =========================================================================
    # 3. Sanctions Screening
    # =========================================================================
    lines.append("## Sanctions Screening")

    sanctions_results = []
    if investigation:
        if investigation.individual_sanctions:
            sanctions_results.append(("Individual", investigation.individual_sanctions))
        if investigation.entity_sanctions:
            sanctions_results.append(("Entity", investigation.entity_sanctions))

    if sanctions_results:
        for label, sr in sanctions_results:
            lines.append(f"### {label} Screening: {sr.entity_screened}")
            lines.append(f"**Disposition:** {sr.disposition.value}")
            if sr.disposition_reasoning:
                lines.append(f"*Reasoning:* {sr.disposition_reasoning}")
            lines.append("")

            # Screening sources
            if sr.screening_sources:
                lines.append("**Screening Sources:** " + ", ".join(sr.screening_sources))
                lines.append("")

            # Search queries executed
            if sr.search_queries_executed:
                lines.append("**Search Queries Executed:**")
                for q in sr.search_queries_executed:
                    lines.append(f"- `{q}`")
                lines.append("")

            # Match detail table
            if sr.matches:
                lines.append("| List | Matched Name | Score | Disposition | Reasoning |")
                lines.append("|------|-------------|-------|-------------|-----------|")
                for m in sr.matches:
                    list_name = _esc(m.list_name)
                    matched = _esc(m.matched_name)
                    score = m.score
                    details = _esc(m.details, 100)
                    lines.append(f"| {list_name} | {matched} | {score} | {sr.disposition.value} | {details} |")
                lines.append("")
            else:
                lines.append("No matches found across all screening sources.")
                lines.append("")
    else:
        lines.append("No sanctions screening results available.")
        lines.append("")

    # =========================================================================
    # 3. PEP Classification
    # =========================================================================
    lines.append("## PEP Classification")
    if investigation and investigation.pep_classification:
        pep = investigation.pep_classification
        lines.append(f"- **Entity:** {pep.entity_screened}")
        lines.append(f"- **Detected Level:** {pep.detected_level.value}")
        lines.append(f"- **Self-Declared:** {pep.self_declared}")
        lines.append(f"- **EDD Required:** {pep.edd_required}")
        lines.append("")

        # EDD Timeline
        if pep.edd_permanent:
            lines.append("**EDD Timeline:** Permanent (never expires)")
        elif pep.edd_expiry_date:
            lines.append(f"**EDD Timeline:** Expires {pep.edd_expiry_date}")
        lines.append("")

        # Positions table
        if pep.positions_found:
            lines.append("### Positions Found")
            lines.append("| Position | Organization | Dates | Source |")
            lines.append("|----------|-------------|-------|--------|")
            for pos in pep.positions_found:
                position = _esc(pos.position)
                org = _esc(pos.organization)
                dates = _esc(pos.dates)
                source = _esc(pos.source)
                lines.append(f"| {position} | {org} | {dates} | {source} |")
            lines.append("")

        # Search queries
        if pep.search_queries_executed:
            lines.append("**Search Queries Executed:**")
            for q in pep.search_queries_executed:
                lines.append(f"- `{q}`")
            lines.append("")
    else:
        lines.append("No PEP classification results available.")
        lines.append("")

    # =========================================================================
    # 4. Adverse Media Screening
    # =========================================================================
    lines.append("## Adverse Media Screening")

    media_results = []
    if investigation:
        if investigation.individual_adverse_media:
            media_results.append(("Individual", investigation.individual_adverse_media))
        if investigation.business_adverse_media:
            media_results.append(("Business", investigation.business_adverse_media))

    if media_results:
        for label, mr in media_results:
            lines.append(f"### {label} Media: {mr.entity_screened}")
            lines.append(f"**Overall Level:** {mr.overall_level.value}")
            lines.append("")

            if mr.categories:
                lines.append(f"**Categories:** {', '.join(mr.categories)}")
                lines.append("")

            # Articles table with source tier
            if mr.articles_found:
                lines.append("| Tier | Title | Source | Date | Category |")
                lines.append("|------|-------|--------|------|----------|")
                for article in mr.articles_found:
                    tier = _esc(article.source_tier)
                    title = _esc(article.title, 100)
                    source = _esc(article.source, 50)
                    date = _esc(article.date)
                    category = _esc(article.category)
                    lines.append(f"| {tier} | {title} | {source} | {date} | {category} |")
                lines.append("")

            # Search queries
            if mr.search_queries_executed:
                lines.append("**Search Queries Executed:**")
                for q in mr.search_queries_executed:
                    lines.append(f"- `{q}`")
                lines.append("")
    else:
        lines.append("No adverse media screening results available.")
        lines.append("")

    # =========================================================================
    # 5. UBO Cascade Results (business only)
    # =========================================================================
    if investigation and investigation.ubo_screening:
        lines.append("## UBO Cascade Results")
        lines.extend(render_ubo_screening_table(investigation.ubo_screening))

    # =========================================================================
    # 6. Evidence Graph
    # =========================================================================
    if synthesis and synthesis.evidence_graph:
        eg = synthesis.evidence_graph
        lines.append("## Evidence Graph")
        lines.append(f"- **Total Evidence Records:** {eg.total_evidence_records}")
        lines.append(f"- **[V] Verified:** {eg.verified_count}")
        lines.append(f"- **[S] Sourced:** {eg.sourced_count}")
        lines.append(f"- **[I] Inferred:** {eg.inferred_count}")
        lines.append(f"- **[U] Unknown:** {eg.unknown_count}")
        lines.append(f"- **Contradictions:** {len(eg.contradictions)}")
        lines.append(f"- **Corroborations:** {len(eg.corroborations)}")
        lines.append("")

        if eg.contradictions:
            lines.append("### Contradictions")
            for c in eg.contradictions:
                fa = c.finding_a if hasattr(c, "finding_a") else c.get("finding_a", "") if isinstance(c, dict) else str(c)
                fb = c.finding_b if hasattr(c, "finding_b") else c.get("finding_b", "") if isinstance(c, dict) else str(c)
                lines.append(f"- {_esc(fa)} vs {_esc(fb)}")
            lines.append("")

    # =========================================================================
    # 7. Evidence Record Listing (with provenance)
    # =========================================================================
    if evidence_store:
        lines.append("## Evidence Records")
        lines.append(f"Total: {len(evidence_store)}")
        lines.append("")
        lines.append("| ID | Agent | Entity | Claim | Level | Disposition | Confidence | Sources |")
        lines.append("|----|-------|--------|-------|-------|-------------|------------|---------|")
        for er in evidence_store[:50]:  # Cap at 50 for readability
            if isinstance(er, dict):
                eid = _esc(str(er.get("evidence_id", "")))
                source = _esc(er.get("source_name", "N/A"))
                entity = _esc(str(er.get("entity_screened", "")))
                claim = _esc(str(er.get("claim", "")), 120)
                level = er.get("evidence_level", "U")
                disp = er.get("disposition", "PENDING_REVIEW")
                conf = er.get("confidence", "MEDIUM")
                urls = er.get("source_urls", [])
                url_count = f"{len(urls)} URL(s)" if urls else "None"
                lines.append(f"| {eid} | {source} | {entity} | {claim} | [{level}] | {disp} | {conf} | {url_count} |")
        if len(evidence_store) > 50:
            lines.append(f"*... and {len(evidence_store) - 50} more records*")
        lines.append("")

        # Evidence provenance footnotes
        lines.append("### Evidence Provenance")
        lines.append("")
        for er in evidence_store[:30]:
            if isinstance(er, dict):
                eid = er.get("evidence_id", "")
                source_name = er.get("source_name", "Unknown")
                level = er.get("evidence_level", "U")
                conf = er.get("confidence", "MEDIUM")
                claim = str(er.get("claim", ""))
                urls = er.get("source_urls", [])
                ts = er.get("timestamp", "")
                ts_str = str(ts)[:19] if ts else "N/A"

                lines.append(f"**[{eid}]** {source_name} | [{level}] | {conf} confidence")
                lines.append(f"  Claim: \"{claim}\"")
                if urls:
                    for url in urls[:3]:
                        lines.append(f"  Source: {url}")
                lines.append(f"  Screened: {ts_str}")
                lines.append("")
        if len(evidence_store) > 30:
            lines.append(f"*... {len(evidence_store) - 30} additional evidence records omitted for brevity*")
            lines.append("")

    # =========================================================================
    # 8. Disposition Analysis & Officer Decisions
    # =========================================================================
    if synthesis and synthesis.decision_points:
        lines.append("## Disposition Analysis & Officer Decisions")
        lines.append("")
        for dp in synthesis.decision_points:
            lines.append(f"### {dp.title}")
            lines.append("")
            lines.append(f"**System Recommendation:** {dp.disposition} ({dp.confidence:.0%} confidence)")
            lines.append("")
            lines.append(f"**Context:** {dp.context_summary}")
            lines.append("")

            # Counter-argument
            ca = dp.counter_argument
            lines.append("**Counter-Analysis:**")
            lines.append(f"{ca.argument}")
            lines.append("")
            lines.append("**Risk if Disposition Incorrect:**")
            lines.append(f"{ca.risk_if_wrong}")
            lines.append("")

            if ca.recommended_mitigations:
                lines.append("**Recommended Mitigations:**")
                for m in ca.recommended_mitigations:
                    lines.append(f"- {m}")
                lines.append("")

            # Officer decision (if made)
            if dp.officer_selection:
                selected_opt = None
                for opt in dp.options:
                    if opt.option_id == dp.officer_selection:
                        selected_opt = opt
                        break
                label = selected_opt.label if selected_opt else dp.officer_selection
                lines.append(f"**Officer Decision:** {label} (Option {dp.officer_selection})")
                if dp.officer_notes:
                    lines.append(f"- Officer Notes: \"{dp.officer_notes}\"")
                lines.append("- Counter-argument acknowledged: Yes")
                lines.append("")
            else:
                # Show available options
                lines.append("**Decision Options:**")
                lines.append("")
                lines.append("| Option | Label | Description | Onboarding Impact | Timeline |")
                lines.append("|--------|-------|-------------|-------------------|----------|")
                for opt in dp.options:
                    lines.append(f"| {_esc(opt.option_id)} | {_esc(opt.label)} | {_esc(opt.description)} | {_esc(opt.onboarding_impact)} | {_esc(opt.timeline)} |")
                lines.append("")
                lines.append("*Awaiting officer decision*")
                lines.append("")

    # =========================================================================
    # 9. Review Session Log
    # =========================================================================
    if review_session and review_session.actions:
        lines.append("## Review Session Log")
        lines.append(f"- **Officer:** {review_session.officer_name or 'Not specified'}")
        lines.append(f"- **Started:** {review_session.started_at}")
        lines.append(f"- **Finalized:** {review_session.finalized}")
        lines.append("")
        for action in review_session.actions:
            lines.append(f"- **{action.action_type}** ({action.timestamp})")
            if action.query:
                lines.append(f"  Query: {action.query}")
            if action.response_summary:
                lines.append(f"  Response: {action.response_summary}")
            if action.officer_note:
                lines.append(f"  Note: {action.officer_note}")
        lines.append("")

    # Footer
    lines.append("---")
    lines.append("*Evidence: [V] Verified | [S] Sourced | [I] Inferred | [U] Unknown*")
    lines.extend(render_brief_footer()[1:])  # Tagline (skip duplicate ---)

    return "\n".join(lines)


