# Concall Result Automation

An automated pipeline to download, extract, and analyze earnings call transcripts for Indian listed companies using Gemini or OpenRouter-hosted LLMs. Includes a Streamlit dashboard for interactive exploration of saved results.

For a module-by-module overview, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Current Behavior

- Pipeline stages are idempotent: existing PDFs, extracted text files, and analysis JSON files are skipped.
- `config.yaml` is the default runtime configuration; CLI flags override it for one run.
- Gemini models use `GEMINI_API_KEY`; OpenRouter models use `OPENROUTER_API_KEY` and `provider/model` names.
- The dashboard is read-only. It loads saved analysis JSON files and does not call the LLM.
- The dashboard groups calendar months into fiscal quarters: Apr-Jun = Q4, Jul-Sep = Q1, Oct-Dec = Q2, Jan-Mar = Q3.
- The dashboard no longer exposes model filters or model-comparison views; if several analysis files exist for a period, the newest valid JSON is displayed.

---

## Features

- **Automated download** of earnings transcripts from Screener.in (sourced from BSE filings)
- **PDF to text extraction** using PyMuPDF
- **AI-powered analysis** using Gemini or OpenRouter-hosted models - extracts 9 structured sections per transcript (financial guidance, growth drivers, red flags, analyst take, and more)
- **Multi-model support** - run one or more configured models on the same transcript; outputs are stored separately on disk
- **Incremental / idempotent** — re-running skips already-processed files; no duplicate API calls
- **Streamlit dashboard** - filter by date range, company, and fiscal quarter; auto-adapts view for multi-quarter or multi-company comparisons

---

## Project Structure

```
project_root/
├── main.py                   # Orchestrator — runs the full pipeline via CLI
├── analyzer.py               # Gemini LLM extraction module
├── transcript_downloader.py  # Scrapes & downloads transcript PDFs from Screener.in
├── transcript_extraction.py  # Batch PDF → TXT extraction
├── app.py                    # Streamlit viewer
├── tickers.csv               # Ticker universe with sector metadata
├── requirements.txt          # Python dependencies
├── .env                      # API keys (not committed)
├── .gitignore
└── Outputs/
    └── Concalls/
        └── <TICKER>/
            └── <Mon YYYY>/   # e.g. "Feb 2026"
                ├── Transcript.pdf
                ├── Transcript.txt
                └── analysis_<model>.json   # e.g. analysis_gemini-2.5-flash.json
```

---

## Setup

### 1. Clone & install dependencies

```bash
git clone https://github.com/<your-username>/concall-result-automation.git
cd concall-result-automation

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure API key

Create a `.env` file in the project root:

```env
GEMINI_API_KEY=your_google_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
```

Get your free API key at [Google AI Studio](https://aistudio.google.com/app/apikey).

**Free tier limits** (as of March 2026):
| Model | Requests/min | Requests/day |
|---|---|---|
| `gemini-2.5-flash` | 10 | 500 |
| `gemini-2.0-flash` | 15 | 1,500 |

### 3. Configure tickers

Edit `tickers.csv` to add the companies you want to track:

```csv
ticker,company_name,sector,sub_sector
CEINSYS,Ceinsys Tech Limited,Technology,GIS & Engineering
SALZERELEC,Salzer Electronics Limited,Electronics,Electrical Components
TCS,Tata Consultancy Services,Technology,IT Services
```

The `ticker` column must match the NSE/BSE symbol used on [Screener.in](https://www.screener.in).

---

## Usage

All phases are run through `main.py`.

### Run the full pipeline (download → extract → analyze)

```bash
python main.py
```

### Run for specific tickers only

```bash
python main.py --tickers CEINSYS,SALZERELEC
```

### Run a specific phase only

```bash
python main.py --phase download    # Download new PDFs only
python main.py --phase extract     # Convert PDFs to TXT only
python main.py --phase analyze     # Run Gemini analysis only
```

### Analyze all historical periods

By default, the number of recent concalls comes from `recent_quarters` in `config.yaml`. Use `--all-quarters` to process everything:

```bash
python main.py --all-quarters
```

### Use different models

```bash
python main.py --models gemini-2.0-flash,google/gemini-2.5-flash
```

Each model creates a separate `analysis_<model>.json` file unless `model_output_aliases` maps it to an existing output name.

### CLI reference

| Flag | Default | Description |
|---|---|---|
| `--tickers` | all from `tickers.csv` | Comma-separated tickers to process |
| `--phase` | `all` | `download`, `extract`, `analyze`, or `all` |
| `--all-quarters` | off | Analyze all quarters, not just latest |
| `--recent-quarters` | config value | Number of most recent concalls per ticker when `--all-quarters` is not used |
| `--models` | config or `GEMINI_MODEL` | Comma-separated model names |
| `--watch` | off | Poll continuously for new transcripts |
| `--poll-interval` | config value | Seconds between watch-mode polls |
| `--concurrency-delay` | config value | Seconds used to stagger LLM calls |

---

## Analysis Output

Each transcript produces an `analysis_<model>.json` file with 9 structured sections:

| Section | Description |
|---|---|
| `financial_guidance` | Explicit revenue / EBITDA / PAT guidance with exact quotes |
| `growth_drivers` | Explicitly mentioned growth drivers with supporting quotes |
| `capacity_capex` | Current capacity, utilization %, and expansion plans |
| `margins_commentary` | Exact management statements on margins |
| `order_book_demand` | Order book size, pipeline, and demand commentary |
| `red_flags` | Rising receivables, debt, working capital stress — with quotes |
| `quarter_change` | Explicit comparisons vs previous quarter |
| `key_quotes` | 5–10 most important verbatim statements |
| `analyst_take` | Bull case / Bear case / Monitorables (from facts only) |

The LLM is instructed to use **only** information explicitly stated in the transcript — no inference, no external knowledge, every claim backed by a direct quote.

---

## Streamlit Dashboard

```bash
streamlit run app.py
```

### Sidebar filters
- **Date range** -> **Company** -> **Quarter**

The date range matches companies that have at least one concall month
overlapping the selected range. Once a company matches, all available quarters
for that company remain visible.

Quarter labels use the dashboard fiscal mapping: Apr-Jun = Q4, Jul-Sep = Q1,
Oct-Dec = Q2, and Jan-Mar = Q3.

### View modes (auto-detected from selection)

| Selection | View |
|---|---|
| 1 company + multiple quarters | **Quarter comparison** — side-by-side columns per quarter |
| Multiple companies + 1 quarter | **Company comparison** — one expander per company |
| Everything else | **Flat list** — one expander per company + quarter |

Click **🔄 Refresh Data** in the sidebar to pick up new analysis files without restarting.

---

## Scaling

The pipeline is designed to scale from 2 to 2000 companies:

- **Tickers** are driven entirely by `tickers.csv` — add rows to scale up
- **Idempotency** — every phase skips already-processed files; safe to re-run at any time (e.g. as a nightly cron job)
- **Rate limiting** — `--concurrency-delay` controls request staggering; increase it if providers return rate-limit errors
- **Multi-model storage** — each model's output is a separate file; the Streamlit app displays the newest valid result for each period
- **Recent-period default** — by default the configured `recent_quarters` limits API usage

---

## License

MIT
