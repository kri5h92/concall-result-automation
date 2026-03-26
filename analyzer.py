import os
import json
import glob
import time
import asyncio
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()  # Load .env file before API key is read

from google import genai
from pydantic import BaseModel, Field


# -----------------------------------
# PYDANTIC SCHEMA
# -----------------------------------

class TranscriptAnalysis(BaseModel):
    """Schema for structured earnings transcript analysis."""

    company_name: str = Field(description="Full company name as stated in the transcript")
    ticker: str = Field(description="NSE/BSE ticker symbol")
    quarter: str = Field(description="Financial quarter (e.g. Q3 FY26)")
    period: str = Field(description="Calendar period of the call (e.g. Feb 2026)")

    financial_guidance: str = Field(
        description="Explicit revenue/EBITDA/PAT guidance with exact quotes. 'Not disclosed' if absent."
    )
    growth_drivers: str = Field(
        description="Explicitly mentioned growth drivers with supporting quotes."
    )
    capacity_capex: str = Field(
        description="Current capacity, utilization, expansion plans with quotes. 'Not disclosed' per missing item."
    )
    margins_commentary: str = Field(
        description="Exact management statements on margins. No interpretation."
    )
    order_book_demand: str = Field(
        description="Order book and demand details if explicitly discussed, with quotes. 'Not disclosed' if absent."
    )
    red_flags: str = Field(
        description="Red flags (rising receivables, debt, working capital stress) with quotes. 'Not disclosed' if absent."
    )
    quarter_change: str = Field(
        description="Explicit management comparisons vs previous quarter. 'Not disclosed' if absent."
    )
    key_quotes: list[str] = Field(
        description="5-10 most important verbatim statements from the transcript."
    )
    analyst_take: str = Field(
        description="Bull case, Bear case, and Monitorables derived ONLY from extracted facts above."
    )


# -----------------------------------
# SYSTEM PROMPT
# -----------------------------------

SYSTEM_PROMPT = """You are an equity research analyst.

Your task is to extract ONLY factual, verifiable information from the provided earnings call transcript.

STRICT RULES (MANDATORY):

1. Use ONLY information explicitly stated in the transcript.
2. Do NOT infer, assume, estimate, or add external knowledge.
3. Every key point MUST be supported by a direct quote from the transcript.
4. If any information is not clearly mentioned, write: "Not disclosed".
5. Do NOT generalize vague statements into concrete numbers.
6. Avoid paraphrasing critical financial guidance — use exact wording wherever possible.
7. If management language is ambiguous, highlight it as "Ambiguous commentary".

Your goal is NOT to summarize, but to extract decision-useful facts for a portfolio manager.

---

OUTPUT FORMAT:

1. Financial Guidance:
* Extract ONLY explicit guidance (Revenue / EBITDA / PAT)
* Provide exact quote for each point
* If no guidance → "Not disclosed"

2. Growth Drivers:
* List only explicitly mentioned drivers
* Quote supporting lines

3. Capacity & Capex:
* Current capacity (with quote)
* Utilization (with quote)
* Expansion plans (with quote)
* If missing → "Not disclosed"

4. Margins Commentary:
* Extract exact management statements
* No interpretation

5. Order Book / Demand:
* Only if explicitly discussed
* Include quotes

6. Red Flags:
* Only if explicitly hinted or stated
* Examples: Rising receivables, Working capital stress, Debt increase
* Each point MUST include quote

7. Change vs Previous Quarter:
* Only if management explicitly compares
* Otherwise → "Not disclosed"

8. Key Quotes:
* List the most important 5–10 verbatim statements

9. Analyst Take (STRICT MODE):
* This section must be derived ONLY from extracted facts above
* No new information allowed
* Clearly separate: Bull case (based on facts), Bear case (based on facts), Monitorables

---

FINAL CHECK BEFORE ANSWERING:
* Ensure every insight is traceable to a quote
* Remove any statement that is not explicitly supported
* If unsure → delete it"""


