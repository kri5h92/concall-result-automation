import os
import json
import glob
import time
import asyncio
import logging

logger = logging.getLogger(__name__)


LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(level: int = logging.INFO, log_dir: str = None) -> None:
    """Configure console + rotating file logging.

    Args:
        level: Logging level (default INFO).
        log_dir: Directory for log files. Defaults to <cwd>/logs/.
    """
    from logging.handlers import RotatingFileHandler

    if log_dir is None:
        log_dir = os.path.join(os.getcwd(), "logs")
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, "pipeline.log")

    root = logging.getLogger()
    if root.handlers:
        # Already configured (e.g. Streamlit), just add file handler if missing
        has_file = any(isinstance(h, logging.FileHandler) for h in root.handlers)
        if not has_file:
            _add_file_handler(root, log_file, level)
        root.setLevel(min(root.level, level))
        return

    root.setLevel(logging.DEBUG)  # capture everything at root; handlers filter per level

    # Console handler — INFO and above only
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
    root.addHandler(console)

    # Rotating file handler — DEBUG and above (captures all request/response logs)
    _add_file_handler(root, log_file, logging.DEBUG)

    logger.debug("Logging to file: %s", log_file)


def _add_file_handler(root: logging.Logger, log_file: str, level: int) -> None:
    from logging.handlers import RotatingFileHandler
    fh = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
    root.addHandler(fh)

from dotenv import load_dotenv
load_dotenv()  # Load .env file before API key is read

from period_utils import select_recent_period_items

try:
    from google import genai as _genai
except ImportError:
    _genai = None

from pydantic import BaseModel, Field


# -----------------------------------
# PYDANTIC SCHEMA
# -----------------------------------

class AnalystTake(BaseModel):
    bull_case: str = Field(description="Bull case derived ONLY from extracted facts.")
    bear_case: str = Field(description="Bear case derived ONLY from extracted facts.")
    monitorables: str = Field(description="Key things to monitor going forward.")


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
    analyst_take: AnalystTake = Field(
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

DEFAULT_MODEL = "google/gemini-2.5-flash"  # cheap + reasoning, OpenRouter format (provider/model)


def _detect_provider(model_name: str) -> str:
    """Detect LLM provider from model name. 'provider/model' format → openrouter."""
    return "openrouter" if "/" in model_name else "gemini"


def _model_to_slug(model_name: str) -> str:
    """Convert a model name to a safe filename slug (e.g. 'gemini-2.5-flash')."""
    import re
    return re.sub(r'[<>:"/\\|?*\s]', '-', model_name).strip('-')


def _get_gemini_client():
    """Initialize the Gemini GenAI client. Requires GEMINI_API_KEY env var."""
    if _genai is None:
        raise ImportError(
            "google-genai package is not installed. Run: pip install google-genai"
        )
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GEMINI_API_KEY environment variable is not set. "
            "Set it with: set GEMINI_API_KEY=your_key_here"
        )
    return _genai.Client(api_key=api_key)


def _get_openrouter_client():
    """Initialize the OpenRouter client. Requires OPENROUTER_API_KEY env var."""
    from openai import OpenAI
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENROUTER_API_KEY environment variable is not set. "
            "Set it with: set OPENROUTER_API_KEY=your_key_here"
        )
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )


def _get_client(model_name: str = None):
    """Return the appropriate LLM client based on the model name."""
    if model_name is None:
        model_name = DEFAULT_MODEL
    if _detect_provider(model_name) == "openrouter":
        return _get_openrouter_client()
    return _get_gemini_client()


def analyze_transcript(
    txt_path: str,
    ticker: str,
    company_name: str,
    model_name: str = None,
    client=None,
) -> dict | None:
    """
    Analyze a single transcript text file using the configured LLM provider.
    Returns the parsed analysis dict, or None on failure.
    Saves analysis_{model_slug}.json alongside the transcript.
    """
    if model_name is None:
        model_name = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)

    provider = _detect_provider(model_name)
    folder = os.path.dirname(txt_path)
    slug = _model_to_slug(model_name)
    json_path = os.path.join(folder, f"analysis_{slug}.json")

    # Idempotency: skip if already analyzed with this model
    if os.path.exists(json_path):
        logger.debug("Already analyzed, skipping: %s", json_path)
        return _load_existing(json_path)

    # Read transcript text
    with open(txt_path, "r", encoding="utf-8") as f:
        transcript_text = f.read()

    if not transcript_text.strip():
        logger.warning("Empty transcript, skipping: %s", txt_path)
        return None

    if client is None:
        client = _get_client(model_name)

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
            if provider == "openrouter":
                raw_text = _call_openrouter(client, model_name, user_prompt)
            else:
                raw_text = _call_gemini(client, model_name, user_prompt)

            # Strip markdown fences before parsing
            clean_text = _strip_json_fences(raw_text)

            # Parse the JSON response — fall back to json-repair for malformed LLM output
            try:
                result_dict = json.loads(clean_text)
            except json.JSONDecodeError as json_err:
                logger.warning(
                    "JSON parse failed for %s/%s (%s) — attempting repair",
                    ticker, period, json_err,
                )
                try:
                    from json_repair import repair_json
                    result_dict = json.loads(repair_json(clean_text))
                    logger.info("JSON repaired successfully for %s/%s", ticker, period)
                except Exception as repair_err:
                    # Dump full raw response to a debug file for inspection
                    debug_path = os.path.join(folder, f"debug_{slug}_raw.txt")
                    with open(debug_path, "w", encoding="utf-8") as dbf:
                        dbf.write(raw_text)
                    logger.error(
                        "JSON repair also failed for %s/%s: %s\nFull raw response saved to: %s",
                        ticker, period, repair_err, debug_path,
                    )
                    raise repair_err

            # Validate with Pydantic
            try:
                # If model returned a list, try to use the first element
                if isinstance(result_dict, list):
                    if result_dict and isinstance(result_dict[0], dict):
                        logger.warning(
                            "Model returned a JSON array for %s/%s — using first element",
                            ticker, period,
                        )
                        result_dict = result_dict[0]
                    else:
                        raise ValueError(f"Model returned a JSON array with no usable dict element: {result_dict!r}")

                validated = TranscriptAnalysis(**result_dict)
            except Exception as val_err:
                keys = list(result_dict.keys()) if isinstance(result_dict, dict) else type(result_dict).__name__
                logger.error(
                    "Schema validation error for %s/%s: %s | Keys returned: %s",
                    ticker, period, val_err, keys,
                )
                raise

            result_dict = validated.model_dump()

            # Save to disk (filename encodes the model used)
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(result_dict, f, indent=2, ensure_ascii=False)

            logger.info("Analyzed: %s / %s [%s] -> %s", ticker, period, model_name, json_path)
            return result_dict

        except Exception as e:
            error_str = str(e).lower()
            is_rate_limit = any(
                kw in error_str
                for kw in ["429", "rate", "quota", "resource_exhausted", "too many requests"]
            )

            if is_rate_limit and attempt < max_retries - 1:
                wait = (2 ** attempt) * 5  # 5s, 10s, 20s
                logger.warning(
                    "Rate limited on %s/%s — retrying in %ds (attempt %d/%d)",
                    ticker, period, wait, attempt + 1, max_retries,
                )
                time.sleep(wait)
                continue
            else:
                logger.error(
                    "Failed to analyze %s/%s (attempt %d/%d)",
                    ticker, period, attempt + 1, max_retries,
                    exc_info=True,
                )
                if attempt == max_retries - 1:
                    return None


