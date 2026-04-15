"""
Concall Result Automation — Orchestrator

Runs the full pipeline: download transcripts → extract text → analyze with LLM.
All phases are idempotent (skip already-processed files).

Usage:
    python main.py                        # Use config.yaml defaults
    python main.py --watch                # Watch mode (overrides config)
    python main.py --phase analyze        # Override a single setting
    python main.py --config my.yaml       # Use a different config file
"""

import os
import csv
import argparse
import time
import logging

import yaml
from dotenv import load_dotenv
load_dotenv()  # Load .env file before any env var reads

from transcript_downloader import run_downloader
from transcript_extraction import extract_all_transcripts
from analyzer import analyze_batch, analyze_transcript, _get_client, DEFAULT_MODEL, configure_logging, _discover_txt_files
from period_utils import normalize_recent_quarters


# -----------------------------------
# CONFIG LOADER
# -----------------------------------

_CONFIG_DEFAULTS = {
    "tickers": [],
    "models": [],
    "phase": "all",
    "all_quarters": False,
    "recent_quarters": 1,
    "watch": False,
    "poll_interval": 30.0,
    "api_delay": 2.0,
}


def load_config(path: str = None) -> dict:
    """Load config.yaml and merge with defaults. Missing keys fall back to defaults."""
    if path is None:
        path = os.path.join(os.getcwd(), "config.yaml")
    cfg = dict(_CONFIG_DEFAULTS)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        cfg.update({k: v for k, v in loaded.items() if k in _CONFIG_DEFAULTS})
    return cfg


# -----------------------------------
# TICKER LOADER
# -----------------------------------

def load_ticker_info(csv_path: str = None) -> dict[str, dict]:
    """
    Load full ticker metadata from tickers.csv.
    Returns dict: {ticker: {company_name, sector, sub_sector}}
    """
    if csv_path is None:
        csv_path = os.path.join(os.getcwd(), "tickers.csv")

    if not os.path.exists(csv_path):
        print(f"ERROR: tickers.csv not found at {csv_path}")
        return {}

    info = {}
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticker = row.get("ticker", "").strip()
            if ticker:
                info[ticker] = {
                    "company_name": row.get("company_name", ticker).strip(),
                    "sector": row.get("sector", "").strip(),
                    "sub_sector": row.get("sub_sector", "").strip(),
                }
    return info


# -----------------------------------
# WATCH MODE
# -----------------------------------

def _resolve_recent_quarters(cfg: dict) -> int | None:
    """Resolve quarter scope from config. None means process all available periods."""
    if cfg.get("all_quarters"):
        return None
    return normalize_recent_quarters(cfg.get("recent_quarters", 1))


def _snapshot_txt_files(output_root: str, tickers: list[str], recent_quarters: int | None) -> set[str]:
    """Return the tracked Transcript.txt paths currently on disk for given tickers."""
    return {
        txt_path
        for _, _, txt_path in _discover_txt_files(
            output_root=output_root,
            tickers=tickers,
            recent_quarters=recent_quarters,
        )
    }


def watch_mode(
    ticker_list: list[str],
    ticker_names: dict[str, str],
    output_root: str,
    models: list[str] = None,
    recent_quarters: int | None = 1,
    poll_interval: float = 30.0,
    delay: float = 2.0,
):
    """
    Continuously poll for new transcripts. On each poll:
      1. Download + extract for the configured recent scope
      2. Detect any Transcript.txt files that are new since last poll
      3. Immediately analyze only those new files with ALL configured models
    """
    log = logging.getLogger(__name__)
    default_model = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
    resolved_models = models if models else [default_model]

    log.info("=" * 60)
    log.info("WATCH MODE STARTED")
    log.info("Tickers : %s", ", ".join(ticker_list))
    log.info("Models  : %s", ", ".join(resolved_models))
    log.info("Scope   : %s", "all quarters" if recent_quarters is None else f"last {recent_quarters} concall(s) per ticker")
    log.info("Interval: %ss", poll_interval)
    log.info("=" * 60)

    known_txts = _snapshot_txt_files(output_root, ticker_list, recent_quarters)
    log.info("Baseline: %d existing transcript(s) found.", len(known_txts))

    # Pre-build a client per model
    clients = {m: _get_client(m) for m in resolved_models}
    poll = 0

    while True:
        poll += 1
        log.info("--- Poll #%d: downloading + extracting ---", poll)

        run_downloader(tickers=ticker_list, recent_quarters=recent_quarters)
        extract_all_transcripts(
            output_root=output_root,
            tickers=ticker_list,
            recent_quarters=recent_quarters,
        )

        current_txts = _snapshot_txt_files(output_root, ticker_list, recent_quarters)
        new_txts = sorted(current_txts - known_txts)

        if new_txts:
            log.info("New transcript(s) detected: %d", len(new_txts))
            for i, txt_path in enumerate(new_txts):
                parts = txt_path.replace("\\", "/").split("/")
                ticker = parts[-3]
                period = parts[-2]
                company_name = ticker_names.get(ticker, ticker)

                for j, model in enumerate(resolved_models):
                    log.info(
                        "  [transcript %d/%d] [model %d/%d] Analyzing %s / %s with %s",
                        i + 1, len(new_txts), j + 1, len(resolved_models), ticker, period, model,
                    )
                    analyze_transcript(
                        txt_path=txt_path,
                        ticker=ticker,
                        company_name=company_name,
                        model_name=model,
                        client=clients[model],
                    )
                    # Delay between API calls (skip after the very last call)
                    if not (i == len(new_txts) - 1 and j == len(resolved_models) - 1):
                        time.sleep(delay)

            known_txts = current_txts
        else:
            log.info("No new transcripts. Next poll in %.0fs...", poll_interval)

        time.sleep(poll_interval)


