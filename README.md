# KYC Client Onboarding Intelligence System

**What can a compliance officer now do that they couldn't before?**

A single command screens a client across sanctions lists, PEP databases, adverse media, corporate registries, and jurisdiction risk — across every beneficial owner — in minutes instead of hours. The officer gets an evidence-linked risk profile, counter-arguments against every disposition, and an interactive review session where they can interrogate the findings before making a decision.

This is investigative depth at scale. Not automation of existing workflows — expansion of what's possible in a compliance review.

**AI investigates. Rules classify. Humans decide.**

## Quick Start

```bash
cd kyc-intelligence
pip install -r requirements.txt
cp .env.example .env    # Add your ANTHROPIC_API_KEY

python main.py --client test_cases/case3_business_critical.json
```

### What Happens

1. **Intake** classifies risk and plans the investigation (deterministic)
2. **Investigation** runs 9 AI agents + UBO cascades across 5 jurisdictions
3. **Synthesis** (Opus) cross-references 40+ evidence records, surfaces contradictions
4. **Adversarial Review** — a red-team agent challenges every match and every clear
5. **Officer Review** — the compliance officer asks questions, approves dispositions, decides
6. **Reports** — 4 department briefs + PDFs, Excel workbook, SAR/STR narrative, filing pre-fills

```
[review] > Why is Viktor Petrov flagged?
┌─ Review Assistant ────────────────────────────┐
│ Viktor Petrov [EV_012] triggered a POTENTIAL   │
│ MATCH against OFAC SDN list entry for Viktor   │
│ Petrov (DOB mismatch: 1972 vs 1968). The 51%  │
│ ownership stake triggers the OFAC 50% rule...  │
└────────────────────────────────────────────────┘
[review] > decide dp_1 B
  Decision recorded: Sanctions Disposition: Alexander Petrov
    Selected: [B] ESCALATE — Refer to senior compliance for review
[review] > finalize
```

### Pipeline Metrics (Sample Case 3 Run)

| Metric | Value |
|--------|-------|
| Total time | ~90s |
| Agents | 9 + 3 UBO cascades |
| Total tokens | ~50K |
| Estimated cost | ~$0.45 |
| Evidence grade | B |
| Web searches | ~30 |

## Architecture

```
Stage 1          Stage 2           Stage 3          Stage 4        Stage 5      Stage 6
Intake &    -->  Investigation -->  Synthesis   -->  Adversarial -> Interactive  -> Final
Classification   (AI + Rules)      (Opus AI)        Review         Review         Reports
                                                    (AI)           (Human)
deterministic    9 agents +        cross-ref        red-team       ask questions  4 briefs
risk scoring     UBO cascades      contradict       challenge      decide         + PDFs
reg detection    12 utilities      counter-args     assumptions    approve        + Excel
```

### Stage 2: Investigation Agents

| Agent | Individual | Business | What It Does |
|-------|-----------|----------|-------------|
| IndividualSanctions | Y | UBO cascade | CSL, OpenSanctions, Global Affairs Canada, UN lists |
| PEPDetection | Y | UBO cascade | FINTRAC PEP classification (HIO, HIF, DP, DPF, FP — 5 levels) |
| IndividualAdverseMedia | Y | UBO cascade | Negative news, CanLII legal databases |
| EntityVerification | | Y | Corporate registry (Corporations Canada, ONBIS, BC Registry, REQ, SEDAR+) |
| EntitySanctions | | Y | Entity screening + OFAC 50% rule |
| BusinessAdverseMedia | | Y | Trade compliance, regulatory actions |
| JurisdictionRisk | Y | Y | FATF grey/black, OFAC sanctions programs |
| KYCSynthesis | Y | Y | Cross-references all evidence, surfaces contradictions (Opus) |
| AdversarialReviewer | Y | Y | Red-team: challenges every disposition for HIGH/CRITICAL cases (Opus) |

Plus 12 deterministic utilities: ID verification, suitability (CIRO 3202), FATCA/CRS, EDD triggers, compliance actions, business risk assessment, document requirements, SAR risk assessment.

### Canadian Regulatory Coverage

Built for Canadian financial institutions with US cross-border support:

- **FINTRAC** — PEP classification (5 categories), LVCTR (crypto >$10K, 15-day filing), EFTR (international wire >$10K, 5 business days)
- **CIRO 3202** — Suitability assessment for securities dealers
- **PCMLTFA** — Risk-based approach, record retention, compliance program requirements
- **Sanctions** — Global Affairs Canada SEMA lists, Public Safety Canada s.83.05, JVCFOA/Magnitsky Act, OFAC SDN/SSI
- **Cross-border** — FinCEN SAR filing pre-fill, FATCA/CRS dual-citizenship US person detection, OFAC 50% rule for UBO chains

