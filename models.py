"""
Pydantic models for the KYC Client Onboarding Intelligence System.

Defines all data structures for the 5-stage pipeline:
1. Intake & Classification
2. Investigation (AI agents + deterministic utilities)
3. Synthesis & Proto-Reports
4. Conversational Review
5. Final Reports
"""

import re
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_URL_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)


# =============================================================================
# Preserved Enums (from original system)
# =============================================================================

class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class SourceTier(str, Enum):
    TIER_0 = "TIER_0"  # Primary sources (government registries, official sanctions lists)
    TIER_1 = "TIER_1"  # Strong secondary (major news, regulatory databases)
    TIER_2 = "TIER_2"  # Regional/trade publications, secondary sources
    TIER_3 = "TIER_3"  # Blogs, social media, unverified sources


class EvidenceClass(str, Enum):
    """Classification of how a claim is supported."""
    VERIFIED = "V"    # URL + direct quote + Tier 0/1 source
    SOURCED = "S"     # URL + excerpt + Tier 1/2 source
    INFERRED = "I"    # Derived from signals, no direct evidence
    UNKNOWN = "U"     # Explicitly searched but not found


# =============================================================================
# KYC-Specific Enums
# =============================================================================

class ClientType(str, Enum):
    INDIVIDUAL = "individual"
    BUSINESS = "business"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DispositionStatus(str, Enum):
    """Screening result disposition."""
    CLEAR = "CLEAR"
    POTENTIAL_MATCH = "POTENTIAL_MATCH"
    CONFIRMED_MATCH = "CONFIRMED_MATCH"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    PENDING_REVIEW = "PENDING_REVIEW"


class PEPLevel(str, Enum):
    """Politically Exposed Person classification per FINTRAC."""
    NOT_PEP = "NOT_PEP"
    FOREIGN_PEP = "FOREIGN_PEP"        # Permanent - never expires
    DOMESTIC_PEP = "DOMESTIC_PEP"       # 5-year window after leaving office
    HIO = "HIO"                         # Head of International Organization - 5yr
    PEP_FAMILY = "PEP_FAMILY"           # Family member of PEP
    PEP_ASSOCIATE = "PEP_ASSOCIATE"     # Close associate of PEP


class OnboardingDecision(str, Enum):
    APPROVE = "APPROVE"
    CONDITIONAL = "CONDITIONAL"
    ESCALATE = "ESCALATE"
    DECLINE = "DECLINE"


class AdverseMediaLevel(str, Enum):
    CLEAR = "CLEAR"
    LOW_CONCERN = "LOW_CONCERN"
    MATERIAL_CONCERN = "MATERIAL_CONCERN"
    HIGH_RISK = "HIGH_RISK"


# =============================================================================
# Input Models — Client Data
# =============================================================================

class Address(BaseModel):
    """Physical address."""
    street: str | None = None
    city: str | None = None
    province_state: str | None = None
    postal_code: str | None = None
    country: str = "Canada"


class AccountRequest(BaseModel):
    """Account type being requested."""
    account_type: str = Field(description="e.g., 'personal_investment', 'corporate_trading'")
    investment_objectives: str | None = None
    risk_tolerance: str | None = None
    time_horizon: str | None = None
    initial_deposit: float | None = None
    expected_activity: str | None = None


class EmploymentInfo(BaseModel):
    """Employment details for individual clients."""
    status: str = Field(description="employed, self_employed, retired, student, unemployed")
    employer: str | None = Field(default=None, json_schema_extra={"pii": True})
    occupation: str | None = None
    industry: str | None = None
    years_employed: int | None = None


