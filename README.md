# Concall Result Automation

An automated pipeline to download, extract, and analyze earnings call transcripts for Indian listed companies using Google Gemini AI. Includes a Streamlit dashboard for interactive exploration of results.

---

## Features

- **Automated download** of earnings transcripts from Screener.in (sourced from BSE filings)
- **PDF to text extraction** using PyMuPDF
- **AI-powered analysis** using Google Gemini — extracts 9 structured sections per transcript (financial guidance, growth drivers, red flags, analyst take, and more)
- **Multi-model support** — run different Gemini models on the same transcript and compare outputs side-by-side
- **Incremental / idempotent** — re-running skips already-processed files; no duplicate API calls
- **Streamlit dashboard** — filter by sector, sub-sector, company, quarter, and model; auto-adapts view for multi-quarter or multi-company comparisons

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

### Analyze all historical quarters (not just latest)

By default, only the **latest quarter** per company is analyzed. Use `--all-quarters` to process everything:

```bash
python main.py --all-quarters
```

### Use a different Gemini model

```bash
python main.py --model gemini-2.0-flash
```

This creates a separate `analysis_gemini-2.0-flash.json` alongside any existing model outputs — perfect for comparing model quality.

### CLI reference

| Flag | Default | Description |
|---|---|---|
| `--tickers` | all from `tickers.csv` | Comma-separated tickers to process |
| `--phase` | `all` | `download`, `extract`, `analyze`, or `all` |
| `--all-quarters` | off | Analyze all quarters, not just latest |
| `--model` | `GEMINI_MODEL` env var | Gemini model name to use |
| `--concurrency-delay` | `2.0` | Seconds between Gemini API calls |

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
- **Sector** → **Sub-Sector** → **Company** → **Quarter** → **Model**

### View modes (auto-detected from selection)

| Selection | View |
|---|---|
| 1 company + 1 quarter + multiple models | **Model comparison** — side-by-side columns per model |
| 1 company + multiple quarters | **Quarter comparison** — side-by-side columns per quarter |
| Multiple companies + 1 quarter | **Company comparison** — one expander per company |
| Everything else | **Flat list** — one expander per company + quarter + model |

Click **🔄 Refresh Data** in the sidebar to pick up new analysis files without restarting.

---

## Scaling

The pipeline is designed to scale from 2 to 2000 companies:

- **Tickers** are driven entirely by `tickers.csv` — add rows to scale up
- **Idempotency** — every phase skips already-processed files; safe to re-run at any time (e.g. as a nightly cron job)
- **Rate limiting** — `--concurrency-delay` controls the pause between Gemini calls; increase for free tier, decrease for paid
- **Multi-model storage** — each model's output is a separate file; the Streamlit app merges them automatically
- **Latest-only default** — by default only the newest transcript per company is analyzed, keeping API usage minimal

---

## License

MIT
