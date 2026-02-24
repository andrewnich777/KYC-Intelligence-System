"""
Regulatory Actions Brief Generator.
Filing obligations and deadlines for Regulatory team.
"""


from generators.brief_helpers import render_brief_footer, render_brief_header
from generators.markdown_utils import esc as _esc


def generate_regulatory_actions_brief(
    client_id: str,
    synthesis=None,
    plan=None,
    investigation=None,
    review_intelligence=None,
) -> str:
    """Generate a regulatory actions brief in Markdown."""
    lines = render_brief_header("Regulatory Actions Brief", client_id)

    # =========================================================================
    # 1. Applicable Regulations
    # =========================================================================
    lines.append("## Applicable Regulations")
    if plan and plan.applicable_regulations:
        for reg in plan.applicable_regulations:
            lines.append(f"- **{reg}**")
    else:
        lines.append("No regulations detected.")
    lines.append("")

    # =========================================================================
    # 2. FATCA/CRS Classification
    # =========================================================================
    if investigation and investigation.fatca_crs:
        fc = investigation.fatca_crs
        lines.append("## FATCA/CRS Classification")

        fatca = fc.get("fatca", {})
        if fatca:
            lines.append("### FATCA")
            lines.append(f"- **US Person:** {fatca.get('us_person', False)}")
            if fatca.get("indicia"):
                lines.append(f"- **US Indicia:** {', '.join(fatca['indicia']) if isinstance(fatca['indicia'], list) else fatca['indicia']}")
            lines.append(f"- **Reporting Required:** {fatca.get('reporting_required', False)}")
            if fatca.get("forms_required"):
                lines.append(f"- **Forms Required:** {', '.join(fatca['forms_required']) if isinstance(fatca['forms_required'], list) else fatca['forms_required']}")
            lines.append("")

        crs = fc.get("crs", {})
        if crs:
            lines.append("### CRS")
            lines.append(f"- **Reporting Required:** {crs.get('reporting_required', False)}")
            if crs.get("reportable_jurisdictions"):
                jurisdictions = crs["reportable_jurisdictions"]
                if isinstance(jurisdictions, list):
                    lines.append(f"- **Reportable Jurisdictions:** {', '.join(jurisdictions)}")
                else:
                    lines.append(f"- **Reportable Jurisdictions:** {jurisdictions}")
            lines.append("")

        # Entity classification (for business)
        if fc.get("entity_classification"):
            lines.append("### Entity Classification")
            lines.append(f"- **Classification:** {fc['entity_classification']}")
            if fc.get("giin"):
                lines.append(f"- **GIIN:** {fc['giin']}")
            lines.append("")

        # Required forms
        if fc.get("required_forms"):
            lines.append("### Required Forms")
            for form in fc["required_forms"]:
                lines.append(f"- {form}")
            lines.append("")

    # =========================================================================
    # 3. Enhanced Due Diligence
    # =========================================================================
    if investigation and investigation.edd_requirements:
        edd = investigation.edd_requirements
        lines.append("## Enhanced Due Diligence")
        lines.append(f"- **EDD Required:** {edd.get('edd_required', False)}")
        lines.append(f"- **Approval Level:** {edd.get('approval_required') or 'Not required'}")
        lines.append(f"- **Monitoring Frequency:** {edd.get('monitoring_frequency', 'annual')}")
        lines.append("")

        # Monitoring schedule with next review date
        schedule = edd.get("monitoring_schedule", {})
        if schedule:
            lines.append("### Monitoring Schedule")
            lines.append(f"- **Frequency:** {schedule.get('frequency', 'N/A')}")
            lines.append(f"- **Next Review Date:** {schedule.get('next_review_date', 'N/A')}")
            lines.append(f"- **Review Interval:** {schedule.get('review_interval_days', 'N/A')} days")
            lines.append("")

        if edd.get("triggers"):
            lines.append("### EDD Triggers")
            for trigger in edd["triggers"]:
                lines.append(f"- {trigger}")
            lines.append("")

        if edd.get("measures"):
            lines.append("### EDD Measures")
            for measure in edd["measures"]:
                lines.append(f"- {measure}")
            lines.append("")

    # =========================================================================
    # 3.5 Per-Finding Regulatory Obligations (from Review Intelligence)
    # =========================================================================
    if review_intelligence and review_intelligence.regulatory_mappings:
        lines.append("## Per-Finding Regulatory Obligations")
        lines.append("")
        lines.append("| Finding | Source | Regulation | Obligation | Filing | Timeline |")
        lines.append("|---------|--------|-----------|------------|--------|----------|")
        for fm in review_intelligence.regulatory_mappings:
            for tag in fm.regulatory_tags:
                filing = "Yes" if tag.filing_required else "No"
                lines.append(f"| {_esc(fm.claim, 35)} | {_esc(fm.source_name)} | {_esc(tag.regulation)} | "
                             f"{_esc(tag.obligation, 35)} | {filing} | {_esc(tag.timeline)} |")
        lines.append("")

    # =========================================================================
    # 4. Compliance Action Items
    # =========================================================================
    if investigation and investigation.compliance_actions:
        ca = investigation.compliance_actions
        lines.append("## Compliance Action Items")

        if ca.get("reports"):
            lines.append("### Required Reports")
            lines.append("| Report Type | Status | Timeline | Computed Deadline | Filing Details |")
            lines.append("|-------------|--------|----------|-------------------|----------------|")
            timelines = ca.get("timelines", {})
            for report in ca["reports"]:
                rtype = report.get("type", "N/A")
                filing = report.get("filing_decision", "N/A")
                timeline = report.get("timeline", "N/A")
                # Get computed deadline from timelines
                tl = timelines.get(rtype, {})
                computed = tl.get("computed_deadline", "N/A")
                notes = _esc(str(report.get("notes", "")), 60)
                lines.append(f"| {_esc(rtype)} | {_esc(filing)} | {_esc(timeline)} | {_esc(computed)} | {notes} |")
            lines.append("")

        if ca.get("actions"):
            lines.append("### Required Actions")
            for action in ca["actions"]:
                lines.append(f"- {action}")
            lines.append("")

        if ca.get("escalations"):
            lines.append("### Escalations")
            for esc in ca["escalations"]:
                lines.append(f"- {esc}")
            lines.append("")

    # =========================================================================
    # 5. Identity Verification
    # =========================================================================
    if investigation and investigation.id_verification:
        idv = investigation.id_verification
        lines.append("## Identity Verification")
        lines.append(f"- **Method:** {idv.get('method', 'N/A')}")
        lines.append(f"- **Status:** {idv.get('status', 'N/A')}")
        lines.append("")

        reqs = idv.get("requirements", [])
        if reqs:
            lines.append("### Requirements")
            for req in reqs:
                if isinstance(req, dict):
                    lines.append(f"- {req.get('document', req.get('name', str(req)))}")
                else:
                    lines.append(f"- {req}")

        outstanding = idv.get("concerns", [])
        if outstanding:
            lines.append("### Outstanding Items")
            for item in outstanding:
                lines.append(f"- {item}")
        lines.append("")

    # =========================================================================
    # 6. Suitability (CIRO 3202)
    # =========================================================================
    if investigation and investigation.suitability_assessment:
        suit = investigation.suitability_assessment
        lines.append("## Suitability Assessment (CIRO 3202)")
        lines.append(f"- **Suitable:** {suit.get('suitable', 'N/A')}")
        if suit.get("concerns"):
            lines.append("### Concerns")
            for concern in suit["concerns"]:
                lines.append(f"- {concern}")
        lines.append("")

    # =========================================================================
    # 7. Regulatory Action Timeline
    # =========================================================================
    if investigation and investigation.compliance_actions:
        ca = investigation.compliance_actions
        timelines = ca.get("timelines", {})
        if timelines:
            lines.append("## Regulatory Action Timeline")
            # Collect all deadlines with computed dates and sort
            deadline_entries = []
            for action_type, tl in timelines.items():
                computed = tl.get("computed_deadline")
                deadline_str = tl.get("deadline", "")
                description = tl.get("description", tl.get("filing_decision", ""))
                if computed:
                    deadline_entries.append((computed, action_type, deadline_str, description))
                else:
                    deadline_entries.append(("9999-12-31", action_type, deadline_str, description))

            deadline_entries.sort(key=lambda x: x[0])

            lines.append("| Date | Action | Description |")
            lines.append("|------|--------|-------------|")
            for computed, action_type, deadline_str, description in deadline_entries:
                date_display = computed if computed != "9999-12-31" else "Ongoing"
                desc = f"{deadline_str} - {description}" if description else deadline_str
                lines.append(f"| {_esc(date_display)} | {_esc(action_type)} | {_esc(desc)} |")
            lines.append("")

    # =========================================================================
    # 8. Document Requirements Matrix
    # =========================================================================
    if investigation and investigation.document_requirements:
        dr = investigation.document_requirements
        reqs = dr.get("requirements", [])
        if reqs:
            lines.append("## Document Requirements Matrix")
            lines.append(f"**Total Required:** {dr.get('total_required', len(reqs))} | "
                         f"**Outstanding:** {dr.get('total_outstanding', 0)}")
            lines.append("")
            lines.append("| Document | Regulatory Basis | Status | Priority |")
            lines.append("|----------|-----------------|--------|----------|")
            for req in reqs:
                doc = req.get("document", "N/A")
                basis = req.get("regulatory_basis", "N/A")
                status = req.get("status", "N/A")
                priority = req.get("priority", "N/A")
                lines.append(f"| {_esc(doc)} | {_esc(basis)} | {_esc(status)} | {_esc(priority)} |")
            lines.append("")

    # Footer
    lines.extend(render_brief_footer())

    return "\n".join(lines)
