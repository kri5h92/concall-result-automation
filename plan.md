# Concall Intelligence Project Plan

## Executive Decision

Build the next version as a local, Postgres-backed concall intelligence system that keeps the existing `Outputs/Concalls/...` filesystem as the raw artifact store. The system should become an evidence-backed investment research platform for Indian equities, not only a transcript summarizer.

The operating model for v1 is batch-first:

- All stored LLM outputs are produced through batch APIs by default.
- Synchronous "normal request" execution is designed into the architecture as a controlled escape hatch, but it is disabled by default.
- Synchronous execution can later be enabled only for explicitly allowlisted task categories such as urgent single-company reruns, analyst SQL generation, prompt smoke tests, or failed-batch repair.
- Streamlit stays responsive by reading Postgres and enqueueing jobs; it must not own long-running LLM work.

This plan is intentionally split into focused project documents:

- [Investment Intelligence Plan](docs/plans/investment-intelligence-plan.md)
- [Batch-First AI Plan](docs/plans/batch-first-ai-plan.md)
- [Data And System Design Plan](docs/plans/data-system-design-plan.md)
- [Implementation Roadmap](docs/plans/implementation-roadmap.md)

## Current System Baseline

The current repo is a filesystem-first pipeline:

1. `transcript_downloader.py` downloads Screener transcript PDFs into deterministic ticker and period folders.
2. `transcript_extraction.py` converts PDFs to `Transcript.txt`.
3. `analyzer.py` runs the LLM and writes `analysis_<model>.json`.
4. `app.py` is a read-only Streamlit dashboard over saved JSON files.

That behavior remains valid. The new system adds Postgres, job orchestration, batch execution, evidence tables, and richer research views on top of the existing artifacts.

## Project Goals

- Preserve every raw source document and current JSON output.
- Import current filesystem outputs into Postgres without breaking the existing app path.
- Create typed, queryable financial facts, claims, KPIs, guidance items, evidence spans, tags, reports, alerts, and job history.
- Make transcript analysis comparable across companies, sectors, sub-sectors, and fiscal quarters.
- Add strict-quarter subsector and category reports that disclose missing companies instead of silently mixing stale periods.
- Build a batch-first LLM execution layer with cost reservation, usage reconciliation, retries, and provider-specific batch support.
- Add portfolio and watchlist workflows so the system prioritizes holdings and active watchlist companies before broad backfills.
- Support controlled synchronous execution later for specific urgent or interactive categories.

## Non-Goals For v1

- No full FastAPI + React rewrite.
- No public internet exposure; Tailscale is the initial network boundary.
- No automatic trading, recommendations, or portfolio orders.
- No silent LLM inferences without source evidence.
- No long-running jobs inside Streamlit.
- No hard-coded model pricing or unverified model IDs in the main plan.

## Architecture Overview

```text
Screener/manual upload
        |
        v
Raw filesystem artifacts
Outputs/Concalls/... and Outputs/Docs/...
        |
        v
Postgres import and artifact registry
        |
        v
Job queue and batch LLM worker
        |
        v
Validated structured outputs
claims, evidence, KPIs, guidance, facts, profile versions
        |
        v
Streamlit research interface
dashboards, strict-quarter reports, SQL views, tags, alerts
```

The filesystem is the raw record. Postgres is the queryable and orchestration record. Generated reports and profiles are projections that can be rebuilt from raw artifacts plus versioned extraction outputs.

## Batch-First Operating Model

Batch execution is not only a scheduler option; it is the default architecture for LLM work.

| Task category | v1 execution | Future sync eligibility | Notes |
| --- | --- | --- | --- |
| Latest transcript full analysis | Batch | Yes, urgent single-company rerun only | Premium model allowed here. |
| Historical transcript context extraction | Batch | No by default | Cheap model. Quote-backed context only. |
| Annual report, PPT, result filing extraction | Batch | No by default | Cheap model. Rebuilds fact base and profile. |
| Claim/KPI/tag suggestion jobs | Batch | Rare | Stored outputs must be reproducible. |
| Cross-company narrative reports | Batch | Yes, analyst-approved one-off | Input is structured facts, not raw transcripts. |
| Natural-language SQL generation | Deferred or batch ticket in v1 | Yes | Must use read-only views and SQL validation. |
| Admin prompt smoke test | Manual only | Yes | Never writes production output. |