class BeneficialOwner(BaseModel):
    """Beneficial owner of a business entity (for UBO cascade)."""
    full_name: str = Field(json_schema_extra={"pii": True})
    date_of_birth: str | None = Field(default=None, json_schema_extra={"pii": True})
    citizenship: str | None = None
    country_of_residence: str | None = None
    country_of_birth: str | None = None
    ownership_percentage: float = Field(ge=0, le=100)
    role: str | None = None
    pep_self_declaration: bool = False
    pep_details: str | None = None
    us_person: bool = False
    tax_residencies: list[str] = Field(default_factory=list)
    address: Address | None = None

    @field_validator("date_of_birth")
    @classmethod
    def _validate_dob(cls, v: str | None) -> str | None:
        if v is not None and not _ISO_DATE_RE.match(v):
            raise ValueError(f"date_of_birth must be YYYY-MM-DD, got: {v!r}")
        return v


class IndividualClient(BaseModel):
    """Individual client intake data — exact field names from spec."""
    client_type: ClientType = ClientType.INDIVIDUAL
    full_name: str = Field(json_schema_extra={"pii": True})
    date_of_birth: str | None = Field(default=None, json_schema_extra={"pii": True})
    citizenship: str | None = "Canada"
    country_of_residence: str | None = "Canada"
    country_of_birth: str | None = None
    address: Address | None = Field(default=None, json_schema_extra={"pii": True})
    sin_last4: str | None = Field(default=None, json_schema_extra={"pii": True})
    us_person: bool = False
    us_tin: str | None = Field(default=None, json_schema_extra={"pii": True})
    tax_residencies: list[str] = Field(default_factory=lambda: ["Canada"])
    pep_self_declaration: bool = False
    pep_details: str | None = None
    employment: EmploymentInfo | None = None
    annual_income: float | None = None
    net_worth: float | None = None
    source_of_funds: str | None = None
    source_of_wealth: str | None = None
    intended_use: str | None = None
    account_requests: list[AccountRequest] = Field(default_factory=list)
    third_party_determination: bool = False
    third_party_details: str | None = None

    @field_validator("date_of_birth")
    @classmethod
    def _validate_dob(cls, v: str | None) -> str | None:
        if v is not None and not _ISO_DATE_RE.match(v):
            raise ValueError(f"date_of_birth must be YYYY-MM-DD, got: {v!r}")
        return v


class BusinessClient(BaseModel):
    """Business client intake data — exact field names from spec."""
    client_type: ClientType = ClientType.BUSINESS
    legal_name: str
    operating_name: str | None = None
    operating_names: list[str] = Field(default_factory=list)
    business_number: str | None = None
    incorporation_date: str | None = None
    incorporation_jurisdiction: str | None = None
    entity_type: str | None = None
    business_type: str | None = None
    industry: str | None = None
    naics_code: str | None = None
    nature_of_business: str | None = None
    address: Address | None = None
    countries_of_operation: list[str] = Field(default_factory=lambda: ["Canada"])
    us_nexus: bool = False
    us_nexus_details: str | None = None
    us_tin: str | None = None
    annual_revenue: float | None = None
    expected_transaction_volume: float | None = None
    expected_transaction_frequency: str | None = None
    source_of_funds: str | None = None
    intended_use: str | None = None
    beneficial_owners: list[BeneficialOwner] = Field(default_factory=list)
    authorized_signatories: list[str] = Field(default_factory=list)
    account_requests: list[AccountRequest] = Field(default_factory=list)
    third_party_determination: bool = False

    @field_validator("incorporation_date")
    @classmethod
    def _validate_inc_date(cls, v: str | None) -> str | None:
        if v is not None and not _ISO_DATE_RE.match(v):
            raise ValueError(f"incorporation_date must be YYYY-MM-DD, got: {v!r}")
        return v


# =============================================================================
# Typed sub-models for previously untyped list[dict] fields
# =============================================================================

class ScoreHistoryEntry(BaseModel):
    """Single entry in risk score progression."""
    stage: str = ""
    score: int = 0
    level: str = "UNKNOWN"


class SanctionsMatch(BaseModel):
    """A match found during sanctions screening."""
    list_name: str = ""
    matched_name: str = ""
    score: float = 0.0
    details: str = ""


class PEPPosition(BaseModel):
    """A political position found for a PEP."""
    position: str = ""
    organization: str = ""
    dates: str = ""
    source: str = ""


