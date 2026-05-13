# Investment Intelligence Plan

## Purpose

The product should answer an investor's core question after every result cycle: what changed, why it matters, and what evidence supports it. The system should produce source-backed research primitives that can be queried, compared, and rolled up into analyst notes.

## First-Class Financial Sources

Do not rely on transcripts alone.

Required source hierarchy:

1. Quarterly result filings for reported financials.
2. Concall transcript for management commentary and Q&A.
3. Concall PPT for slide-level segment and guidance data.
4. Annual report for durable business structure, capacity, risks, and strategy.
5. Investor presentations for updated strategy, capex, segment mix, and medium-term goals.
6. Press releases and exchange filings for event updates.

Quarterly results should produce `results_facts` covering:

- revenue
- EBITDA, EBIT, PAT, EPS
- gross margin and EBITDA margin when available
- segment revenue and margin
- debt, cash, working capital, receivables, inventory
- capex
- exceptional items
- one-offs and accounting changes
- standalone vs consolidated basis

These facts become the baseline against which transcript commentary is evaluated.

## Analyst-Grade Outputs

Each latest transcript analysis should support these outputs:

- company call note
- what changed since last quarter
- thesis delta: improved, weakened, unchanged, unclear
- KPI table with prior quarter and year-over-year comparisons
- management guidance tracker
- risk flags with severity and evidence
- segment performance summary
- margin bridge and cost commentary
- demand/order book/channel inventory commentary
- capex and capacity progress
- balance sheet and working capital flags
- management credibility update
- questions to monitor before the next call

Cross-company outputs:

- strict-quarter sub-sector report
- KPI heatmap by sub-sector
- guidance revision board
- risk dashboard
- management credibility leaderboard
- peer outlier detection
- missing-company coverage list
- portfolio/watchlist morning brief

## Evidence Policy

Every investment claim must be traceable.

Required evidence:

- source document
- page, slide, section, line, or transcript span when available
- speaker for transcript evidence
- quote or table excerpt
- extraction model and prompt package version
- confidence
- validation status

No evidence means no promoted claim. Low-confidence or high-materiality outputs go to analyst review.

## Typed KPI Dictionary

`kpis.yaml` should become a sector data dictionary, not only prompt text.

Each KPI definition should include:

- stable `kpi_name`
- display label
- aliases and common phrasing
- unit
- formula or extraction instruction
- normalized unit
- higher/lower/context-dependent polarity
- valid range
- source priority
- required/optional status
- comparability caveats
- sector notes

Example banking KPIs:

- NIM
- CASA ratio
- loan growth
- deposit growth
- LDR
- GNPA
- NNPA
- slippages
- credit cost
- PCR
- SMA book
- restructured book
- yield on advances
- cost of funds

Example capital goods KPIs:

- order inflow
- order book
- book-to-bill
- execution run rate
- margin
- working capital days
- receivables
- customer concentration
- export mix
- capacity utilization

## KPI Extraction Record

Store KPIs as rows, not display text.

Fields:

- company
- fiscal quarter
- source period
- sub-sector
- `kpi_name`
- segment
- raw value
- normalized value
- unit
- basis: standalone, consolidated, segment, adjusted, reported
- YoY change
- QoQ change
- source document
- source location
- quote
- confidence
- extraction status
- not-disclosed reason

## Guidance Tracking

Guidance is not only a value. It has a lifecycle.

Track:

- metric
- guided value/range
- midpoint when calculable
- target period
- hard vs soft guidance
- conditions or dependencies
- speaker
- source quote
- status: new, reiterated, raised, lowered, withdrawn, met, missed, ambiguous
- later actual
- actual source
- analyst review status

Qualitative guidance should also be tracked:

- on track
- delayed
- contradicted
- unclear
- no update

## Risk Flag Taxonomy

Risk flags should be typed and comparable.

Common fields:

- risk type
- severity: low, medium, high, critical
- direction: improving, worsening, stable, new
- repeat count
- affected segment
- time horizon
- evidence
- portfolio materiality
- review status

Sector examples:

- lenders: asset quality, deposit pressure, NIM compression, credit cost, restructuring
- pharma: FDA/regulatory, pricing pressure, plant remediation, product concentration
- IT: deal delays, discretionary spending, attrition, pricing, client concentration
- consumer: channel inventory, rural demand, premiumization, raw materials, ad spend
- capital goods: order quality, execution delay, working capital, receivables, margin leakage
- cyclicals: leverage, commodity sensitivity, utilization, spread compression

## Portfolio And Watchlist Workflow

Add portfolio/watchlist tables so batch priority reflects investment relevance.

Suggested fields:

- ticker
- list type: holding, watchlist, idea, avoid
- weight or priority
- owner
- thesis
- key triggers
- stop-watch conditions
- alert preferences
- materiality threshold

Batch priority:

1. Holdings.
2. Active watchlist.
3. Current result-season coverage universe.
4. Historical backfill.
5. Low-priority document enrichment.

Morning brief sort order:

1. portfolio materiality
2. new high-severity risk
3. guidance miss or downgrade
4. major KPI outlier
5. thesis delta
6. missing evidence or needs-review item

## Comparability Rules

Peer tables must not silently mix non-comparable numbers.

Normalize:

- INR crore, lakh, million, billion
- percentage vs basis points
- standalone vs consolidated
- adjusted vs reported
- current quarter vs trailing twelve months
- YoY and QoQ basis
- segment renames and restatements
- call date vs result period

Missing values should be explicit:

- not disclosed
- not applicable
- source missing
- extraction failed
- needs review

## Review Queue

Items requiring analyst review:

- high impact and low confidence
- conflicting facts across transcript/PPT/results
- guidance miss classification
- outlier normalized KPI value
- source quote not found
- unit mismatch
- stale quarter in peer comparison
- model output without evidence

Reviewed items should record user, timestamp, decision, and note.