Design the execution interface as `mode = batch | sync`, but configure v1 as `batch` for all production output categories. A future `allowed_sync_categories` setting can enable sync for selected categories without creating a second analyzer path.

## LLM Workload Policy

Use task roles instead of baking provider/model names into application logic.

| Role | Inputs | Output | Default execution |
| --- | --- | --- | --- |
| `doc_extraction` | Annual reports, PPTs, press releases, filings, quarterly results | `knowledge_facts`, `results_facts`, `ppt_facts` | Batch |
| `history_extraction` | Non-latest transcripts | `concall_context` with quotes | Batch |
| `transcript_analysis` | Latest transcript plus compact company/KPI/prior-call context | `analysis_run`, claims, KPIs, guidance, risk flags | Batch |
| `narrative_synthesis` | Claim/KPI/evidence tables for a strict quarter/filter | Investor-grade report | Batch |
| `sql_generation` | User question plus schema of safe read-only views | SQL candidate | Future sync or batch ticket |

Keep mutable model details in a future `model_registry.yaml`:

- provider
- model ID
- task role eligibility
- context limit
- batch support
- prompt/cache support
- structured-output support
- dated pricing metadata
- last verified date

Do not hard-code model price math into `plan.md`. Use the registry plus actual provider usage records.

## Canonical Period Model

The current filesystem uses folders such as `Feb 2026`. The new system needs canonical period fields:

- `folder_period`: raw folder label from disk.
- `period_start`: normalized month start date for current compatibility.
- `call_date`: actual concall date when available.
- `reported_fiscal_quarter`: fiscal quarter covered by the result.
- `reported_fiscal_year`: fiscal year covered by the result.
- `strict_quarter_key`: canonical key used for peer comparison, for example `FY2026-Q3`.

Never classify a transcript as latest by taking `max()` over period strings or over only the current batch. Latest/historical role is DB-driven:

- `latest`: most recent transcript by canonical company timeline.
- `historical`: prior transcripts within the configured history window.
- `superseded`: a transcript that was once latest but became historical after a newer call arrived.
- `manual_override`: analyst-approved correction when source metadata is wrong.

## Document Universe

Treat quarterly results as a first-class source, not just transcripts and PPTs.

| Document type | Source path | Model role | Purpose |
| --- | --- | --- | --- |
| Latest transcript | `Outputs/Concalls/<TICKER>/<Period>/Transcript.*` | `transcript_analysis` | Full evidence-backed call analysis. |
| Historical transcript | Same path | `history_extraction` | Prior guidance, metrics, management commentary. |
| Concall PPT | `Outputs/Concalls/<TICKER>/<Period>/Presentation.*` | `doc_extraction` | Slide-level numbers, guidance, segment data. |
| Quarterly result filing | `Outputs/Results/<TICKER>/<Period>/QuarterlyResults.*` | `doc_extraction` | Reported P&L, margin, debt, working capital, exceptional items. |
| Annual report | `Outputs/Docs/<TICKER>/AnnualReports/<FY>/...` | `doc_extraction` | Business segments, capacity, targets, strategic context. |
| Investor presentation | `Outputs/Docs/<TICKER>/InvestorPresentations/<Period>/...` | `doc_extraction` | Strategy, capacity, segment data, medium-term commentary. |
| Press release / filing | `Outputs/Docs/<TICKER>/PressReleases/<DateSlug>/...` | `doc_extraction` | Deals, capex, management changes, events. |

For annual reports, extract only relevant business sections where possible: MD&A, business overview, segment review, operational highlights, capacity, and strategy. Retain the full PDF but avoid sending irrelevant statutory pages to the LLM.

## Financial Fact Base

The LLM is a synthesis layer, not the source of truth. Build a typed fact layer underneath it.

Core fact categories:

