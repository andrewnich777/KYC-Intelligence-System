"""
FINTRAC Identity Verification Pathway.

Determines which identity verification method applies to a client
based on FINTRAC guidelines. Pure deterministic logic, no API calls.

Methods:
- Credit file method (preferred for individuals)
- Government-issued photo ID method
- Dual-process method (two independent sources)
- Business verification (articles of incorporation + certificate of status)
"""

from datetime import UTC, datetime

from models import BusinessClient, IndividualClient


def assess_id_verification(client) -> dict:
    """
    Determine identity verification requirements per FINTRAC guidelines.

    Returns dict with:
        method: str — primary verification method
        requirements: list of specific docs/steps needed
        status: str — pending, verified, or incomplete
        evidence: list of EvidenceRecord-compatible dicts
        alternative_methods: list of dicts describing fallback paths

    Decision tree:
    - Individual: credit file method (preferred), OR government-issued photo ID,
      OR dual-process (two independent sources)
    - Business: articles of incorporation + certificate of status +
      registered address verification
    """
    if isinstance(client, IndividualClient):
        return _assess_individual(client)
    elif isinstance(client, BusinessClient):
        return _assess_business(client)
    else:
        return {
            "method": "unknown",
            "requirements": ["Unable to determine client type"],
            "status": "incomplete",
            "evidence": [],
            "alternative_methods": [],
        }


def _assess_individual(client: IndividualClient) -> dict:
    """Assess individual identity verification pathway."""
    evidence = []
    concerns = []
    timestamp = datetime.now(UTC).isoformat()

    # Determine preferred method based on available data
    # Method 1: Credit file (preferred — most reliable, no in-person needed)
    credit_file_viable = True
    credit_file_reqs = [
        "Obtain credit file from Canadian credit bureau (Equifax or TransUnion)",
        "Credit file must have existed for at least 3 years",
        "Verify full name matches client-provided name",
        "Verify date of birth matches client-provided DOB",
        "Verify current address matches client-provided address",
    ]

    if not client.date_of_birth:
        credit_file_reqs.append("MISSING: Date of birth required for credit file match")
        concerns.append("Date of birth not provided — credit file verification may fail")
    if not client.address:
        credit_file_reqs.append("MISSING: Address required for credit file match")
        concerns.append("Address not provided — credit file verification may fail")

    # Method 2: Government-issued photo ID
    photo_id_reqs = [
        "Obtain government-issued photo identification document",
        "Acceptable: passport, driver's licence, provincial/territorial ID card",
        "Document must be valid (not expired)",
        "Verify name on ID matches client-provided name",
        "Verify photo matches client (in-person or secure video)",
        "Record document type, number, issuing authority, and expiry date",
    ]

    # Method 3: Dual-process (two independent sources)
    dual_process_reqs = [
        "Obtain TWO independent, reliable sources to verify name + one other identifier",
        "Source A: credit file, bank statement, utility bill, or government record",
        "Source B: must be different type from Source A",
        "Each source must confirm client's name",
        "At least one source must confirm date of birth OR address",
        "Neither source may be provided by the client themselves",
    ]

    # Determine which methods are available
    methods_available = []

    # Credit file is preferred if client has a Canadian address and SIN
    if client.country_of_residence and client.country_of_residence.lower() in ("canada", "ca"):
        methods_available.append({
            "method": "credit_file",
            "description": "Canadian credit bureau verification (preferred)",
            "requirements": credit_file_reqs,
            "viable": credit_file_viable,
        })

    methods_available.append({
        "method": "gov_photo_id",
        "description": "Government-issued photo identification",
        "requirements": photo_id_reqs,
        "viable": True,
    })

    methods_available.append({
        "method": "dual_process",
        "description": "Dual-process method (two independent sources)",
        "requirements": dual_process_reqs,
        "viable": True,
    })

    # Select primary method
    if methods_available and methods_available[0]["method"] == "credit_file":
        primary_method = "credit_file"
        primary_reqs = credit_file_reqs
    else:
        primary_method = "gov_photo_id"
        primary_reqs = photo_id_reqs

    # Check for non-face-to-face concerns
    non_face_to_face = False
    if client.address and (client.address.country or "").lower() not in ("canada", "ca"):
        non_face_to_face = True
        concerns.append(
            "Client address is outside Canada — non-face-to-face verification applies"
        )
        primary_reqs.append(
            "Non-face-to-face: must use credit file or dual-process method"
        )
        if primary_method == "gov_photo_id":
            primary_method = "dual_process"
            primary_reqs = dual_process_reqs

    # Build evidence records
    evidence.append({
        "evidence_id": f"idv_method_{client.full_name.lower().replace(' ', '_')}",
        "source_type": "utility",
        "source_name": "id_verification",
        "entity_screened": client.full_name,
        "entity_context": "individual client",
        "claim": f"Identity verification method determined: {primary_method}",
        "evidence_level": "S",
        "supporting_data": [
            {"detail": f"Method: {primary_method}"},
            {"detail": f"Requirements count: {len(primary_reqs)}"},
            {"detail": f"Non-face-to-face: {non_face_to_face}"},
        ],
        "disposition": "PENDING_REVIEW",
        "confidence": "HIGH",
        "timestamp": timestamp,
    })

    if concerns:
        evidence.append({
            "evidence_id": f"idv_concerns_{client.full_name.lower().replace(' ', '_')}",
            "source_type": "utility",
            "source_name": "id_verification",
            "entity_screened": client.full_name,
            "entity_context": "individual client",
            "claim": f"Identity verification concerns identified: {len(concerns)}",
            "evidence_level": "S",
            "supporting_data": [{"concern": c} for c in concerns],
            "disposition": "PENDING_REVIEW",
            "confidence": "MEDIUM",
            "timestamp": timestamp,
        })

    return {
        "method": primary_method,
        "requirements": primary_reqs,
        "status": "pending",
        "evidence": evidence,
        "concerns": concerns,
        "alternative_methods": [
            m for m in methods_available if m["method"] != primary_method
        ],
        "non_face_to_face": non_face_to_face,
    }