class PEPFamilyAssociation(BaseModel):
    """A family association of a PEP."""
    name: str = ""
    relationship: str = ""
    pep_name: str = ""
    source: str = ""


class MediaArticle(BaseModel):
    """An adverse media article found during screening."""
    title: str = ""
    source: str = ""
    date: str = ""
    summary: str = ""
    category: str = ""
    source_tier: str = ""


class SanctionsProgram(BaseModel):
    """A sanctions program applicable to a jurisdiction."""
    program: str = ""
    country: str = ""
    authority: str = ""


class JurisdictionDetail(BaseModel):
    """Detailed jurisdiction risk assessment."""
    country: str = ""
    fatf_status: str = "clean"
    cpi_score: float | None = None
    basel_aml_score: float | None = None


class RecommendedAlert(BaseModel):
    """A recommended transaction monitoring alert."""
    alert_type: str = ""
    threshold: str = ""
    description: str = ""


class RiskElevation(BaseModel):
    """A risk factor discovered during synthesis."""
    factor: str = ""
    points: int = 0
    reason: str = ""
    description: str = ""
    evidence_id: str = ""


class OfficerOverride(BaseModel):
    """An auditable officer override during review."""
    type: str = ""
    target: str = ""
    old_value: str = ""
    new_value: str = ""
    old_score: int | None = None
    new_score: int | None = None
    old_level: str = ""
    new_level: str = ""
    old_disposition: str = ""
    new_disposition: str = ""
    evidence_id: str = ""
    reason: str = ""
    timestamp: datetime | None = None


class GraphContradiction(BaseModel):
    """A contradiction detected in the evidence graph."""
    finding_a: str = ""
    finding_b: str = ""
    agent_a: str = ""
    agent_b: str = ""
    resolution: str = ""
    resolution_guidance: str = ""


class GraphCorroboration(BaseModel):
    """A corroboration detected in the evidence graph."""
    finding_1: str = ""
    finding_2: str = ""
    source_1: str = ""
    source_2: str = ""


# =============================================================================
# Stage 1: Intake & Classification
# =============================================================================

class RiskFactor(BaseModel):
    """Individual risk factor contributing to overall score."""
    factor: str = Field(description="Description of the risk factor")
    points: int = Field(description="Points assigned")
    category: str = Field(description="e.g., pep, citizenship, industry, jurisdiction")
    source: str = Field(description="Where this factor was identified")


class RiskAssessment(BaseModel):
    """Risk classification result from Stage 1."""
    total_score: int = Field(default=0)
    risk_level: RiskLevel = Field(default=RiskLevel.LOW)
    risk_factors: list[RiskFactor] = Field(default_factory=list)
    is_preliminary: bool = Field(default=True, description="True until UBO cascade + synthesis revise it")
    score_history: list[ScoreHistoryEntry] = Field(default_factory=list, description="Track score progression")


class InvestigationPlan(BaseModel):
    """Plan of which agents and utilities to run."""
    client_type: ClientType
    client_id: str
    agents_to_run: list[str] = Field(default_factory=list)
    utilities_to_run: list[str] = Field(default_factory=list)
    ubo_cascade_needed: bool = False
    ubo_names: list[str] = Field(default_factory=list)
    applicable_regulations: list[str] = Field(default_factory=list)
    preliminary_risk: RiskAssessment = Field(default_factory=RiskAssessment)
    investigation_scope: str = Field(default="full", description="'standard' (LOW), 'enhanced' (MEDIUM), or 'full' (HIGH/CRITICAL)")


# =============================================================================
# Stage 2: Investigation Results
# =============================================================================

