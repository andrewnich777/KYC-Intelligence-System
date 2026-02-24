"""
Onboarding Decision Brief Generator.
Go/no-go decision summary for Brokerage Ops.
"""

from datetime import datetime

from generators.brief_helpers import render_brief_footer
from generators.markdown_utils import esc as _esc
from generators.ubo_helpers import extract_ubo_field as _extract_ubo_field


def generate_onboarding_summary(
    client_id: str,
    synthesis=None,
    plan=None,
    investigation=None,
    review_intelligence=None,
) -> str:
    """Generate an onboarding decision brief."""
    lines = []
    now = datetime.now().strftime("%B %d, %Y")

    # 1. Decision banner
    decision = "ESCALATE"
    if synthesis and synthesis.recommended_decision is not None:
        decision = synthesis.recommended_decision.value

    decision_emoji = {
        "APPROVE": "APPROVED",
        "CONDITIONAL": "CONDITIONAL APPROVAL",
        "ESCALATE": "ESCALATED FOR REVIEW",
        "DECLINE": "DECLINED",
    }

    lines.append(f"# Onboarding Decision: {decision_emoji.get(decision, decision)}")
    lines.append(f"**Client:** {client_id} | **Date:** {now}")
    lines.append("")

    # 1.5 Review Intelligence Highlights
    if review_intelligence:
        lines.append("## Review Intelligence Highlights")
        lines.append("")

        # Contradiction count alert
        if review_intelligence.contradictions:
            lines.append(f"- **{len(review_intelligence.contradictions)} contradiction(s) detected** "
                         f"— review before finalizing decision")

        # Confidence grade alert if degraded
        conf = review_intelligence.confidence
        if conf.degraded:
            lines.append(f"- **Evidence quality: Grade {conf.overall_confidence_grade}** "
                         f"(V:{conf.verified_pct:.0f}% S:{conf.sourced_pct:.0f}% "
                         f"I:{conf.inferred_pct:.0f}% U:{conf.unknown_pct:.0f}%) — DEGRADED")

        # Top 3 critical discussion points
        top_points = review_intelligence.discussion_points[:3]
        if top_points:
            lines.append("")
            lines.append("**Priority discussion points:**")
            for dp in top_points:
                lines.append(f"- [{dp.severity.value}] {dp.title}")

        # Filing obligation count
        filing_count = sum(
            1 for fm in review_intelligence.regulatory_mappings
            for tag in fm.regulatory_tags if tag.filing_required
        )
        if filing_count > 0:
            lines.append(f"- **{filing_count} regulatory filing obligation(s)** identified")

        lines.append("")

    # 2. Risk level badge
    if plan and plan.preliminary_risk:
        risk = plan.preliminary_risk
        # Use revised risk if available
        if synthesis and synthesis.revised_risk_assessment:
            risk = synthesis.revised_risk_assessment
        lines.append(f"## Risk Assessment: {risk.risk_level.value} ({risk.total_score} pts)")
        lines.append("")

    # 3. Top 5 risk factors
    risk_source = None
    if synthesis and synthesis.revised_risk_assessment:
        risk_source = synthesis.revised_risk_assessment
    elif plan and plan.preliminary_risk:
        risk_source = plan.preliminary_risk

    if risk_source and risk_source.risk_factors:
        lines.append("## Top Risk Factors")
        for rf in sorted(risk_source.risk_factors, key=lambda x: x.points, reverse=True)[:5]:
            lines.append(f"- **{rf.factor}** (+{rf.points} pts)")
        lines.append("")

    # 4. Decision reasoning (expanded)
    if synthesis and synthesis.decision_reasoning:
        lines.append("## Decision Reasoning")
        lines.append(synthesis.decision_reasoning)
        lines.append("")

        if synthesis.key_findings:
            lines.append("### Key Findings")
            for finding in synthesis.key_findings:
                lines.append(f"- {finding}")
            lines.append("")

    # 5. Conditions split — pre-activation blockers vs post-activation
    if synthesis and synthesis.conditions:
        pre_activation = []
        post_activation = []
        for cond in synthesis.conditions:
            cond_lower = cond.lower()
            # Pre-activation: anything that must happen BEFORE account activation
            if any(kw in cond_lower for kw in (
                "before", "prior to", "obtain", "verify", "confirm",
                "document", "approval", "w-9", "id ", "identity",
            )):
                pre_activation.append(cond)
            else:
                post_activation.append(cond)

        if pre_activation:
            lines.append("## Pre-Activation Blockers")
            lines.append("*Must be completed before account activation:*")
            for i, cond in enumerate(pre_activation, 1):
                lines.append(f"{i}. [ ] {cond}")
            lines.append("")

        if post_activation:
            lines.append("## Post-Activation Conditions")
            lines.append("*Must be addressed after account activation:*")
            for i, cond in enumerate(post_activation, 1):
                lines.append(f"{i}. [ ] {cond}")
            lines.append("")

    # 6. Outstanding document requirements
    if investigation and investigation.document_requirements:
        dr = investigation.document_requirements
        outstanding = [r for r in dr.get("requirements", []) if r.get("status") == "outstanding"]
        if outstanding:
            lines.append("## Outstanding Document Requirements")
            lines.append(f"**{len(outstanding)}** documents outstanding of {dr.get('total_required', len(outstanding))} total")
            lines.append("")
            for req in outstanding:
                priority_marker = "**[HIGH]**" if req.get("priority") == "high" else "[medium]"
                lines.append(f"- {priority_marker} {req.get('document', 'N/A')} ({req.get('regulatory_basis', '')})")
            lines.append("")

    # 7. Entity verification status (business only)
    if investigation and investigation.entity_verification:
        ev = investigation.entity_verification
        lines.append("## Entity Verification Status")
        lines.append(f"- **Registration Verified:** {ev.verified_registration}")
        lines.append(f"- **UBO Structure Verified:** {ev.ubo_structure_verified}")
        if ev.registry_sources:
            lines.append(f"- **Registry Sources:** {', '.join(ev.registry_sources)}")
        if ev.discrepancies:
            lines.append("### Discrepancies")
            for disc in ev.discrepancies:
                lines.append(f"- {disc}")
        lines.append("")

    # 8. Senior management approval
    if synthesis and synthesis.senior_management_approval_needed:
        lines.append("## Senior Management Approval Required")
        lines.append("**This client requires senior management approval before onboarding.**")
        lines.append("")
        if synthesis.items_requiring_review:
            lines.append("Items for senior review:")
            for item in synthesis.items_requiring_review:
                lines.append(f"- [ ] {item}")
        lines.append("")

    # 9. Processing considerations
    lines.append("## Processing Considerations")
    risk_level = "LOW"
    if risk_source:
        risk_level = risk_source.risk_level.value

    processing_map = {
        "LOW": ("1-3 business days", "Standard processing. Automated checks sufficient."),
        "MEDIUM": ("3-5 business days", "Enhanced review required. Manual verification of flagged items."),
        "HIGH": ("5-10 business days", "Full compliance review required. All documentation must be verified before activation."),
        "CRITICAL": ("10+ business days", "Executive review required. Consider relationship viability before proceeding."),
    }
    timeline, guidance = processing_map.get(risk_level, processing_map["LOW"])
    lines.append(f"- **Expected Processing Time:** {timeline}")
    lines.append(f"- **Guidance:** {guidance}")
    lines.append("")

    # 10. UBO risk summary (for business clients)
    if plan and plan.ubo_cascade_needed:
        lines.append("## Beneficial Owner Risk Summary")
        lines.append("| Owner | Sanctions | PEP | Adverse Media |")
        lines.append("|-------|-----------|-----|---------------|")
        ubo_screening = {}
        if investigation and hasattr(investigation, 'ubo_screening'):
            ubo_screening = investigation.ubo_screening
        for ubo_name in plan.ubo_names:
            ubo_data = ubo_screening.get(ubo_name, {})
            sanctions_status = _extract_ubo_field(ubo_data, "sanctions", "disposition")
            pep_status = _extract_ubo_field(ubo_data, "pep", "detected_level")
            media_status = _extract_ubo_field(ubo_data, "adverse_media", "overall_level")
            lines.append(f"| {_esc(ubo_name)} | {_esc(sanctions_status)} | {_esc(pep_status)} | {_esc(media_status)} |")
        lines.append("")

    # Applicable regulations
    if plan and plan.applicable_regulations:
        lines.append("## Regulatory Requirements")
        for reg in plan.applicable_regulations:
            lines.append(f"- {reg}")
        lines.append("")

    # Footer
    lines.extend(render_brief_footer())

    return "\n".join(lines)