def _assess_business(client: BusinessClient) -> dict:
    """Assess business entity identity verification pathway."""
    evidence = []
    requirements = []
    concerns = []
    timestamp = datetime.now(UTC).isoformat()

    entity_name = client.legal_name

    # Business verification requirements per FINTRAC
    requirements = [
        "Obtain articles of incorporation, certificate of incorporation, or equivalent",
        "Obtain certificate of status or certificate of good standing (if available)",
        "Verify registered business address matches client-provided address",
        "Confirm legal name matches official registration records",
        "Verify business number (BN) with Canada Revenue Agency records if Canadian",
    ]

    if client.operating_name and client.operating_name != client.legal_name:
        requirements.append(
            f"Verify operating name '{client.operating_name}' is registered as a trade name"
        )

    # Incorporation jurisdiction checks
    if client.incorporation_jurisdiction:
        jurisdiction = client.incorporation_jurisdiction
        requirements.append(
            f"Obtain registration confirmation from {jurisdiction} corporate registry"
        )
        if jurisdiction.lower() not in ("canada", "ca") and not any(
            prov in jurisdiction.lower()
            for prov in [
                "ontario", "quebec", "british columbia", "alberta",
                "manitoba", "saskatchewan", "nova scotia",
                "new brunswick", "newfoundland", "prince edward island",
                "northwest territories", "nunavut", "yukon",
            ]
        ):
            concerns.append(
                f"Foreign incorporation jurisdiction ({jurisdiction}) — "
                "may require apostilled or notarized documents"
            )
            requirements.append(
                "Foreign entity: obtain apostilled or notarized copies of incorporation documents"
            )
    else:
        concerns.append("Incorporation jurisdiction not provided — cannot determine registry")

    # Beneficial owner verification
    if client.beneficial_owners:
        requirements.append(
            f"Verify identity of all {len(client.beneficial_owners)} declared beneficial owners"
        )
        for ubo in client.beneficial_owners:
            requirements.append(
                f"  - Verify {ubo.full_name} ({ubo.ownership_percentage}% owner) "
                "using individual verification method"
            )
    else:
        concerns.append(
            "No beneficial owners declared — must determine all persons "
            "who own or control 25% or more"
        )
        requirements.append(
            "Determine and verify all beneficial owners (25%+ ownership or control)"
        )

    # Authorized signatories
    if client.authorized_signatories:
        requirements.append(
            f"Verify identity of all {len(client.authorized_signatories)} authorized signatories"
        )
    else:
        requirements.append("Obtain and verify authorized signatory list")

    # Director verification
    requirements.append("Obtain list of directors and senior officers")
    requirements.append("Verify at least one director's identity using individual method")

    # Build evidence
    evidence.append({
        "evidence_id": f"idv_business_{entity_name.lower().replace(' ', '_')}",
        "source_type": "utility",
        "source_name": "id_verification",
        "entity_screened": entity_name,
        "entity_context": "business client",
        "claim": f"Business identity verification requirements determined: {len(requirements)} items",
        "evidence_level": "S",
        "supporting_data": [
            {"detail": f"Requirements count: {len(requirements)}"},
            {"detail": f"Concerns count: {len(concerns)}"},
            {"detail": f"Beneficial owners to verify: {len(client.beneficial_owners)}"},
        ],
        "disposition": "PENDING_REVIEW",
        "confidence": "HIGH",
        "timestamp": timestamp,
    })

    if concerns:
        evidence.append({
            "evidence_id": f"idv_business_concerns_{entity_name.lower().replace(' ', '_')}",
            "source_type": "utility",
            "source_name": "id_verification",
            "entity_screened": entity_name,
            "entity_context": "business client",
            "claim": f"Business verification concerns: {len(concerns)}",
            "evidence_level": "S",
            "supporting_data": [{"concern": c} for c in concerns],
            "disposition": "PENDING_REVIEW",
            "confidence": "MEDIUM",
            "timestamp": timestamp,
        })

    return {
        "method": "business_verification",
        "requirements": requirements,
        "status": "pending",
        "evidence": evidence,
        "concerns": concerns,
        "alternative_methods": [],
        "ubo_verification_needed": len(client.beneficial_owners) > 0,
        "signatory_verification_needed": True,
    }