class EvidenceRecord(BaseModel):
    """Central evidence record — all findings flow through this."""
    evidence_id: str = Field(description="Unique identifier")
    source_type: str = Field(description="'agent' or 'utility'")
    source_name: str = Field(description="Agent/utility that produced this")
    entity_screened: str = Field(description="Name of person/entity screened")
    entity_context: str | None = Field(default=None, description="Role context, e.g., 'UBO (45% owner)'")
    claim: str = Field(description="The factual finding")
    evidence_level: EvidenceClass = Field(default=EvidenceClass.UNKNOWN)
    supporting_data: list[dict] = Field(default_factory=list, description="URLs, quotes, document references")
    disposition: DispositionStatus = Field(default=DispositionStatus.PENDING_REVIEW)
    disposition_reasoning: str | None = None
    confidence: Confidence = Field(default=Confidence.MEDIUM)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_urls: list[str] = Field(default_factory=list, description="URLs fetched during investigation")
    urls_are_global: bool = Field(default=False, description="True if source_urls are agent-wide, not claim-specific")
    data_as_of: datetime | None = Field(default=None, description="UTC timestamp when the underlying data was current")
    data_freshness_warning: str | None = Field(default=None, description="Warning if data source was stale")

    @field_validator("source_urls")
    @classmethod
    def _validate_urls(cls, v: list[str]) -> list[str]:
        return [url for url in v if _URL_SCHEME_RE.match(url)]


class SanctionsResult(BaseModel):
    """Result from sanctions screening."""
    entity_screened: str
    screening_sources: list[str] = Field(default_factory=list)
    matches: list[SanctionsMatch] = Field(default_factory=list, description="Sanctions list matches")
    disposition: DispositionStatus = Field(default=DispositionStatus.CLEAR)
    disposition_reasoning: str | None = None
    ofac_50_percent_rule_applicable: bool = False
    search_queries_executed: list[str] = Field(default_factory=list)
    evidence_records: list[EvidenceRecord] = Field(default_factory=list)

    @classmethod
    def failed(cls, entity: str, error: str) -> "SanctionsResult":
        """Create a sentinel result representing a failed agent run."""
        return cls(
            entity_screened=entity,
            disposition=DispositionStatus.PENDING_REVIEW,
            disposition_reasoning=f"Agent failed: {error}",
        )


class PEPClassification(BaseModel):
    """Result from PEP detection."""
    entity_screened: str
    self_declared: bool = False
    detected_level: PEPLevel = Field(default=PEPLevel.NOT_PEP)
    positions_found: list[PEPPosition] = Field(default_factory=list, description="Political positions held")
    family_associations: list[PEPFamilyAssociation] = Field(default_factory=list)
    edd_required: bool = False
    edd_expiry_date: str | None = Field(default=None, description="ISO date when EDD expires (None=permanent)")
    edd_permanent: bool = Field(default=False, description="True for FOREIGN_PEP — EDD never expires")
    search_queries_executed: list[str] = Field(default_factory=list)
    evidence_records: list[EvidenceRecord] = Field(default_factory=list)

    @classmethod
    def failed(cls, entity: str, error: str) -> "PEPClassification":
        """Create a sentinel result representing a failed agent run.

        Conservative: keeps NOT_PEP but requires EDD since we cannot confirm clear.
        """
        return cls(
            entity_screened=entity,
            detected_level=PEPLevel.NOT_PEP,
            edd_required=True,
        )


class AdverseMediaResult(BaseModel):
    """Result from adverse media screening."""
    entity_screened: str
    overall_level: AdverseMediaLevel = Field(default=AdverseMediaLevel.CLEAR)
    articles_found: list[MediaArticle] = Field(default_factory=list, description="Adverse media articles found")
    categories: list[str] = Field(default_factory=list, description="fraud, money_laundering, regulatory, etc.")
    search_queries_executed: list[str] = Field(default_factory=list)
    evidence_records: list[EvidenceRecord] = Field(default_factory=list)

    @classmethod
    def failed(cls, entity: str, error: str) -> "AdverseMediaResult":
        """Create a sentinel result representing a failed agent run.

        Conservative: LOW_CONCERN since we cannot confirm no adverse media.
        """
        return cls(
            entity_screened=entity,
            overall_level=AdverseMediaLevel.LOW_CONCERN,
        )


