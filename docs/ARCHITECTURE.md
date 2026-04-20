# Concall Result Automation Architecture

This project is a three-stage pipeline for earnings call transcripts:

1. Download transcript PDFs from Screener.in.
2. Extract text from each PDF.
3. Analyze each transcript with an LLM and save structured JSON.

The Streamlit app reads the saved JSON files. It does not call the LLM.

## Data Flow

```text
tickers.csv
    |
    v
transcript_downloader.py
    |
    v
Outputs/Concalls/<TICKER>/<Mon YYYY>/Transcript.pdf
    |
    v
transcript_extraction.py
    |
    v
Outputs/Concalls/<TICKER>/<Mon YYYY>/Transcript.txt
    |
    v
analyzer.py
    |
    v
Outputs/Concalls/<TICKER>/<Mon YYYY>/analysis_<model-slug>.json
    |
    v
app.py
```

## Module Responsibilities

`main.py` is the CLI orchestrator. It loads `config.yaml`, applies CLI overrides, resolves the ticker universe, and runs download, extraction, analysis, or watch mode.

`transcript_downloader.py` scrapes Screener.in concall pages, finds transcript links, and downloads `Transcript.pdf` into a deterministic ticker/period folder.

`transcript_extraction.py` converts `Transcript.pdf` files into `Transcript.txt` files using PyMuPDF. It skips already extracted files.

`analyzer.py` owns the LLM prompt, Pydantic output schema, provider routing, JSON repair, validation, idempotent writes, and batch analysis concurrency.

`period_utils.py` centralizes period parsing and recent-period selection so downloader, extractor, and analyzer use the same ordering rules.

`app.py` is a read-only Streamlit viewer for completed analysis files. It groups calendar months into Indian fiscal quarters:

| Months | Quarter |
|---|---|
| Apr, May, Jun | Q4 |
| Jul, Aug, Sep | Q1 |
| Oct, Nov, Dec | Q2 |
| Jan, Feb, Mar | Q3 |

## Idempotency

Each stage skips work that already exists on disk:

- Download skips an existing `Transcript.pdf`.
- Extraction skips an existing `Transcript.txt`.
- Analysis skips an existing `analysis_<model-slug>.json`.

For compatible model upgrades, `model_output_aliases` in `config.yaml` can make a newer model reuse the output filename of an older model.

## Configuration

`config.yaml` is the default source of runtime settings. CLI flags in `main.py` override YAML values for one run.

Important fields:

- `tickers`: Empty means all rows from `tickers.csv`.
- `models`: Empty means `GEMINI_MODEL` from `.env`, falling back to `DEFAULT_MODEL`.
- `phase`: One of `download`, `extract`, `analyze`, or `all`.
- `all_quarters`: When true, process every available period.
- `recent_quarters`: Used only when `all_quarters` is false.
- `watch`: Continuously poll for new transcripts.
- `api_delay`: Delay used to stagger LLM calls.

## Environment Variables

Gemini models require:

```env
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash
```

OpenRouter models use `provider/model` names and require:

```env
OPENROUTER_API_KEY=...
```

## Operational Notes

The analyzer validates every LLM response against `TranscriptAnalysis`. If parsing fails, it tries `json-repair`; if repair also fails, the raw response is written next to the transcript as `debug_<model-slug>_raw.txt`.

Batch analysis uses a thread pool. Reduce `max_workers` in code or increase `api_delay` in config if provider rate limits become frequent.
