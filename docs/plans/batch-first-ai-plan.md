# Batch-First AI Plan

## Operating Rule

All production LLM outputs are batch by default in v1. Synchronous execution is a capability in the design, not the default path.

The same `llm_jobs` abstraction should support both modes:

- `batch`: default for stored outputs.
- `sync`: allowlisted escape hatch, disabled for production categories until explicitly enabled.

This prevents two analyzer implementations from drifting.

## Provider Assumptions

Provider capabilities change. Treat these as dated assumptions to verify during implementation.

- OpenAI Batch API currently documents asynchronous jobs with 50% lower costs, separate higher rate limits, JSONL input, 24-hour turnaround, `custom_id` result mapping, and supported endpoints including Responses, Chat Completions, Embeddings, Completions, and Moderations.
- Anthropic Message Batches currently document asynchronous Message API batch processing, custom IDs, up to 24-hour completion, and provider batch result retrieval.
- Gemini Batch API currently documents asynchronous large-volume processing at 50% of standard cost with target 24-hour turnaround, using inline requests for smaller batches or JSONL/file input for larger batches.

Implementation must verify current provider docs and model support before enabling any provider in production.

Reference links:

- OpenAI Batch API: https://platform.openai.com/docs/guides/batch/
- OpenAI Batch reference: https://platform.openai.com/docs/api-reference/batch
- OpenAI cost optimization: https://platform.openai.com/docs/guides/cost-optimization
- Anthropic Message Batches: https://docs.anthropic.com/en/api/creating-message-batches
- Anthropic prompt caching: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
- Gemini Batch API: https://ai.google.dev/gemini-api/docs/batch-mode

## Task Categories

| Category | Mode in v1 | Model tier | Writes stored output | Sync eligibility later |
| --- | --- | --- | --- | --- |
| `doc_extraction` | Batch | cheap | Yes | No |
| `history_extraction` | Batch | cheap | Yes | No |
| `transcript_analysis` | Batch | premium | Yes | Urgent single-company rerun |
| `narrative_synthesis` | Batch | premium or mid-tier | Yes | Analyst-approved report |
| `tag_suggestion` | Batch | cheap | Pending suggestions | Rare |
| `alert_summary` | Batch | cheap/mid-tier | Alert record | Urgent portfolio event |
| `sql_generation` | Batch ticket in strict v1 | cheap/mid-tier | Query audit only | Yes |
| `prompt_smoke_test` | Manual sync | configured | No production write | Yes |

## LLM Job Record

Every LLM request should be represented before any provider call.

Core fields:

- `llm_job_id`
- task category
- execution mode
- provider
- model
- endpoint
- prompt package hash
- schema version
- parser version
- source artifact hashes
- company/profile/KPI context hashes
- idempotency key
- estimated input tokens
- estimated output tokens
- reserved cost
- actual usage
- status
- retry count
- raw response path
- validation error

## Provider Adapter Contract

Provider-specific code should live behind a small interface.

Adapter capabilities:

- `render_request`
- `generate_structured`
- `submit_batch`
- `poll_batch`
- `fetch_batch_results`
- `cancel_batch`
- `parse_usage`
- `classify_error`
- `supports_batch`
- `supports_prompt_cache`
- `supports_native_schema`
- `max_context_tokens`
- `pricing_lookup`

OpenRouter-routed models and direct provider APIs may not expose the same batch or cache features. The provider contract must capture that explicitly.

## Batch Request Design

Batch records must be durable before submission.

Use stable custom IDs:

```text
<task_category>:<company_id>:<period_key>:<source_hash>:<prompt_hash>:<schema_version>:<model_slug>
```

Rules:

- Group batches by provider, endpoint, model, and compatible request shape.
- Do not rely on output order; map results by `custom_id`.
- Store provider batch ID immediately after submission.
- Store input manifest path, output path, error path, and request count.
- Keep raw provider output until normalized output and usage are reconciled.
- Partial batch failure creates retry jobs only for failed or expired request IDs.

## Prompt Package Versioning

Hashing only the system prompt is insufficient.

Prompt package hash includes:

- system prompt
- task instructions
- schema definition
- schema descriptions
- renderer code version
- context assembly version
- KPI block version
- model parameters
- output parser version
- validation rules version

Any change can mark previous outputs stale for the affected task category.

## Evidence Validation

LLM output is not accepted only because it is valid JSON.

Validation gates:

- required schema fields present
- source quote exists in source text or table text
- extracted numbers are present in or directly supported by evidence
- KPI unit is parseable
- period/basis is known
- no claim is promoted without evidence
- context-derived flags are labeled separately from transcript-backed claims
- `not_disclosed` is a status, not a value string

Failed validation can trigger:

- repair with same model
- stricter retry
- escalation to better model
- analyst review
- permanent failure

## Historical Context Safety

Cheap-model historical context influences premium transcript analysis. Treat it as untrusted until validated.

`concall_context` must include:

- metrics with evidence
- guidance with evidence
- capex statements with evidence
- concerns with evidence
- confidence
- validation status

Low-confidence, guidance-heavy, or portfolio-material historical calls can be selectively escalated.

## Cost Ledger

Every job reserves cost before submission and reconciles after completion.

Track:

- estimated input tokens
- estimated output tokens
- actual input tokens
- actual output tokens
- cached input tokens where available
- cache creation/read tokens where available
- batch discount flag
- retry cost
- repair cost
- failed/expired request cost
- provider invoice reconciliation status

Caps:

- daily total
- monthly total
- per run
- per task category
- per user-triggered action
- portfolio backfill cap

## Sync Escape Hatch

Sync execution requires:

- category in `allowed_sync_categories`
- user identity
- reason
- estimated cost shown before execution
- cost cap check
- audit log
- same validation pipeline as batch

Recommended future sync categories:

- `urgent_single_company_rerun`
- `sql_generation`
- `failed_batch_repair`
- `prompt_smoke_test`
- `urgent_alert_triage`

Do not add a generic "run sync" button.

## Rate Limits And Retries

Use provider-aware retry logic:

- request/token buckets per provider/model
- retry-after header handling
- jittered exponential backoff
- retryable vs permanent error classification
- circuit breaker after repeated provider failures
- dead-letter state after max attempts
- batch expiration handling

Simple sleep delays are not enough once multiple providers and batch states exist.

## AI Evaluation Metrics

Maintain a labeled eval set for transcripts and documents.

Metrics:

- schema-valid rate
- quote precision
- numeric accuracy
- guidance recall
- KPI recall
- hallucination rate
- not-disclosed accuracy
- context misuse rate
- repair success rate
- batch failure/expiry rate
- estimated vs actual cost error

Promotion gate: a prompt or model change cannot become default unless it passes the eval threshold for affected task categories.
