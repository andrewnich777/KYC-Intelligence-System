"""
Dispatch tables for agent and utility routing.

Replaces if/elif chains in pipeline.py with data-driven lookups.
"""

from typing import Any

from models import BusinessClient, IndividualClient, InvestigationPlan, InvestigationResults

ClientT = IndividualClient | BusinessClient

# =============================================================================
# Agent Dispatch
# =============================================================================
# Maps agent name -> (agent_attr, kwargs_extractor_fn, method_name)
#   agent_attr: attribute name on KYCPipeline to get the agent instance
#   kwargs_extractor_fn: callable(client, plan) -> dict of kwargs for agent.research()
#   method_name: method to call on the agent (always "research")


def _individual_sanctions_kwargs(client: ClientT, plan: InvestigationPlan) -> dict[str, Any]:
    return dict(
        full_name=client.full_name,
        date_of_birth=getattr(client, 'date_of_birth', None),
        citizenship=getattr(client, 'citizenship', None),
    )


def _pep_detection_kwargs(client: ClientT, plan: InvestigationPlan) -> dict[str, Any]:
    return dict(
        full_name=client.full_name,
        citizenship=getattr(client, 'citizenship', None),
        pep_self_declaration=getattr(client, 'pep_self_declaration', False),
        pep_details=getattr(client, 'pep_details', None),
    )


def _individual_adverse_media_kwargs(client: ClientT, plan: InvestigationPlan) -> dict[str, Any]:
    employer = None
    if hasattr(client, 'employment') and client.employment:
        employer = client.employment.employer
    return dict(
        full_name=client.full_name,
        employer=employer,
        citizenship=getattr(client, 'citizenship', None),
    )


def _entity_verification_kwargs(client: ClientT, plan: InvestigationPlan) -> dict[str, Any]:
    declared_ubos = [
        {"full_name": ubo.full_name, "ownership_percentage": ubo.ownership_percentage}
        for ubo in client.beneficial_owners
    ] if hasattr(client, 'beneficial_owners') else None
    return dict(
        legal_name=client.legal_name,
        jurisdiction=getattr(client, 'incorporation_jurisdiction', None),
        business_number=getattr(client, 'business_number', None),
        declared_ubos=declared_ubos,
    )


def _entity_sanctions_kwargs(client: ClientT, plan: InvestigationPlan) -> dict[str, Any]:
    ubo_dicts = [
        {"full_name": ubo.full_name, "ownership_percentage": ubo.ownership_percentage}
        for ubo in client.beneficial_owners
    ] if hasattr(client, 'beneficial_owners') else None
    return dict(
        legal_name=client.legal_name,
        beneficial_owners=ubo_dicts,
        countries=getattr(client, 'countries_of_operation', None),
        us_nexus=getattr(client, 'us_nexus', False),
    )


def _business_adverse_media_kwargs(client: ClientT, plan: InvestigationPlan) -> dict[str, Any]:
    return dict(
        legal_name=client.legal_name,
        industry=getattr(client, 'industry', None),
        countries=getattr(client, 'countries_of_operation', None),
    )


def _jurisdiction_risk_kwargs(client: ClientT, plan: InvestigationPlan) -> dict[str, Any]:
    jurisdictions = set()
    if isinstance(client, IndividualClient):
        if client.citizenship:
            jurisdictions.add(client.citizenship)
        if client.country_of_residence:
            jurisdictions.add(client.country_of_residence)
        if client.country_of_birth:
            jurisdictions.add(client.country_of_birth)
        jurisdictions.update(client.tax_residencies)
    else:
        jurisdictions.update(client.countries_of_operation)
        if client.incorporation_jurisdiction:
            jurisdictions.add(client.incorporation_jurisdiction)
        for ubo in client.beneficial_owners:
            if ubo.citizenship:
                jurisdictions.add(ubo.citizenship)
            if ubo.country_of_birth:
                jurisdictions.add(ubo.country_of_birth)
            if ubo.country_of_residence:
                jurisdictions.add(ubo.country_of_residence)
    # Remove None and Canada
    jurisdictions = [j for j in jurisdictions if j and j.lower() not in ("canada", "ca")]
    if not jurisdictions:
        jurisdictions = ["Canada"]  # At minimum assess Canada
    # JurisdictionRiskAgent.research() takes a positional list, not kwargs
    return dict(_positional_arg=list(jurisdictions))


