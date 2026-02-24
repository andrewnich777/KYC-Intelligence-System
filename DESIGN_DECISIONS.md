# Design Decisions

**KYC Client Onboarding Intelligence System**
*AI investigates. Rules classify. Humans decide.*

This document captures the architectural reasoning behind key design choices, the tradeoffs we accepted, and the problems we chose not to solve yet.

---

## 1. What Breaks at Scale

The bottleneck in any KYC screening system is not the AI. It is the human review queue.

At 10 cases per day, a compliance officer can read every synthesis report, examine every piece of evidence, and make a considered decision. At 100+ cases per day, that model collapses. The solution is not more AI -- it is better queue management.

- **Priority routing via review intelligence severity scores.** CRITICAL cases (sanctions matches, high-risk jurisdictions, PEP with adverse media) surface first. LOW-risk cases with Grade A evidence sit in the queue until an officer has bandwidth, or get fast-tracked through a streamlined review path. The severity score is deterministic, computed from the same risk scoring and evidence classification the system already produces.
- **Evidence quality auto-grading to fast-track Grade A cases.** A case where 60%+ of evidence is Verified or Strong, with no contradictions, no confidence degradation, and a LOW risk score is qualitatively different from a case built on Insufficient and Unknown evidence. Grade A cases can move through an expedited review path -- the officer still decides, but the review is shorter because the evidence speaks for itself.
- **Cohort detection across concurrent cases.** If 15 cases in a single batch all involve the same jurisdiction, that is not 15 independent reviews -- it is one jurisdiction assessment applied to 15 cases. At scale, surfacing these patterns so officers can review cohorts instead of individuals becomes the primary throughput multiplier.

The temptation at scale is to let AI make more decisions. That is the wrong response. The right response is to give humans better tools for prioritizing their attention.

---

## 2. Why AI Must Stop at Disposition

The system's architecture enforces a hard boundary: AI gathers evidence and frames the decision, but it cannot make the final call. This is not a temporary limitation. It is a permanent design constraint, for four reasons.

- **Accountability requires a human on record.** When a regulator asks why a client was onboarded or declined, there must be a named individual who made that judgment. "The AI decided" is not an acceptable answer under FINTRAC guidelines, OSFI expectations, or any Canadian provincial securities regulation. The officer's signature on the disposition is not a formality -- it is the legal mechanism that makes the decision auditable.
- **AI has incomplete world models.** The system searches public records, sanctions lists, adverse media, and regulatory databases. It cannot know about a private settlement, an ongoing but sealed investigation, a verbal agreement between counterparties, or a relationship that exists only in the officer's institutional memory. The human's judgment integrates context that AI cannot access because that context was never digitized or made public.
- **Regulatory interpretation drifts and AI training data lags.** Regulations change. Enforcement priorities shift. A sanctions designation that was imminent last month may have been quietly dropped. An industry that was low-risk last year may now be under enhanced scrutiny due to a recent enforcement action. AI models are trained on historical data and cannot reliably track the leading edge of regulatory intent. A compliance officer reading FINTRAC advisories and OSFI communications in real time has access to interpretive context that no model possesses.
- **Adversarial entities will eventually learn to evade AI patterns.** Any automated screening system creates a target for adversarial adaptation. If the system auto-approves cases that meet certain evidence profiles, sophisticated actors will learn to construct those profiles. A human reviewer introduces unpredictability and judgment that cannot be reverse-engineered from the system's outputs. The human is not just a checkpoint -- they are a defense against adversarial gaming.

The synthesis report is designed to make the officer's job easier, not to replace it. Review intelligence (discussion points, contradictions, confidence degradation, regulatory mapping) exists specifically to arm the human with the right questions, not the right answers.

---

## 3. "Rules Classify" -- The Nuance

The tagline places rules between AI and humans for a reason. Rules handle the obligations that are explicit in regulation, where there is no room for interpretation.

- **PEP detected → Enhanced Due Diligence required.** This is not a judgment call. It is a regulatory obligation. The rule fires deterministically.
- **Sanctions list match above threshold → DECLINE.** There is no "maybe" on a confirmed sanctions match. The rule produces the only correct output.
- **High-risk jurisdiction + specific industry → additional document requirements.** The regulation specifies the combination. The rule encodes it.

Rules produce repeatable, auditable, bias-free results for the regulatory minimum. Two officers reviewing the same case will always see the same rule-based classifications, because the rules do not depend on interpretation. This is critical for audit trails and regulatory examinations.

AI handles the ambiguity that rules cannot reach:

- Is this adverse media article *material* to the client's risk profile, or is it a decade-old resolved dispute?
- Is this entity ownership structure *suspicious*, or is it a standard multi-jurisdiction holding pattern for the industry?
- Does this collection of individually benign facts constitute a *pattern* that warrants concern?

These questions require synthesis, contextual reasoning, and judgment about relevance. Rules cannot answer them. AI can investigate them and present findings. But the final interpretation still belongs to the human.

The separation is not AI vs. rules. It is: rules handle what regulation makes explicit, AI handles what regulation leaves ambiguous, and humans handle what requires accountability.

---