class EntityVerification(BaseModel):
    """Result from business entity verification."""
    entity_name: str
    verified_registration: bool = False
    registry_sources: list[str] = Field(default_factory=list)
    registration_details: dict = Field(default_factory=dict)
    ubo_structure_verified: bool = False
    discrepancies: list[str] = Field(default_factory=list)
    search_queries_executed: list[str] = Field(default_factory=list)
    evidence_records: list[EvidenceRecord] = Field(default_factory=list)

    @classmethod
    def failed(cls, entity: str, error: str) -> "EntityVerification":
        """Create a sentinel result representing a failed agent run.

        Conservative: sentinel discrepancy so downstream consumers don't
        treat an empty list as 'no issues found'.
        """
        return cls(
            entity_name=entity,
            discrepancies=[f"[VERIFICATION FAILED — {error}]"],
        )


class JurisdictionRiskResult(BaseModel):
    """Result from jurisdiction risk assessment."""
    jurisdictions_assessed: list[str] = Field(default_factory=list)
    fatf_grey_list: list[str] = Field(default_factory=list)
    fatf_black_list: list[str] = Field(default_factory=list)
    sanctions_programs: list[SanctionsProgram] = Field(default_factory=list)
    fintrac_directives: list[str] = Field(default_factory=list)
    overall_jurisdiction_risk: RiskLevel = Field(default=RiskLevel.LOW)
    jurisdiction_details: list[JurisdictionDetail] = Field(default_factory=list, description="Per-jurisdiction risk details")
    search_queries_executed: list[str] = Field(default_factory=list)
    evidence_records: list[EvidenceRecord] = Field(default_factory=list)

    @classmethod
    def failed(cls, entity: str, error: str) -> "JurisdictionRiskResult":
        """Create a sentinel result representing a failed agent run.

        Conservative: MEDIUM since we cannot confirm low jurisdiction risk.
        """
        return cls(overall_jurisdiction_risk=RiskLevel.MEDIUM)


class AMLTypology(BaseModel):
    """AML typology identified for a client profile."""
    typology_name: str
    description: str
    relevance: str = Field(default="MEDIUM", description="HIGH, MEDIUM, LOW")
    indicators: list[str] = Field(default_factory=list)
    monitoring_recommendation: str = ""


class TransactionMonitoringResult(BaseModel):
    """Result from transaction monitoring agent."""
    entity_screened: str
    industry_typologies: list[AMLTypology] = Field(default_factory=list)
    geographic_typologies: list[AMLTypology] = Field(default_factory=list)
    recommended_alerts: list[RecommendedAlert] = Field(default_factory=list)
    recommended_monitoring_frequency: str = "standard"
    sar_risk_indicators: list[str] = Field(default_factory=list)
    search_queries_executed: list[str] = Field(default_factory=list)
    evidence_records: list[EvidenceRecord] = Field(default_factory=list)

    @classmethod
    def failed(cls, entity: str, error: str) -> "TransactionMonitoringResult":
        """Create a sentinel result representing a failed agent run.

        Conservative: enhanced monitoring since we cannot confirm standard is safe.
        """
        return cls(
            entity_screened=entity,
            recommended_monitoring_frequency="enhanced",
        )


class InvestigationResults(BaseModel):
    """Container for all Stage 2 investigation findings."""
    # Individual screening
    individual_sanctions: SanctionsResult | None = None
    pep_classification: PEPClassification | None = None
    individual_adverse_media: AdverseMediaResult | None = None

    # Business screening
    entity_verification: EntityVerification | None = None
    entity_sanctions: SanctionsResult | None = None
    business_adverse_media: AdverseMediaResult | None = None

    # Shared
    jurisdiction_risk: JurisdictionRiskResult | None = None
    transaction_monitoring: TransactionMonitoringResult | None = None

    # Utility results (stored as dicts for flexibility)
    id_verification: dict | None = None
    suitability_assessment: dict | None = None
    fatca_crs: dict | None = None
    edd_requirements: dict | None = None
    compliance_actions: dict | None = None
    business_risk_assessment: dict | None = None
    document_requirements: dict | None = None
    misrepresentation_detection: dict | None = None
    sar_risk_assessment: dict | None = None

    # UBO cascade results (business only)
    ubo_screening: dict[str, dict] = Field(
        default_factory=dict,
        description="UBO name -> {sanctions, pep, adverse_media}"
    )

    # Degraded status tracking (Phase D)
    failed_agents: list[str] = Field(default_factory=list, description="Agents that failed during investigation")
    is_degraded: bool = Field(default=False, description="True if any agents failed")


