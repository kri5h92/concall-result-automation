# Data And System Design Plan

## Design Position

Use Postgres as both the query layer and orchestration backbone. Keep the raw filesystem as the immutable artifact layer.

Do not move directly to a distributed queue or web backend. For the expected scale of about 50 users and 5-10 active users, local Postgres, Streamlit, and one or more worker processes are enough if responsibilities are separated.

## Storage Layers

| Layer | Responsibility |
| --- | --- |
| Filesystem | Raw PDFs, extracted text, raw JSON outputs, provider raw responses, debug artifacts. |
| Postgres core tables | Companies, periods, documents, artifacts, jobs, analyses, claims, evidence, KPIs. |
| Postgres projections | Profile versions, report outputs, dashboard views, materialized summaries. |
| Streamlit cache | Short-lived UI cache only; not a source of truth. |

## Core Tables

Company and period:

- `companies`
- `company_aliases`
- `fiscal_periods`
- `company_periods`

Artifacts:

- `documents`
- `document_artifacts`
- `document_sources`
- `raw_json_outputs`

LLM and jobs:

- `job_runs`
- `job_tasks`
- `job_errors`
- `llm_jobs`
- `llm_batch_requests`
- `llm_usage_ledger`

Research outputs:

- `analysis_runs`
- `analysis_sections`
- `claims`
- `claim_evidence`
- `guidance_items`
- `guidance_actuals`
- `kpi_definitions`
- `analysis_kpi_values`
- `company_knowledge_facts`
- `concall_contexts`
- `company_profile_versions`
- `narrative_reports`

Workflow:

- `tags`
- `tag_suggestions`
- `tag_assignments`
- `alerts`
- `alert_events`
- `watchlists`
- `watchlist_items`
- `portfolio_positions`
- `review_queue`
- `audit_log`

## Key Constraints

Examples of required uniqueness:

- company ticker unique after canonicalization
- one document per company, document type, source URL/hash, and fiscal period
- one artifact per document, artifact type, parser version, and content hash
- one analysis run per document, model, prompt package, schema version, profile version, and KPI hash
- one accepted KPI value per analysis run and `kpi_name`, unless segmented
- one active tag assignment per entity and tag
- one alert event per rule and source event hash

All generated rows should carry source artifact hashes and version fields.

## Canonical Period Design

Separate:

- source folder period
- call date
- result announcement date
- fiscal quarter
- fiscal year
- dashboard quarter label
- strict-quarter comparison key

The current Indian fiscal mapping can remain, but it must be stored centrally and tested.

Latest/historical role:

- computed from DB-wide company timeline
- recalculated when new transcripts arrive
- manually overrideable
- never based only on current batch contents

## Document Lifecycle State

```text
DISCOVERED
DOWNLOADED
TEXT_EXTRACTED
FACTS_QUEUED
FACTS_EXTRACTED
FACTS_VALIDATED
PROFILE_REBUILT
READY
```

Failure states:

```text
DOWNLOAD_FAILED
TEXT_EXTRACTION_FAILED
RETRYABLE_FAILED
PERMANENT_FAILED
NEEDS_REVIEW
STALE
SUPERSEDED
```

## Analysis Lifecycle State

```text
QUEUED
COST_RESERVED
BATCH_SUBMITTED
POLLING
RESULT_RECEIVED
SCHEMA_VALIDATED
EVIDENCE_VALIDATED
NORMALIZED
WRITTEN
COMPLETED
```

Failure states:

```text
EXPIRED
CANCELED
RETRYABLE_FAILED
PERMANENT_FAILED
NEEDS_REVIEW
STALE
```

## Worker Model

Streamlit enqueues and reads. Workers execute.

Worker rules:

- Claim tasks with leases.
- Use `FOR UPDATE SKIP LOCKED` or advisory locks.
- Record `attempt_count`, `locked_by`, `locked_until`, and `next_retry_at`.
- Renew lease during long work.
- Mark abandoned jobs retryable after lease expiry.
- Write provider batch IDs before polling.
- Dead-letter after max attempts.

One scheduler instance should be active. Use DB locking to prevent duplicate scheduled runs.

## Streamlit Boundary

Streamlit responsibilities:

- render dashboards
- show job state
- enqueue manual jobs
- accept document uploads
- collect tag/review actions
- run read-only queries against curated views

Streamlit must not:

- scrape documents directly
- call LLM providers directly
- poll provider batch APIs in the UI process
- run long migrations
- write raw analysis outputs without worker validation

## NL SQL Boundary

Use curated read-only views:

- `v_company_latest_analysis`
- `v_strict_quarter_claims`
- `v_subsector_kpis`
- `v_guidance_tracker`
- `v_risk_flags`
- `v_document_coverage`
- `v_batch_status`

Safety controls:

- read-only DB role
- single `SELECT`
- AST validation
- table/view allowlist
- column allowlist for sensitive fields
- row limit
- statement timeout
- query audit log
- displayed SQL before execution

## Security And Access

Tailscale is network access, not full application auth.

Minimum v1 controls:

- Postgres binds to localhost.
- Streamlit binds to localhost or tailnet IP only.
- Tailscale ACLs restrict users.
- Tailscale Funnel disabled unless intentionally public.
- Mutating pages require user identity or local login/PIN.
- Audit log for uploads, tags, reviews, sync LLM jobs, and SQL execution.
- Secrets stay in `.env` or local secret manager, not in DB rows or logs.

## Backup And Restore

Back up DB and filesystem together.

Required:

- daily `pg_dump`
- daily archive of `Outputs/`
- hash manifest for artifacts
- encrypted off-machine copy
- retention policy
- monthly restore drill
- restore checklist that validates DB rows against artifact paths and hashes

If Postgres is restored without matching files, evidence links and artifacts become unreliable.

## Observability

Log with stable IDs:

- run ID
- job ID
- llm job ID
- provider batch ID
- custom ID
- company ID
- document ID
- artifact hash
- prompt package hash

Dashboards:

- jobs by state
- batch success/failure/expiry rate
- cost reserved vs actual
- stale analysis count
- evidence validation failures
- review queue count
- missing documents by company/quarter
- extraction quality metrics

## Compatibility Strategy

The existing JSON files remain valid.

During migration:

- Import JSON as raw JSONB.
- Normalize sections and claims into relational tables.
- Keep DB-backed Streamlit behind a feature flag.
- Retain filesystem fallback until parity is proven.
- Do not delete existing outputs.
- Write new outputs to both filesystem and DB where required for compatibility.