- Reported financials: revenue, EBITDA, EBIT, PAT, margin, EPS, debt, cash, working capital, exceptional items.
- Segment facts: revenue, growth, margin, volume, pricing, utilization, order book, capacity.
- Guidance: metric, range, midpoint, target period, hard/soft guidance, assumptions, speaker, quote.
- KPI values: raw value, normalized value, unit, period, basis, source, confidence, extraction status.
- Risks: severity, trend, affected segment, repeat count, evidence, materiality.
- Management credibility: guidance issued, reiterated, raised, lowered, withdrawn, met, missed, ambiguous.

Quarterly results and PPT numbers should be reconciled against transcript commentary. If management says margins improved but the reported result shows a one-off, the system should capture that tension as an evidence-backed flag.

## Evidence And Provenance

Every promoted claim must have evidence.

Minimum evidence fields:

- source document ID
- document type
- page, slide, transcript section, or line/span reference where available
- speaker when available
- exact quote or table excerpt
- extraction model and prompt package version
- confidence
- validation status

Generated outputs must distinguish:

- transcript-backed claim
- background-context-derived flag
- financial-filing-backed fact
- analyst-approved tag or note
- model-generated synthesis

Background context can help the model compare and reason, but transcript claims should still cite transcript evidence. Low-confidence or high-materiality items go to a review queue.

## Typed KPI And Comparability Layer

Do not store KPIs as `dict[str, str]`. Store typed rows keyed by stable `kpi_name`.

KPI record fields:

- `kpi_name`
- `label`
- `sector`
- `sub_sector`
- `period`
- `segment`
- `raw_value`
- `normalized_value`
- `unit`
- `basis`: consolidated, standalone, segment, adjusted, reported
- `change_yoy`
- `change_qoq`
- `source_doc_id`
- `source_location`
- `quote`
- `confidence`
- `extraction_status`: found, not_disclosed, ambiguous, invalid, needs_review

`kpis.yaml` should become a sector data dictionary:

- stable KPI name
- display label
- aliases
- formula or extraction instruction
- unit and normalization rules
- polarity: higher_is_better, lower_is_better, context_dependent
- valid ranges and outlier checks
- source priority
- comparability caveats

The existing plain-text KPI blocks can be migrated gradually, but the destination schema should be typed.

## Company Profile

`CompanyProfile` is a versioned projection, not a mutable source of truth.

Use immutable profile versions:

- source document IDs and hashes
- source fact IDs
- profile JSON
- profile hash
- as-of date
- created_at

Each analysis run references the exact `company_profile_version_id` used in the prompt. Updating a profile does not silently change historical analyses. Re-analysis is explicit.

Profiles should store conflicts, not only the newest non-conflicting fact. Example: if an AR states one capacity number and a later PPT states another, both facts should remain available with source/date and conflict status.

## Job Orchestration

Use Postgres as the orchestration backbone for v1. Avoid Celery until the local setup needs it.

Durable job primitives:

- `job_runs`: scheduler/manual run metadata.
- `job_tasks`: one unit of work, state, lease, attempts, idempotency key.
- `llm_jobs`: model task, mode, provider, model, prompt package, schema version, estimated cost, actual usage.
- `llm_batch_requests`: provider batch ID, custom ID, request hash, status, result/error mapping.
- `job_errors`: normalized error class, message, retry decision.
- `llm_usage_ledger`: reserved and actual cost/tokens.

State machine:

```text
DISCOVERED
DOWNLOADED
TEXT_EXTRACTED
QUEUED
COST_RESERVED
SUBMITTED
POLLING
RESULT_RECEIVED
VALIDATED
WRITTEN
COMPLETED
```

Failure and lifecycle states:

```text
RETRYABLE_FAILED
PERMANENT_FAILED
EXPIRED
CANCELED
STALE
SUPERSEDED
NEEDS_REVIEW
```

Workers should use leases, attempt counts, retry deadlines, advisory locks or `FOR UPDATE SKIP LOCKED`, and dead-letter handling.

## Streamlit Product Surface

Streamlit remains the v1 interface. It reads Postgres and enqueues jobs only.

Views to add in sequence:

- DB-backed version of the existing JSON viewer behind a feature flag.
- Strict-quarter company comparison.
- Sub-sector KPI matrix.
- Evidence-backed claim search.
- Guidance tracker and management credibility page.
- Portfolio/watchlist dashboard.
- Document upload and processing status page.
- Job/batch status page.
- Tag management page.
- Natural-language SQL page over curated read-only views.

