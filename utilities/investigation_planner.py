"""
Investigation planner — builds agent + utility execution plan based on client type and risk.

Risk-stratified agent selection:
- LOW risk (0-15 pts): Sanctions + PEP only (standard scope)
- MEDIUM risk (16-35 pts): Add adverse media + jurisdiction risk (enhanced scope)
- HIGH/CRITICAL (36+ pts): Full agent suite + UBO cascade (full scope)
- Utilities always run (deterministic, no API cost).
"""

import re

from models import (
    BusinessClient,
    ClientType,
    IndividualClient,
    InvestigationPlan,
    RiskLevel,
)
from utilities.regulation_detector import detect_applicable_regulations
from utilities.risk_scoring import calculate_business_risk_score, calculate_individual_risk_score


def _generate_client_id(client) -> str:
    """Generate a filesystem-safe client ID."""
    if isinstance(client, IndividualClient):
        name = client.full_name
    else:
        name = client.legal_name

    # Convert to filesystem-safe string
    safe = re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')
    return safe


def _select_agents_for_risk(
    client_type: ClientType,
    risk_level: RiskLevel,
) -> tuple[list[str], str]:
    """Select agents based on client type and risk level.

    Returns (agents_list, investigation_scope).
    """
    if client_type == ClientType.INDIVIDUAL:
        # Core agents — always run for any risk level
        core = ["IndividualSanctions", "PEPDetection"]
        enhanced = ["IndividualAdverseMedia", "JurisdictionRisk"]
        full = ["TransactionMonitoring"]

        if risk_level == RiskLevel.LOW:
            return core, "standard"
        elif risk_level == RiskLevel.MEDIUM:
            return core + enhanced, "enhanced"
        else:  # HIGH or CRITICAL
            return core + enhanced + full, "full"

    else:  # BUSINESS
        core = ["EntityVerification", "EntitySanctions"]
        enhanced = ["BusinessAdverseMedia", "JurisdictionRisk"]
        full = ["TransactionMonitoring"]

        if risk_level == RiskLevel.LOW:
            return core, "standard"
        elif risk_level == RiskLevel.MEDIUM:
            return core + enhanced, "enhanced"
        else:  # HIGH or CRITICAL
            return core + enhanced + full, "full"


def build_investigation_plan(client) -> InvestigationPlan:
    """
    Build the investigation plan for a client.
    Determines which agents and utilities to run based on risk-stratified approach.
    """
    client_type = client.client_type
    client_id = _generate_client_id(client)

    # Calculate preliminary risk
    if isinstance(client, IndividualClient):
        risk = calculate_individual_risk_score(client)
    else:
        risk = calculate_business_risk_score(client)

    # Detect applicable regulations
    regulations = detect_applicable_regulations(client)

    # Risk-stratified agent selection
    agents, scope = _select_agents_for_risk(client_type, risk.risk_level)

    # Utilities always run (deterministic, zero API cost)
    if client_type == ClientType.INDIVIDUAL:
        utilities = [
            "id_verification",
            "suitability",
            "individual_fatca_crs",
            "edd_requirements",
            "compliance_actions",
            "misrepresentation_detection",
            "sar_risk_assessment",
            "document_requirements",
        ]
    else:
        utilities = [
            "id_verification",
            "suitability",
            "entity_fatca_crs",
            "business_risk_assessment",
            "edd_requirements",
            "compliance_actions",
            "misrepresentation_detection",
            "sar_risk_assessment",
            "document_requirements",
        ]

    # UBO cascade — only for HIGH/CRITICAL business clients
    ubo_cascade = False
    ubo_names = []
    if isinstance(client, BusinessClient) and client.beneficial_owners:
        if risk.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            ubo_cascade = True
            ubo_names = [ubo.full_name for ubo in client.beneficial_owners]

    return InvestigationPlan(
        client_type=client_type,
        client_id=client_id,
        agents_to_run=agents,
        utilities_to_run=utilities,
        ubo_cascade_needed=ubo_cascade,
        ubo_names=ubo_names,
        applicable_regulations=regulations,
        preliminary_risk=risk,
        investigation_scope=scope,
    )
