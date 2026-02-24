"""
KYC Client Onboarding Intelligence System - Generator exports.
"""

from generators.aml_operations_brief import generate_aml_operations_brief
from generators.case_package import export_case_package
from generators.dedup import (
    BriefDeduplicator,
    deduplicate_by_field,
    deduplicate_claims,
    deduplicate_evidence_urls,
    deduplicate_items,
)
from generators.excel_export import generate_excel
from generators.onboarding_summary import generate_onboarding_summary
from generators.pdf_generator import generate_kyc_pdf
from generators.recommendation_engine import recommend_decision
from generators.regulatory_actions_brief import generate_regulatory_actions_brief
from generators.regulatory_filing import prefill_fincen_sar, prefill_fintrac_str
from generators.risk_assessment_brief import generate_risk_assessment_brief
from generators.sar_narrative import generate_sar_narrative

__all__ = [
    "generate_aml_operations_brief",
    "generate_risk_assessment_brief",
    "generate_regulatory_actions_brief",
    "generate_onboarding_summary",
    "recommend_decision",
    "generate_kyc_pdf",
    "generate_excel",
    "generate_sar_narrative",
    "prefill_fincen_sar",
    "prefill_fintrac_str",
    "export_case_package",
    "BriefDeduplicator",
    "deduplicate_items",
    "deduplicate_claims",
    "deduplicate_by_field",
    "deduplicate_evidence_urls",
]
