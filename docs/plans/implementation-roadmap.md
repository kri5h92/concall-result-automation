# Implementation Roadmap

## Roadmap Principles

- Preserve current behavior first.
- Make the database a mirror before making it the source for UI.
- Add job orchestration before adding more LLM work.
- Add batch execution before large-scale document enrichment.
- Add typed facts and evidence before investor-grade narratives.
- Keep every phase shippable and reversible.

## Phase 0: Compatibility Baseline

Deliverables:

- Inventory current output folders, transcript PDFs, text files, and analysis JSON files.
- Document current config behavior and CLI flags.
- Define artifact hash rules.
- Define canonical ticker and period parsing rules.
- Create a dry-run import report format.

Acceptance:

- Current pipeline still runs.
- Current Streamlit JSON view still works.
- Dry-run import can count companies, periods, transcripts, text files, and analysis JSONs without writing DB rows.

## Phase 1: Postgres Mirror

Deliverables:

- Initial schema for companies, periods, documents, artifacts, raw JSON outputs, analysis runs.
- Repeatable `ingest_existing` design.
- Unique constraints and indexes for idempotency.
- DB import dry-run and real-run plan.

Acceptance:

- Running import twice creates no duplicates.
- Imported counts match filesystem inventory.
- Existing JSON is stored as raw JSONB.
- No LLM calls are made.

## Phase 2: DB-Backed Streamlit Read Path

Deliverables:

- Read-only DB views matching the existing dashboard.
- Feature flag for DB mode.
- Filesystem fallback.
- Connection handling and query caching rules.

Acceptance:

- DB mode and filesystem mode show the same companies, periods, and latest analysis selections.
- Streamlit does not enqueue or execute long jobs yet.
- Query performance is acceptable for 5-10 active users.

## Phase 3: Canonical Period And Strict-Quarter Reports

Deliverables:

- Canonical fiscal period model.
- Latest/historical/superseded role calculation.
- Strict-quarter inclusion logic.
- Missing-company disclosure.

Acceptance:

- Old backfills are not misclassified as latest.
- Strict-quarter report includes only matching quarter companies.
- Missing companies are listed with reason.
- Manual period override is auditable.

## Phase 4: Job Queue And Worker

Deliverables:

- `job_runs`, `job_tasks`, `job_errors`.
- Worker lease model.
- Retry and dead-letter design.
- Scheduler singleton lock.
- Job status Streamlit page.

Acceptance:

- Streamlit can enqueue a non-LLM test job.
- Worker completes the job and updates status.
- Duplicate scheduler instances do not create duplicate tasks.
- Retry and permanent failure states are visible.

## Phase 5: Batch-First LLM Execution

Deliverables:

- `llm_jobs`, `llm_batch_requests`, `llm_usage_ledger`.
- Provider adapter contract.
- Batch request manifest format.
- Cost reservation and reconciliation.
- Raw provider response storage.
- Validation pipeline.

Acceptance:

- Mock batch provider can submit, poll, complete, fail, and expire jobs.
- Result mapping uses `custom_id`, not output order.
- Cost cap blocks over-budget jobs before submission.
- Production outputs use batch mode by default.
- Sync mode exists only behind allowlisted categories.

## Phase 6: Evidence, Claims, KPIs, And Guidance

Deliverables:

- `claims` and `claim_evidence`.
- Typed KPI definitions and values.
- Guidance item lifecycle.
- Evidence quote validation.
- Review queue.

Acceptance:

- Every promoted claim has evidence.
- KPI values are typed and queryable.
- Not-disclosed is represented as status.
- Guidance changes can be tracked across periods.
- Low-confidence/high-materiality items enter review.

## Phase 7: Document Expansion And Company Profiles

Deliverables:

- Quarterly result filings as first-class documents.
- Concall PPT extraction.
- Annual report section extraction.
- `company_knowledge_facts`.
- Immutable `company_profile_versions`.
- Analysis runs reference profile version used.

Acceptance:

- Result filings populate reported financial facts.
- PPT and annual report facts update profile versions.
- Profile updates do not mutate historical analysis runs.
- Conflicting facts remain visible with source provenance.

## Phase 8: Investment Workflows

Deliverables:

- Portfolio/watchlist tables.
- Batch priority based on materiality.
- Guidance tracker page.
- KPI heatmap.
- Risk dashboard.
- Tag workflow.
- Evidence-backed narrative reports.

Acceptance:

- Holdings and watchlist companies process before low-priority backfills.
- Strict-quarter narratives cite structured evidence.
- Risk dashboard shows severity, trend, repeat count, and evidence.
- Tag assignments are auditable.

## Phase 9: Operations Hardening

Deliverables:

- Daily DB and filesystem backup.
- Restore drill.
- Observability dashboard.
- SQL safety controls.
- Tailscale access checklist.
- Runbooks for failed batch, stale analysis, restore, and provider outage.

Acceptance:

- Restore drill succeeds.
- SQL runs only through read-only views and role.
- Logs contain run/job/provider IDs.
- Provider outage creates retryable jobs and alerts instead of silent loss.

## Test Strategy

Default tests:

- no real LLM calls
- fixture-based filesystem tests
- fixture-based Postgres tests
- mocked provider adapters
- deterministic prompt/package hash tests

Explicit smoke tests:

- one cheap model document extraction
- one premium transcript analysis
- one provider batch submission against a small fixture

Eval tests:

- labeled transcript and document set
- numeric extraction accuracy
- quote precision
- guidance recall
- KPI recall
- hallucination rate
- context misuse rate

## Rollback Rules

Every phase should define:

- DB migrations to apply
- DB rollback or forward-fix path
- feature flag to disable new UI path
- artifact compatibility impact
- data backfill repeatability
- how to re-run import without duplicates

No phase should require deleting current `Outputs/` artifacts.

## Deferred Items

Defer until v2 or later:

- FastAPI + React rewrite
- Celery/Redis or distributed workers
- fully automated BSE/NSE filing ingestion beyond v1 sources
- public deployment
- complex permission system
- automated trading or recommendation workflows