### Evidence Classification (V/S/I/U)

Every finding is tagged with an evidence level — this is what makes AI confidence legible to humans:

- **V (Verified)** — URL + direct quote from government registry or official list
- **S (Sourced)** — URL + excerpt from major news or regulatory database
- **I (Inferred)** — Derived from multiple signals, reasoning chain documented
- **U (Unknown)** — Explicitly searched but not found

Tier-0 sources (government registries, official sanctions lists) are auto-elevated to Verified. Tier-3 sources are capped at Inferred. Evidence quality is auto-graded (A-F). Grade A requires 60%+ Verified/Sourced. Low grades trigger extended review time and follow-up actions.

### Model Routing

| Component | Model | Rationale |
|-----------|-------|-----------|
| 7 research agents | Sonnet 4.6 | Fast, cost-effective search + analysis |
| Synthesis | Opus 4.6 | Complex cross-referencing and reasoning |
| Adversarial reviewer | Opus 4.6 | Skeptical challenge of all dispositions |
| Review assistant | Opus 4.6 | Nuanced compliance Q&A with evidence |

### Risk Scoring

Two-pass point-based scoring (deterministic):

| Score | Level | Action |
|-------|-------|--------|
| 0-15 | LOW | Standard onboarding |
| 16-35 | MEDIUM | Enhanced monitoring |
| 36-60 | HIGH | Senior review required |
| 61+ | CRITICAL | Senior management + EDD |

PEP status includes 5-year decay (residual risk after leaving office). UBO risk contributes at 0.75 factor. Verified evidence weighted 1.5x in confidence grading.

## Test Cases

| Case | Client | Risk | Key Features |
|------|--------|------|-------------|
| 1 | Sarah Thompson | LOW | Canadian nurse, clean profile — fast path |
| 2 | Maria Chen-Dubois | HIGH | Domestic PEP, Hong Kong birth, dual tax residency |
| 3 | Northern Maple Trading | CRITICAL | Import/export, Russia corridor, 3 UBOs, OFAC 50% rule |
| 4 | David Chen | MEDIUM | Gray area — Hong Kong import/export, ambiguous signals |
| 5 | Maria Rodriguez | LOW | Sparse data — tests graceful handling of missing information |
| 6 | Mohammed Ali | MEDIUM | Common name — tests disambiguation across screening lists |
| 7 | Pacific Rim Consulting | HIGH | Adversarial — hidden Russian connections behind Singapore front |

### Running Tests

602 tests across 36 files covering agent logic, pipeline integrity, evidence classification, graceful degradation, and structural correctness.

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest tests/ -v

# Non-interactive mode (skips officer review)
python main.py --client test_cases/case1_individual_low.json --non-interactive
```

## Production Hardening

Beyond the core pipeline, the system includes:

- **PII sanitization** — Regex PII masking (SIN, DOB, email, phone) at log level + model-aware field redaction
- **At-rest encryption** — Optional Fernet encryption for result files (`ENCRYPT_RESULTS=true`)
- **Atomic writes** — All checkpoints, stage results, and review sessions use write-tmp-then-rename
- **Multicultural name parsing** — Western, East Asian, Arabic, Hispanic conventions with cultural hints
- **Feedback tracking** — Decision outcome recording + calibration metrics (false positive/negative rates)
- **Cost controls** — Per-case and daily budget thresholds with configurable alerts
- **Graceful degradation** — Failed agents produce sentinel results, `is_degraded` propagates through synthesis

## Results Directory

```
results/{client_id}/
  pipeline_metrics.json      # Timing, tokens, cost, evidence grade
  checkpoint.json
  01_intake/                 # Risk classification + investigation plan
  02_investigation/          # Evidence store + screening results
  03_synthesis/              # Evidence graph + proto-reports + review intelligence
  04_review/                 # Review session log (queries, decisions, notes)
  05_output/                 # Final briefs (MD + PDF) + Excel + SAR + case package
```

## Design Decisions

See [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md) for:
- What breaks at scale (the review queue, not the AI)
- Why AI must stop at disposition (accountability, incomplete world models)
- Evidence classification as core architecture
- Graceful degradation strategies
- Privacy architecture and PIPEDA alignment
- Cost model at 100/1,000/10,000 cases per day
- Adversarial resilience and its limitations

## Tech Stack

- Python 3.12+ with Pydantic v2
- Anthropic Claude API (Opus 4.6 + Sonnet 4.6)
- Rich for terminal UI and interactive review
- fpdf2 for PDF generation, openpyxl for Excel export
- rapidfuzz for sanctions list fuzzy matching
- Trade.gov CSL API + OpenSanctions for screening
- PyYAML for risk configuration overrides
