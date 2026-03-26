"""
Concall Result Automation — Orchestrator

Runs the full pipeline: download transcripts → extract text → analyze with Gemini.
All phases are idempotent (skip already-processed files).

Usage:
    python main.py                                # Run all phases for all tickers
    python main.py --tickers CEINSYS,SALZERELEC   # Specific tickers only
    python main.py --phase download               # Run only download phase
    python main.py --phase analyze --all-quarters  # Analyze all quarters, not just latest
"""

import os
import csv
import argparse
import time

from dotenv import load_dotenv
load_dotenv()  # Load .env file before any env var reads

from transcript_downloader import run_downloader
from transcript_extraction import extract_all_transcripts
from analyzer import analyze_batch


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
# MAIN PIPELINE
# -----------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Concall Result Automation Pipeline"
    )
    parser.add_argument(
        "--tickers",
        type=str,
        default=None,
        help="Comma-separated ticker symbols (e.g. CEINSYS,SALZERELEC). Default: all from tickers.csv",
    )
    parser.add_argument(
        "--phase",
        type=str,
        choices=["download", "extract", "analyze", "all"],
        default="all",
        help="Which phase to run (default: all)",
    )
    parser.add_argument(
        "--all-quarters",
        action="store_true",
        help="Analyze all quarters, not just the latest per company",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Gemini model name (default: gemini-2.5-flash or GEMINI_MODEL env var)",
    )
    parser.add_argument(
        "--concurrency-delay",
        type=float,
        default=2.0,
        help="Seconds to wait between API calls (default: 2.0)",
    )

    args = parser.parse_args()

    # Load ticker metadata
    all_ticker_info = load_ticker_info()

    if args.tickers:
        ticker_list = [t.strip() for t in args.tickers.split(",") if t.strip()]
    else:
        ticker_list = list(all_ticker_info.keys())

    if not ticker_list:
        print("No tickers to process. Check tickers.csv.")
        return

    # Build ticker -> company_name mapping for the analyzer
    ticker_names = {t: all_ticker_info.get(t, {}).get("company_name", t) for t in ticker_list}

    output_root = os.path.join(os.getcwd(), "Outputs", "Concalls")
    run_phases = args.phase

    start_time = time.time()

    print("=" * 60)
    print("CONCALL RESULT AUTOMATION PIPELINE")
    print(f"Tickers: {', '.join(ticker_list)}")
    print(f"Phase: {run_phases}")
    print(f"Latest only: {not args.all_quarters}")
    print("=" * 60)

    # --- PHASE 1: DOWNLOAD ---
    if run_phases in ("download", "all"):
        print("\n--- PHASE 1: DOWNLOAD TRANSCRIPTS ---\n")
        run_downloader(tickers=ticker_list)
        print("\nDownload phase complete.")

    # --- PHASE 2: EXTRACT ---
    if run_phases in ("extract", "all"):
        print("\n--- PHASE 2: EXTRACT TEXT FROM PDFs ---\n")
        extract_stats = extract_all_transcripts(
            output_root=output_root,
            tickers=ticker_list,
        )
        print(f"\nExtraction stats: {extract_stats}")

    # --- PHASE 3: ANALYZE ---
    if run_phases in ("analyze", "all"):
        print("\n--- PHASE 3: ANALYZE WITH GEMINI ---\n")
        analyze_stats = analyze_batch(
            output_root=output_root,
            tickers=ticker_list,
            ticker_info=ticker_names,
            latest_only=not args.all_quarters,
            model_name=args.model,
            delay=args.concurrency_delay,
        )
        print(f"\nAnalysis stats: {analyze_stats}")

    # --- SUMMARY ---
    elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    print(f"PIPELINE COMPLETE — {elapsed:.1f}s elapsed")
    print("=" * 60)


if __name__ == "__main__":
    main()