def _call_gemini(client, model_name: str, user_prompt: str) -> str:
    """Call Gemini API and return raw JSON string."""
    logger.debug("[Gemini] REQUEST model=%s prompt_len=%d", model_name, len(user_prompt))
    response = client.models.generate_content(
        model=model_name,
        contents=user_prompt,
        config=_genai.types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=TranscriptAnalysis,
            temperature=0.1,
        ),
    )
    raw = response.text
    logger.debug("[Gemini] RESPONSE len=%d snippet=%s", len(raw), raw[:120].replace("\n", " "))
    return raw


def _strip_json_fences(text: str) -> str:
    """Remove markdown code fences (```json ... ```) that some models wrap around JSON."""
    text = text.strip()
    if text.startswith("```"):
        # Strip opening fence line
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    return text.strip()


def _call_openrouter(client, model_name: str, user_prompt: str) -> str:
    """Call OpenRouter API with reasoning enabled and return raw JSON string."""
    logger.debug("[OpenRouter] REQUEST model=%s prompt_len=%d", model_name, len(user_prompt))
    schema_json = json.dumps(TranscriptAnalysis.model_json_schema(), indent=2)
    system_with_schema = (
        SYSTEM_PROMPT
        + f"\n\nRespond ONLY with a valid JSON object matching this schema exactly:\n{schema_json}"
    )
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_with_schema},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
        extra_body={
            "reasoning": {"enabled": True},
        },
    )
    raw = response.choices[0].message.content
    logger.debug(
        "[OpenRouter] RESPONSE finish_reason=%s usage=%s len=%d snippet=%s",
        response.choices[0].finish_reason,
        response.usage,
        len(raw),
        raw[:120].replace("\n", " "),
    )
    return raw


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
    recent_quarters: int | None = 1,
    model_name: str = None,
    delay: float = 2.0,
) -> dict:
    """
    Batch-analyze transcripts. Synchronous with a delay between calls for rate-limit safety.

    Args:
        output_root: Root path to Outputs/Concalls/
        tickers: List of ticker symbols to process. None = all.
        ticker_info: Dict mapping ticker -> company_name. Required for new analyses.
        recent_quarters: Number of most recent transcript periods to analyze per ticker.
            None means analyze all available periods.
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

    # Resolve model name first (needed for provider detection and idempotency check)
    resolved_model = model_name or os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
    resolved_slug = _model_to_slug(resolved_model)
    client = _get_client(resolved_model)

    # Discover all txt files to process
    txt_files = _discover_txt_files(output_root, tickers, recent_quarters=recent_quarters)

    if not txt_files:
        logger.warning("No transcript text files found to analyze.")
        return stats

    logger.info("Analyzing %d transcript(s) with [%s]...", len(txt_files), resolved_model)

    for i, (ticker, period, txt_path) in enumerate(txt_files):
        json_path = os.path.join(os.path.dirname(txt_path), f"analysis_{resolved_slug}.json")

        if os.path.exists(json_path):
            stats["skipped"] += 1
            logger.debug(
                "[%d/%d] Skipping %s/%s — already analyzed by %s",
                i + 1, len(txt_files), ticker, period, resolved_model,
            )
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
    recent_quarters: int | None = 1,
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

        selected_periods = select_recent_period_items(period_folders, recent_quarters)
        for period, txt_path in selected_periods:
            results.append((ticker, period, txt_path))
            # Sort by date — folder names like "Feb 2026", "Nov 2025"

    return results
# -----------------------------------
# STANDALONE EXECUTION
# -----------------------------------

if __name__ == "__main__":
    import csv
    configure_logging(logging.INFO)

    # Load ticker info from CSV
    csv_path = os.path.join(os.getcwd(), "tickers.csv")
    ticker_info = {}
    if os.path.exists(csv_path):
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ticker_info[row["ticker"].strip()] = row["company_name"].strip()

    stats = analyze_batch(ticker_info=ticker_info, recent_quarters=1)
    print(f"\nAnalysis complete: {stats}")