# =============================================================================
# Stage 3: Synthesis
# =============================================================================

class KYCEvidenceGraph(BaseModel):
    """Cross-referenced evidence graph from synthesis."""
    total_evidence_records: int = 0
    verified_count: int = 0
    sourced_count: int = 0
    inferred_count: int = 0
    unknown_count: int = 0
    contradictions: list[GraphContradiction] = Field(default_factory=list)
    corroborations: list[GraphCorroboration] = Field(default_factory=list)
    unresolved_items: list[str] = Field(default_factory=list)


class CounterArgument(BaseModel):
    """Adversarial analysis against a disposition."""
    evidence_id: str = Field(description="Evidence record being challenged")
    disposition_challenged: str = Field(description="The disposition being argued against, e.g. FALSE_POSITIVE")
    argument: str = Field(description="The strongest case against the disposition, citing evidence")
    risk_if_wrong: str = Field(description="What happens if this disposition is incorrect")
    recommended_mitigations: list[str] = Field(default_factory=list, description="Steps to reduce residual risk")


class DecisionOption(BaseModel):
    """One selectable path for the compliance officer."""
    option_id: str = Field(description="A, B, C, D etc.")
    label: str = Field(description="Short label: CLEAR, ESCALATE, REQUEST_DOCS, REJECT")
    description: str = Field(description="One-line description of what this means")
    consequences: list[str] = Field(description="Downstream regulatory/operational consequences")
    onboarding_impact: str = Field(description="What happens to the client's onboarding")
    timeline: str = Field(description="Expected time to resolution")


class DecisionPoint(BaseModel):
    """A decision the officer needs to make, with options."""
    decision_id: str
    title: str = Field(description="e.g. 'Sanctions Disposition: Alexander Petrov'")
    context_summary: str = Field(description="Brief summary of the finding")
    disposition: str = Field(description="System's recommended disposition")
    confidence: float = Field(default=0.0)
    counter_argument: CounterArgument
    options: list[DecisionOption] = Field(default_factory=list)
    officer_selection: str | None = None
    officer_notes: str | None = None


class KYCSynthesisOutput(BaseModel):
    """Output from Stage 3 synthesis."""
    evidence_graph: KYCEvidenceGraph = Field(default_factory=KYCEvidenceGraph)
    revised_risk_assessment: RiskAssessment | None = None
    key_findings: list[str] = Field(default_factory=list)
    contradictions: list[GraphContradiction] = Field(default_factory=list)
    risk_elevations: list[RiskElevation] = Field(default_factory=list, description="Factors discovered by synthesis")
    recommended_decision: OnboardingDecision = Field(default=OnboardingDecision.ESCALATE)
    decision_reasoning: str = ""
    conditions: list[str] = Field(default_factory=list, description="Conditions for CONDITIONAL approval")
    items_requiring_review: list[str] = Field(default_factory=list)
    senior_management_approval_needed: bool = False
    decision_points: list[DecisionPoint] = Field(default_factory=list)
    adversarial_challenges: list[dict] = Field(default_factory=list, description="Red-team challenges from AdversarialReviewer")


# =============================================================================
# Stage 3.5: Review Intelligence (deterministic, between Synthesis and Review)
# =============================================================================

class SeverityLevel(str, Enum):
    """Severity levels for review intelligence findings."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    ADVISORY = "ADVISORY"


class CriticalDiscussionPoint(BaseModel):
    """A finding that demands the compliance officer's attention."""
    point_id: str
    title: str
    severity: SeverityLevel
    reason: str = Field(description="Why this requires discussion")
    evidence_ids: list[str] = Field(default_factory=list)
    source_agents: list[str] = Field(default_factory=list)
    recommended_action: str = ""