# -----------------------------------
# MAIN PIPELINE
# -----------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Concall Result Automation Pipeline"
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to YAML config file (default: config.yaml in cwd)",
    )
    # Optional CLI overrides — all default to None so we can detect "not provided"
    parser.add_argument("--tickers", type=str, default=None, help="Comma-separated tickers (overrides config)")
    parser.add_argument("--models",  type=str, default=None, help="Comma-separated models (overrides config)")
    parser.add_argument("--phase",   type=str, default=None, choices=["download", "extract", "analyze", "all"], help="Pipeline phase (overrides config)")
    parser.add_argument("--all-quarters", action="store_true", default=None, help="Analyze all quarters (overrides config)")
    parser.add_argument("--recent-quarters", type=int, default=None, help="Number of most recent concalls per ticker to process when all_quarters is false")
    parser.add_argument("--watch",        action="store_true", default=None, help="Watch mode (overrides config)")
    parser.add_argument("--poll-interval",    type=float, default=None, help="Seconds between polls (overrides config)")
    parser.add_argument("--concurrency-delay", type=float, default=None, help="Seconds between API calls (overrides config)")

    args = parser.parse_args()

    configure_logging(logging.INFO)
    log = logging.getLogger(__name__)

    # Load YAML config, then apply any CLI overrides on top
    cfg = load_config(args.config)
    if args.tickers      is not None: cfg["tickers"]      = [t.strip() for t in args.tickers.split(",") if t.strip()]
    if args.models       is not None: cfg["models"]       = [m.strip() for m in args.models.split(",")  if m.strip()]
    if args.phase        is not None: cfg["phase"]        = args.phase
    if args.all_quarters            : cfg["all_quarters"] = True
    if args.recent_quarters is not None: cfg["recent_quarters"] = args.recent_quarters
    if args.watch                   : cfg["watch"]        = True
    if args.poll_interval    is not None: cfg["poll_interval"] = args.poll_interval
    if args.concurrency_delay is not None: cfg["api_delay"]   = args.concurrency_delay

    # Load ticker metadata
    all_ticker_info = load_ticker_info()

    ticker_list = cfg["tickers"] or list(all_ticker_info.keys())
    if not ticker_list:
        log.error("No tickers to process. Check tickers.csv or config.yaml.")
        return

    models = cfg["models"] or [os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)]
    ticker_names = {t: all_ticker_info.get(t, {}).get("company_name", t) for t in ticker_list}
    output_root = os.path.join(os.getcwd(), "Outputs", "Concalls")
    recent_quarters = _resolve_recent_quarters(cfg)

    # --- WATCH MODE ---
    if cfg["watch"]:
        watch_mode(
            ticker_list=ticker_list,
            ticker_names=ticker_names,
            output_root=output_root,
            models=models,
            recent_quarters=recent_quarters,
            poll_interval=cfg["poll_interval"],
            delay=cfg["api_delay"],
        )
        return

    # --- BATCH PIPELINE ---
    run_phases = cfg["phase"]
    start_time = time.time()

    log.info("=" * 60)
    log.info("CONCALL RESULT AUTOMATION PIPELINE")
    log.info("Tickers: %s", ", ".join(ticker_list))
    log.info("Models : %s", ", ".join(models))
    log.info("Phase  : %s", run_phases)
    log.info("Scope  : %s", "all quarters" if recent_quarters is None else f"last {recent_quarters} concall(s) per ticker")
    log.info("=" * 60)

    if run_phases in ("download", "all"):
        log.info("--- PHASE 1: DOWNLOAD TRANSCRIPTS ---")
        run_downloader(tickers=ticker_list, recent_quarters=recent_quarters)
        log.info("Download phase complete.")

    if run_phases in ("extract", "all"):
        log.info("--- PHASE 2: EXTRACT TEXT FROM PDFs ---")
        extract_stats = extract_all_transcripts(
            output_root=output_root,
            tickers=ticker_list,
            recent_quarters=recent_quarters,
        )
        log.info("Extraction stats: %s", extract_stats)

    if run_phases in ("analyze", "all"):
        log.info("--- PHASE 3: ANALYZE WITH LLM ---")
        for model in models:
            analyze_stats = analyze_batch(
                output_root=output_root,
                tickers=ticker_list,
                ticker_info=ticker_names,
                recent_quarters=recent_quarters,
                model_name=model,
                delay=cfg["api_delay"],
            )
            log.info("Analysis stats [%s]: %s", model, analyze_stats)

    elapsed = time.time() - start_time
    log.info("=" * 60)
    log.info("PIPELINE COMPLETE — %.1fs elapsed", elapsed)
    log.info("=" * 60)


if __name__ == "__main__":
    main()