def _transaction_monitoring_kwargs(client: ClientT, plan: InvestigationPlan) -> dict[str, Any]:
    if isinstance(client, IndividualClient):
        return dict(
            entity_name=client.full_name,
            industry=getattr(client.employment, 'industry', None) if client.employment else None,
            countries=[c for c in [client.citizenship, client.country_of_residence] if c],
            expected_volume=None,
            expected_frequency=None,
            account_requests=[
                {"account_type": a.account_type, "expected_activity": a.expected_activity}
                for a in client.account_requests
            ] if client.account_requests else None,
            source_of_funds=client.source_of_funds,
        )
    else:
        return dict(
            entity_name=client.legal_name,
            industry=getattr(client, 'industry', None),
            countries=getattr(client, 'countries_of_operation', None),
            expected_volume=getattr(client, 'expected_transaction_volume', None),
            expected_frequency=getattr(client, 'expected_transaction_frequency', None),
            account_requests=[
                {"account_type": a.account_type, "expected_activity": a.expected_activity}
                for a in client.account_requests
            ] if client.account_requests else None,
            source_of_funds=getattr(client, 'source_of_funds', None),
        )


AGENT_DISPATCH = {
    "IndividualSanctions": ("individual_sanctions_agent", _individual_sanctions_kwargs),
    "PEPDetection": ("pep_detection_agent", _pep_detection_kwargs),
    "IndividualAdverseMedia": ("individual_adverse_media_agent", _individual_adverse_media_kwargs),
    "EntityVerification": ("entity_verification_agent", _entity_verification_kwargs),
    "EntitySanctions": ("entity_sanctions_agent", _entity_sanctions_kwargs),
    "BusinessAdverseMedia": ("business_adverse_media_agent", _business_adverse_media_kwargs),
    "JurisdictionRisk": ("jurisdiction_risk_agent", _jurisdiction_risk_kwargs),
    "TransactionMonitoring": ("transaction_monitoring_agent", _transaction_monitoring_kwargs),
}

# Maps agent name -> InvestigationResults field name
AGENT_RESULT_FIELD = {
    "IndividualSanctions": "individual_sanctions",
    "PEPDetection": "pep_classification",
    "IndividualAdverseMedia": "individual_adverse_media",
    "EntityVerification": "entity_verification",
    "EntitySanctions": "entity_sanctions",
    "BusinessAdverseMedia": "business_adverse_media",
    "JurisdictionRisk": "jurisdiction_risk",
    "TransactionMonitoring": "transaction_monitoring",
}


# =============================================================================
# Utility Dispatch
# =============================================================================
# Maps util name -> (module_path, function_name, args_builder_fn)
#   module_path: dotted module path for importlib
#   function_name: function to call from that module
#   args_builder_fn: callable(client, plan, results) -> tuple(args, kwargs)


def _simple_client_args(client: ClientT, plan: InvestigationPlan, results: InvestigationResults) -> tuple[tuple, dict]:
    return (client,), {}


def _edd_args(client: ClientT, plan: InvestigationPlan, results: InvestigationResults) -> tuple[tuple, dict]:
    return (client, plan.preliminary_risk, results), {}


def _compliance_args(client: ClientT, plan: InvestigationPlan, results: InvestigationResults) -> tuple[tuple, dict]:
    return (client, plan.preliminary_risk, results), {}


def _document_args(client: ClientT, plan: InvestigationPlan, results: InvestigationResults) -> tuple[tuple, dict]:
    return (client, plan, results), {}


def _misrepresentation_args(client: ClientT, plan: InvestigationPlan, results: InvestigationResults) -> tuple[tuple, dict]:
    return (client, results), {}


UTILITY_DISPATCH = {
    "id_verification": ("utilities.id_verification", "assess_id_verification", _simple_client_args),
    "suitability": ("utilities.suitability", "assess_suitability", _simple_client_args),
    "individual_fatca_crs": ("utilities.individual_fatca_crs", "classify_individual_fatca_crs", _simple_client_args),
    "entity_fatca_crs": ("utilities.entity_fatca_crs", "classify_entity_fatca_crs", _simple_client_args),
    "edd_requirements": ("utilities.edd_requirements", "assess_edd_requirements", _edd_args),
    "compliance_actions": ("utilities.compliance_actions", "determine_compliance_actions", _compliance_args),
    "business_risk_assessment": ("utilities.business_risk_assessment", "assess_business_risk_factors", _simple_client_args),
    "document_requirements": ("utilities.document_requirements", "consolidate_document_requirements", _document_args),
    "misrepresentation_detection": ("utilities.misrepresentation_detector", "detect_misrepresentation", _misrepresentation_args),
    "sar_risk_assessment": ("utilities.sar_risk_assessment", "assess_sar_risk", _misrepresentation_args),
}

# Maps utility name -> InvestigationResults field name
UTILITY_RESULT_FIELD = {
    "id_verification": "id_verification",
    "suitability": "suitability_assessment",
    "individual_fatca_crs": "fatca_crs",
    "entity_fatca_crs": "fatca_crs",
    "edd_requirements": "edd_requirements",
    "compliance_actions": "compliance_actions",
    "business_risk_assessment": "business_risk_assessment",
    "document_requirements": "document_requirements",
    "misrepresentation_detection": "misrepresentation_detection",
    "sar_risk_assessment": "sar_risk_assessment",
}
