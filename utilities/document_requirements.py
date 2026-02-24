"""
Document Requirements Consolidation.

Consolidates all document requirements from ID verification, FATCA/CRS,
EDD, and business verification into a single checklist.
Pure deterministic logic, no API calls.
"""

from datetime import UTC, datetime

from models import BusinessClient, IndividualClient, InvestigationResults


def consolidate_document_requirements(client, plan, investigation: InvestigationResults = None) -> dict:
    """
    Consolidate all document requirements into one checklist.

    Returns dict with:
        requirements: list of dicts — [{document, regulatory_basis, status, category, priority}]
        total_required: int
        total_outstanding: int
        categories: list of str — unique categories
        evidence: list of EvidenceRecord-compatible dicts
    """
    requirements = []
    timestamp = datetime.now(UTC).isoformat()

    if isinstance(client, IndividualClient):
        entity_name = client.full_name
    elif isinstance(client, BusinessClient):
        entity_name = client.legal_name
    else:
        entity_name = "unknown"

    # -------------------------------------------------------------------------
    # ID Verification requirements
    # -------------------------------------------------------------------------
    if investigation and investigation.id_verification:
        id_reqs = investigation.id_verification.get("requirements", [])
        for req in id_reqs:
            if isinstance(req, str):
                requirements.append({
                    "document": req,
                    "regulatory_basis": "FINTRAC PCMLTFA s.64",
                    "status": "outstanding",
                    "category": "identity_verification",
                    "priority": "high",
                })
            elif isinstance(req, dict):
                requirements.append({
                    "document": req.get("document", req.get("name", str(req))),
                    "regulatory_basis": req.get("regulatory_basis", "FINTRAC PCMLTFA s.64"),
                    "status": req.get("status", "outstanding"),
                    "category": "identity_verification",
                    "priority": req.get("priority", "high"),
                })

        # If no specific requirements extracted, add default ID doc
        if not id_reqs:
            method = investigation.id_verification.get("method", "")
            if method:
                requirements.append({
                    "document": f"Government-issued photo ID ({method})",
                    "regulatory_basis": "FINTRAC PCMLTFA s.64",
                    "status": "outstanding",
                    "category": "identity_verification",
                    "priority": "high",
                })

    # -------------------------------------------------------------------------
    # FATCA/CRS requirements
    # -------------------------------------------------------------------------
    if investigation and investigation.fatca_crs:
        fatca_crs = investigation.fatca_crs

        # FATCA forms
        fatca = fatca_crs.get("fatca", {})
        if fatca.get("us_person") or fatca.get("reporting_required"):
            requirements.append({
                "document": "W-9 (IRS Request for Taxpayer Identification Number)",
                "regulatory_basis": "Part XVIII ITA (FATCA)",
                "status": "outstanding",
                "category": "tax_compliance",
                "priority": "high",
            })

        # CRS forms
        crs = fatca_crs.get("crs", {})
        if crs.get("reporting_required") or crs.get("reportable_jurisdictions"):
            requirements.append({
                "document": "CRS Self-Certification Form",
                "regulatory_basis": "Part XIX ITA (CRS)",
                "status": "outstanding",
                "category": "tax_compliance",
                "priority": "high",
            })

        # Required forms from FATCA/CRS utility
        for form in fatca_crs.get("required_forms", []):
            if isinstance(form, str):
                requirements.append({
                    "document": form,
                    "regulatory_basis": "Part XVIII/XIX ITA",
                    "status": "outstanding",
                    "category": "tax_compliance",
                    "priority": "medium",
                })

    # -------------------------------------------------------------------------
    # EDD requirements (documents mentioned in measures)
    # -------------------------------------------------------------------------
    if investigation and investigation.edd_requirements:
        edd = investigation.edd_requirements
        if edd.get("edd_required"):
            measures = edd.get("measures", [])
            doc_keywords = [
                "documentation", "document", "bank statement", "tax return",
                "financial statement", "corporate structure", "articles of",
                "certificate", "W-9",
            ]
            for measure in measures:
                measure_lower = measure.lower()
                if any(kw in measure_lower for kw in doc_keywords):
                    requirements.append({
                        "document": measure,
                        "regulatory_basis": "FINTRAC EDD",
                        "status": "outstanding",
                        "category": "enhanced_due_diligence",
                        "priority": "high",
                    })

    # -------------------------------------------------------------------------
    # Business-specific requirements
    # -------------------------------------------------------------------------
    if isinstance(client, BusinessClient):
        requirements.append({
            "document": "Articles of Incorporation / Certificate of Incorporation",
            "regulatory_basis": "FINTRAC PCMLTFA s.65",
            "status": "outstanding",
            "category": "entity_verification",
            "priority": "high",
        })
        requirements.append({
            "document": "Certificate of Status / Good Standing",
            "regulatory_basis": "FINTRAC PCMLTFA s.65",
            "status": "outstanding",
            "category": "entity_verification",
            "priority": "medium",
        })
        requirements.append({
            "document": "Beneficial Ownership Declaration (>25% ownership/control)",
            "regulatory_basis": "FINTRAC PCMLTFA s.11.1",
            "status": "outstanding",
            "category": "entity_verification",
            "priority": "high",
        })
        if client.beneficial_owners:
            for ubo in client.beneficial_owners:
                requirements.append({
                    "document": f"Government-issued ID for UBO: {ubo.full_name} ({ubo.ownership_percentage}%)",
                    "regulatory_basis": "FINTRAC PCMLTFA s.64",
                    "status": "outstanding",
                    "category": "ubo_verification",
                    "priority": "high",
                })

    # -------------------------------------------------------------------------
    # Deduplicate by document name
    # -------------------------------------------------------------------------
    seen = set()
    deduped = []
    for req in requirements:
        doc_key = req["document"].lower().strip()
        if doc_key not in seen:
            seen.add(doc_key)
            deduped.append(req)
    requirements = deduped

    # -------------------------------------------------------------------------
    # Build summary
    # -------------------------------------------------------------------------
    categories = list(set(r["category"] for r in requirements))
    total_required = len(requirements)
    total_outstanding = sum(1 for r in requirements if r["status"] == "outstanding")

    # Evidence record
    entity_key = entity_name.lower().replace(" ", "_")
    evidence = [{
        "evidence_id": f"doc_requirements_{entity_key}",
        "source_type": "utility",
        "source_name": "document_requirements",
        "entity_screened": entity_name,
        "claim": (
            f"Document requirements consolidated: {total_required} required, "
            f"{total_outstanding} outstanding across {len(categories)} categories."
        ),
        "evidence_level": "S",
        "supporting_data": [
            {"total_required": total_required},
            {"total_outstanding": total_outstanding},
            {"categories": categories},
            {"outstanding_documents": [
                {"document": r["document"], "category": r["category"],
                 "regulatory_basis": r["regulatory_basis"], "priority": r["priority"]}
                for r in requirements if r["status"] == "outstanding"
            ]},
        ],
        "disposition": "PENDING_REVIEW" if total_outstanding > 0 else "CLEAR",
        "confidence": "HIGH",
        "timestamp": timestamp,
    }]

    return {
        "requirements": requirements,
        "total_required": total_required,
        "total_outstanding": total_outstanding,
        "categories": categories,
        "evidence": evidence,
    }