# -----------------------------------
# ANALYZER
# -----------------------------------

DEFAULT_MODEL = "gemini-2.5-flash"


def _model_to_slug(model_name: str) -> str:
    """Convert a model name to a safe filename slug (e.g. 'gemini-2.5-flash')."""
    import re
    return re.sub(r'[<>:"/\\|?*\s]', '-', model_name).strip('-')


def _get_client() -> genai.Client:
    """Initialize the GenAI client. Requires GEMINI_API_KEY env var."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GEMINI_API_KEY environment variable is not set. "
            "Set it with: set GEMINI_API_KEY=your_key_here"
        )
    return genai.Client(api_key=api_key)


def analyze_transcript(
    txt_path: str,
    ticker: str,
    company_name: str,
    model_name: str = None,
    client: genai.Client = None,
) -> dict | None:
    """
    Analyze a single transcript text file using Gemini.
    Returns the parsed analysis dict, or None on failure.
    Saves analysis.json alongside the transcript.
    """
    if model_name is None:
        model_name = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)

    folder = os.path.dirname(txt_path)
    slug = _model_to_slug(model_name)
    json_path = os.path.join(folder, f"analysis_{slug}.json")

    # Idempotency: skip if already analyzed with this model
    if os.path.exists(json_path):
        print(f"  Already analyzed: {json_path}")
        return _load_existing(json_path)

    # Read transcript text
    with open(txt_path, "r", encoding="utf-8") as f:
        transcript_text = f.read()

    if not transcript_text.strip():
        print(f"  Empty transcript: {txt_path}")
        return None

    if client is None:
        client = _get_client()

    # Extract the period from the folder name (e.g. "Feb 2026")
    period = os.path.basename(folder)

    user_prompt = (
        f"Ticker: {ticker}\n"
        f"Company: {company_name}\n"
        f"Period: {period}\n\n"
        f"--- TRANSCRIPT START ---\n\n"
        f"{transcript_text}\n\n"
        f"--- TRANSCRIPT END ---"
    )

    # Retry with exponential backoff for rate limits
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=user_prompt,
                config=genai.types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=TranscriptAnalysis,
                    temperature=0.1,
                ),
            )

            # Parse the JSON response
            result_dict = json.loads(response.text)

            # Validate with Pydantic
            validated = TranscriptAnalysis(**result_dict)
            result_dict = validated.model_dump()

            # Save to disk (filename encodes the model used)
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(result_dict, f, indent=2, ensure_ascii=False)

            print(f"  Analyzed: {ticker} / {period} [{model_name}] -> {json_path}")
            return result_dict

        except Exception as e:
            error_str = str(e).lower()
            is_rate_limit = any(
                kw in error_str
                for kw in ["429", "rate", "quota", "resource_exhausted"]
            )

            if is_rate_limit and attempt < max_retries - 1:
                wait = (2 ** attempt) * 5  # 5s, 10s, 20s
                print(f"  Rate limited on {ticker}/{period}. Retrying in {wait}s... (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
                continue
            else:
                print(f"  ERROR analyzing {ticker}/{period}: {e}")
                return None


def _load_existing(json_path: str) -> dict | None:
    """Load an existing analysis.json file."""
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def analyze_batch(
    output_root: str = None,
    tickers: list[str] = None,
    ticker_info: dict[str, str] = None,
    latest_only: bool = True,
    model_name: str = None,
    delay: float = 2.0,
) -> dict:
    """
    Batch-analyze transcripts. Synchronous with a delay between calls for rate-limit safety.

    Args:
        output_root: Root path to Outputs/Concalls/
        tickers: List of ticker symbols to process. None = all.
        ticker_info: Dict mapping ticker -> company_name. Required for new analyses.
        latest_only: If True, only analyze the latest quarter per ticker.
        model_name: Gemini model to use.
        delay: Seconds to wait between API calls.

    Returns:
        Dict with counts: {'analyzed': N, 'skipped': N, 'failed': N}
    """
    if output_root is None:
        output_root = os.path.join(os.getcwd(), "Outputs", "Concalls")
    if ticker_info is None:
        ticker_info = {}

    stats = {"analyzed": 0, "skipped": 0, "failed": 0}
    client = _get_client()

    # Discover all txt files to process
    txt_files = _discover_txt_files(output_root, tickers, latest_only)

    if not txt_files:
        print("No transcript text files found to analyze.")
        return stats

    print(f"\nAnalyzing {len(txt_files)} transcript(s)...\n")

    # Resolve model name once for the whole batch (used for idempotency check)
    resolved_model = model_name or os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
    resolved_slug = _model_to_slug(resolved_model)

    for i, (ticker, period, txt_path) in enumerate(txt_files):
        json_path = os.path.join(os.path.dirname(txt_path), f"analysis_{resolved_slug}.json")

        if os.path.exists(json_path):
            stats["skipped"] += 1
            print(f"  [{i+1}/{len(txt_files)}] Skipped (already analyzed by {resolved_model}): {ticker}/{period}")
            continue

        company_name = ticker_info.get(ticker, ticker)

        result = analyze_transcript(
            txt_path=txt_path,
            ticker=ticker,
            company_name=company_name,
            model_name=model_name,
            client=client,
        )

        if result is not None:
            stats["analyzed"] += 1
        else:
            stats["failed"] += 1

        # Rate-limit delay between API calls (skip after last file)
        if i < len(txt_files) - 1:
            time.sleep(delay)

    return stats


def _discover_txt_files(
    output_root: str,
    tickers: list[str] = None,
    latest_only: bool = True,
) -> list[tuple[str, str, str]]:
    """
    Find Transcript.txt files to analyze.
    Returns list of (ticker, period, txt_path) tuples.
    """
    results = []

    if tickers:
        ticker_dirs = []
        for t in tickers:
            d = os.path.join(output_root, t)
            if os.path.isdir(d):
                ticker_dirs.append((t, d))
    else:
        ticker_dirs = []
        if os.path.isdir(output_root):
            for name in os.listdir(output_root):
                d = os.path.join(output_root, name)
                if os.path.isdir(d):
                    ticker_dirs.append((name, d))

    for ticker, ticker_dir in ticker_dirs:
        period_folders = []
        for name in os.listdir(ticker_dir):
            period_path = os.path.join(ticker_dir, name)
            txt_path = os.path.join(period_path, "Transcript.txt")
            if os.path.isdir(period_path) and os.path.exists(txt_path):
                period_folders.append((name, txt_path))

        if not period_folders:
            continue

        if latest_only:
            # Sort by date — folder names like "Feb 2026", "Nov 2025"
            period_folders.sort(key=lambda x: _parse_period_date(x[0]), reverse=True)
            period, txt_path = period_folders[0]
            results.append((ticker, period, txt_path))
        else:
            for period, txt_path in period_folders:
                results.append((ticker, period, txt_path))

    return results


def _parse_period_date(period_str: str) -> datetime:
    """Parse folder name like 'Feb 2026' into a datetime for sorting."""
    try:
        return datetime.strptime(period_str, "%b %Y")
    except ValueError:
        # Fallback: return epoch so unparseable folders sort to the end
        return datetime(1970, 1, 1)


# -----------------------------------
# STANDALONE EXECUTION
# -----------------------------------

if __name__ == "__main__":
    import csv

    # Load ticker info from CSV
    csv_path = os.path.join(os.getcwd(), "tickers.csv")
    ticker_info = {}
    if os.path.exists(csv_path):
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ticker_info[row["ticker"].strip()] = row["company_name"].strip()

    stats = analyze_batch(ticker_info=ticker_info, latest_only=True)
    print(f"\nAnalysis complete: {stats}")