Long-running operations should show queued/running/completed/failed state and never block the Streamlit process.

## Natural-Language SQL Safety

Natural-language SQL is useful, but it needs strong boundaries:

- generate SQL only against curated read-only views
- use a read-only DB role
- parse SQL with an AST parser
- allow one `SELECT` statement only
- reject writes, DDL, multiple statements, unsafe functions, and unapproved tables
- enforce row limits and `statement_timeout`
- show SQL before execution
- log question, generated SQL, user, timestamp, row count, and runtime

In strict batch-only v1, SQL generation can be a queued LLM task. Later it can become an allowlisted sync category because it is interactive and cheap compared with transcript analysis.

## Cost Controls

Cost control is ledger-based:

- Estimate tokens and reserve cost before submitting a job.
- Enforce daily, monthly, run-level, and user-triggered caps.
- Track batch discount, prompt/cache reads/writes, input tokens, output tokens, retries, failures, and repairs.
- Reconcile actual provider usage after results return.
- Skip work when source hash, text hash, prompt package hash, schema hash, model ID, profile hash, and KPI hash are unchanged.
- Prioritize portfolio holdings, active watchlist, full coverage universe, and historical backfill in that order.

The plan assumes provider batch APIs can materially reduce cost for non-urgent work, but exact discounts, model support, limits, and pricing belong in a dated registry and must be verified during implementation.

## Migration Strategy

The migration should be incremental.

1. Freeze current filesystem behavior as the compatibility baseline.
2. Create Postgres schema and import current artifacts in dry-run mode.
3. Import existing PDFs, text files, JSON outputs, periods, tickers, sectors, and model metadata.
4. Build DB-backed Streamlit views behind a feature flag with filesystem fallback.
5. Add job queue tables and workers without changing analysis behavior.
6. Add batch-first LLM execution for new tasks.
7. Add typed claims, evidence, KPIs, and guidance tables.
8. Add document extraction, quarterly results, and company profile versions.
9. Add narratives, alerts, tags, and portfolio workflows.

Every phase needs rollback and parity checks.

## Test And Evaluation Gates

Default tests should not call real LLM APIs.

Required gates:

- filesystem import idempotency tests
- canonical period mapping tests
- latest/historical/superseded role tests
- SQL safety tests
- batch job state-machine tests
- provider adapter tests with mocked results
- schema validation and repair tests
- evidence quote existence tests
- KPI normalization tests
- guidance actual matching tests
- Streamlit DB parity tests
- backup/restore smoke test

Quality evals are separate from implementation tests:

- schema-valid rate
- quote precision
- numeric extraction accuracy
- guidance recall
- hallucination rate
- not-disclosed correctness
- context misuse rate
- batch retry/failure rate
- estimated vs actual cost error

## Deployment And Operations

For v1:

- Postgres binds to localhost.
- Streamlit binds to localhost or a tailnet IP only.
- Tailscale ACLs restrict access.
- Funnel stays disabled unless intentionally made public.
- Mutating actions require user identity, even if lightweight at first.
- Workers run as a separate local process, scheduled task, or service.
- Daily `pg_dump` plus filesystem backup of `Outputs/`.
- Encrypted off-machine backup copy.
- Monthly restore drill.
- Logs include run IDs, job IDs, provider batch IDs, and artifact hashes.

## Main Risks

- Treating model output as truth instead of evidence-backed synthesis.
- Misclassifying old backfills as latest transcripts.
- Letting Streamlit become a job runner.
- Mixing stale quarters in peer views.
- Hard-coding volatile model IDs, prices, and provider feature support.
- Storing display strings where typed KPI values are required.
- Adding NL SQL without parser, role, timeout, and view boundaries.
- Skipping backup/restore while DB rows reference filesystem artifacts.

## Acceptance Criteria For The Planning Phase

This planning pass is complete when:

- `plan.md` is the master project plan.
- Domain-specific plans exist under `docs/plans/`.
- Batch-first execution is the default for stored outputs.
- Sync execution is represented as a future allowlisted escape hatch.
- Quarterly results, typed KPIs, evidence, portfolio workflows, and job orchestration are included.
- The implementation sequence is phased and testable.