class Contradiction(BaseModel):
    """A contradiction detected between two findings or agents."""
    contradiction_id: str
    finding_a: str
    finding_b: str
    agent_a: str
    agent_b: str
    evidence_ids: list[str] = Field(default_factory=list)
    severity: SeverityLevel = SeverityLevel.MEDIUM
    resolution_guidance: str = ""


class ConfidenceDegradationAlert(BaseModel):
    """Assessment of overall evidence quality."""
    overall_confidence_grade: str = Field(default="F", description="Letter grade A-F")
    verified_pct: float = 0.0
    sourced_pct: float = 0.0
    inferred_pct: float = 0.0
    unknown_pct: float = 0.0
    degraded: bool = False
    follow_up_actions: list[str] = Field(default_factory=list)


class RegulatoryTag(BaseModel):
    """A regulatory obligation mapped to a specific finding."""
    regulation: str
    obligation: str
    trigger_description: str = ""
    evidence_id: str = ""
    filing_required: bool = False
    timeline: str = ""


class FindingWithRegulations(BaseModel):
    """An evidence finding annotated with its regulatory implications."""
    evidence_id: str
    claim: str
    source_name: str
    regulatory_tags: list[RegulatoryTag] = Field(default_factory=list)


class ReviewIntelligence(BaseModel):
    """Composite model holding all four review intelligence facets."""
    discussion_points: list[CriticalDiscussionPoint] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    confidence: ConfidenceDegradationAlert = Field(default_factory=ConfidenceDegradationAlert)
    regulatory_mappings: list[FindingWithRegulations] = Field(default_factory=list)


# =============================================================================
# Stage 4: Review Session
# =============================================================================

class ReviewAction(BaseModel):
    """A single action taken during conversational review."""
    action_type: str = Field(description="query, approve_disposition, override_risk, add_note, reinvestigate, search, resynthesize, finalize")
    query: str | None = None
    response_summary: str | None = None
    evidence_id: str | None = None
    approved_disposition: DispositionStatus | None = None
    previous_disposition: DispositionStatus | None = None
    officer_note: str | None = None
    agent_name: str | None = None
    search_results_summary: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReviewSession(BaseModel):
    """Record of the conversational review session."""
    client_id: str
    officer_name: str | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    actions: list[ReviewAction] = Field(default_factory=list)
    officer_overrides: list[OfficerOverride] = Field(default_factory=list, description="Auditable officer overrides")
    finalized: bool = False
    finalized_at: datetime | None = None


# =============================================================================
# Final Output
# =============================================================================

class KYCOutput(BaseModel):
    """Complete KYC pipeline output."""
    schema_version: str = Field(default="1.0.0", description="Schema version for migration checks")
    client_id: str
    client_type: ClientType
    client_data: dict = Field(description="Original client intake data")
    is_degraded: bool = Field(default=False, description="True if any agents failed during investigation")
    intake_classification: InvestigationPlan
    investigation_results: InvestigationResults = Field(default_factory=InvestigationResults)
    synthesis: KYCSynthesisOutput | None = None
    review_intelligence: ReviewIntelligence | None = None
    review_session: ReviewSession | None = None
    final_decision: OnboardingDecision | None = None
    aml_operations_brief: str = ""
    risk_assessment_brief: str = ""
    regulatory_actions_brief: str = ""
    onboarding_decision_brief: str = ""
    sar_narrative_draft: dict | None = Field(default=None, description="SAR/STR narrative draft from generators.sar_narrative")
    fincen_filing: dict | None = Field(default=None, description="FinCEN SAR Form 111 pre-fill")
    fintrac_filing: dict | None = Field(default=None, description="FINTRAC STR pre-fill")
    metrics: dict | None = Field(default=None, description="Pipeline metrics (timing, tokens, cost)")
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    duration_seconds: float = 0.0