## 4. Evidence Classification as Core Architecture

Every piece of evidence the system produces is classified into one of four categories: **Verified (V)**, **Strong (S)**, **Insufficient (I)**, or **Unknown (U)**. This is not a nice-to-have. It is the architectural feature that makes the entire system legible to humans.

- **It makes AI confidence legible.** Without classification, the synthesis report is a wall of text. The officer has no way to know which findings are anchored in verified sources and which are inferences from incomplete data. Evidence classification converts AI output into something an officer can assess at a glance: "This case has 70% Verified/Strong evidence" means something different from "This case has 40% Insufficient/Unknown evidence."
- **It enables confidence grading.** The system computes evidence grades (A through F) based on the distribution of V/S/I/U classifications. Grade A requires 60%+ Verified or Strong evidence. This grade drives downstream behavior: review time estimates, priority routing, fast-track eligibility. The grade is a compression of evidence quality into a single actionable signal.
- **It creates a feedback signal for review.** Low-grade evidence (D/F) tells the officer something specific: the AI could not find reliable sources, the web searches returned thin results, or the available information was contradictory. This is more useful than a generic "low confidence" flag because it points to *why* the system is uncertain, not just *that* it is uncertain. The officer can then direct manual verification efforts to the specific evidence gaps.
- **It prevents the black box problem.** A system that outputs "HIGH RISK" without showing its evidence quality is asking the officer to trust it. A system that outputs "HIGH RISK, evidence grade C, 35% Verified, 25% Unknown, 2 contradictions detected" is asking the officer to evaluate it. The second system is auditable. The first is not.

Evidence classification is computed deterministically from the agent outputs. The AI assigns initial classifications during investigation; the evidence classifier and review intelligence modules validate and adjust them using rules. This hybrid approach -- AI generates, rules validate -- keeps classification consistent across cases.

---

## 5. Graceful Degradation

The system is designed to fail safely. Every failure mode has a defined response, and the response is always conservative.

- **Evidence quality drops to Grade D or F.**
  - Alert the reviewing officer with an explicit low-confidence warning.
  - Extend the estimated review time to account for manual verification.
  - Flag specific evidence gaps for targeted follow-up.
  - Never compensate for missing evidence with AI speculation.

- **API rate limits hit (sanctions lists, web search, web fetch).**
  - Exponential backoff with configurable retry limits.
  - Checkpoint the pipeline state so the case can resume from the last successful stage.
  - If retries are exhausted, mark affected checks as INCOMPLETE rather than PASS.

- **Synthesis fails (API error, context too large, model refusal).**
  - Escalate all raw findings directly to the officer for manual review.
  - Include an explanation of why synthesis could not be completed.
  - The officer receives more information, not less -- just without the AI's organizational layer.

- **Web search returns no results for a query.**
  - Mark the corresponding evidence as UNKNOWN.
  - Never fabricate results or infer from absence. "No results found" is a legitimate finding that the officer should see.
  - Log the query for potential retry with alternative search terms in a future pass.

- **Screening list API is unavailable.**
  - Fall back to local fuzzy matching against cached list data if available.
  - If no cached data exists, mark sanctions screening as INCOMPLETE.
  - Never report a clean sanctions check when the check could not be performed.

The principle is consistent: when the system cannot do its job well, it says so explicitly and defers to the human. Silent failure is the only unacceptable failure mode.

---

## 6. Future Directions

The following capabilities are identified but intentionally not built. They represent natural extensions of the current architecture.

- **Continuous monitoring.** Currently the system screens at onboarding. A production deployment would re-screen clients on a schedule (quarterly, annually, or triggered by external events like new sanctions designations). The checkpoint and pipeline architecture already supports re-running individual stages against updated data.
- **Policy diff engine.** When regulations change -- new FINTRAC guidance, updated OSFI expectations, amended provincial securities rules -- the system could detect which active clients are affected and trigger re-evaluation. This requires a structured representation of regulatory requirements that can be diffed against previous versions.
- **Multi-institution benchmarking.** Anonymized, aggregated pattern sharing across institutions: "Clients in this jurisdiction-industry combination are declined at 3x the baseline rate across participating institutions." This requires careful privacy engineering but could surface systemic risks that no single institution can detect from its own case volume.

None of these features require architectural changes to the current system. The pipeline's stage-based design, evidence classification model, and review intelligence framework provide the extension points. The decision to defer them is about scope discipline, not technical limitation.

*Note: Adversarial review (Section 9) and feedback calibration (Section 11) were originally scoped as future directions and have since been implemented.*

---

## 7. Privacy Architecture

PII flows through the system at every stage: intake captures names, dates of birth, SINs, and addresses. Evidence records may contain PII in claims and supporting data. Reports embed PII in narratives and filings.

The approach is layered:

- **Model-level tagging.** Pydantic fields carrying PII are annotated with `pii=True` in their `json_schema_extra`. This metadata is queryable — any component that handles these models can ask "which fields are sensitive?" without hard-coding a list. The tagging is declarative; it does not change runtime behavior by itself.
- **Log sanitization.** The logging formatter applies regex-based redaction (SIN patterns, DOB patterns, emails, phone numbers) to all messages at INFO level and below. WARNING and above are left intact so operators can diagnose production issues, but the pipeline's structured output — not raw PII — is what flows through logs.
- **Evidence store redaction.** `to_redacted_list()` returns evidence records with PII fields masked. This is used for debug output and web API responses that should not expose raw client data.
- **Optional at-rest encryption.** Gated behind `ENCRYPT_RESULTS=true`, result files are encrypted with Fernet before being written to disk. The key comes from `ENCRYPTION_KEY` env var or is auto-generated and stored in `.kyc_key` (gitignored).

PIPEDA alignment: the legal basis for processing is the institutional compliance obligation under PCMLTFA. Retention follows the 5-year PCMLTFA requirement. The system does not implement client-facing data portals or cross-institution sharing — those are out of scope for an internal screening tool.

---

## 8. Cost & Scale

The cost model at current Anthropic pricing:

- **Per case:** ~$0.50–0.75 for a standard investigation (Sonnet research agents + Opus synthesis). HIGH/CRITICAL cases cost more due to adaptive token budgets (+50%/+100% tool call limits).
- **At 100 cases/day:** ~$50–75/day, $1,500–2,250/month. Manageable for a mid-size compliance team.
- **At 1,000 cases/day:** ~$500–750/day. Requires batch optimization — selective agent dispatch (not all LOW-risk cases need full sanctions + PEP + adverse media sweeps), result caching for repeat screenings, and risk-stratified investigation depth (already built).
- **At 10,000 cases/day:** Queue management, priority routing, tiered investigation. The current architecture supports this via the investigation planner's scope field (`standard` / `enhanced` / `full`), but operational tooling (job queues, dashboards, SLA tracking) would need to be built.

Latency: ~90s median for a full investigation (8 parallel agents + synthesis), ~15s for a LOW-risk fast path with reduced agent set. The bottleneck is web search latency from the research agents, not token generation.

Cost alerting (`CostThresholds`) warns when a single case or daily budget exceeds configurable limits. Batch aggregation (`BatchMetrics`) tracks cost per case over time via a JSONL log, enabling trend analysis and projected monthly spend.

---

## 9. Adversarial Resilience

The adversarial reviewer exists because screening systems create a target. If a system consistently clears cases that match certain evidence profiles, sophisticated actors will learn to construct those profiles.

The red-team agent receives the complete synthesis output and evidence store, then challenges every disposition — both matches AND clears. For each finding it asks: "What would a sophisticated actor do to make this look clean?" and "What evidence is missing that would change this conclusion?"

The agent runs automatically for HIGH and CRITICAL risk cases after synthesis. Its output is a list of structured challenges appended to the synthesis output and surfaced in review intelligence.

Limitations: the adversarial reviewer is an AI reasoning about AI output. It cannot detect deception that the original agents also missed. Its value is in forcing the compliance officer to consider specific failure modes — name variants not checked, jurisdictions not covered, assumptions that depend on single differentiators. It is a structured prompt for human skepticism, not a replacement for it.

---

## 10. Name Resolution

Canadian financial institutions serve a multicultural client base. A naive `full_name.split()` fails for:

- **East Asian names** where family name comes first (Chen Wei Ming → family=Chen, not Ming)
- **Arabic names** with compound family names and connector particles (Mohammed bin Salman al-Rashid → family=al-Rashid)
- **Hispanic names** with dual family names (Carlos Garcia Lopez → family=Garcia Lopez)
- **Honorifics and suffixes** that should not be treated as name components (Dr. James Smith Jr.)

The name parser uses a cultural hint (inferred from citizenship or country of birth) to select the appropriate parsing convention. It always preserves the original string for display and sanctions matching — the parsed components are used for regulatory filings (FinCEN SAR Form 111, FINTRAC STR) where first/middle/last fields are required.

For screening, the parser generates name variants (reversed order, without honorifics) to improve fuzzy matching against sanctions lists. This reduces false negatives where a name recorded in family-first order in one database appears given-first in another.

---

## 11. Feedback & Calibration

Risk scoring without feedback is calibration by assumption. The feedback tracker records two types of events: onboarding decisions (APPROVE, DECLINE, ESCALATE, CONDITIONAL) and post-onboarding outcomes (SAR filed, account frozen, no issues).

From these signals, the system computes:

- **False negative rate:** Approved clients who later generated SARs. If this exceeds 5%, the approval threshold may be too permissive.
- **False positive rate:** Escalated/declined clients where no issues emerged. If this exceeds 50%, the system is creating unnecessary officer burden.
- **Calibration drift:** Whether specific risk factor categories (PEP, jurisdiction, industry) are systematically over- or under-weighted relative to actual outcomes.

The feedback loop is intentionally passive — it reports metrics and suggests calibration adjustments, but does not automatically modify risk scoring weights. Automated weight adjustment would risk encoding officer bias into the scoring model. The human compliance team reviews calibration reports and decides whether to adjust thresholds.

Data is stored as append-only JSONL, keeping the implementation simple and auditable. No database dependency, no migration complexity — just a log file that grows over time.
