"""
Extract text from downloaded transcript PDFs.

Input files are expected at:
    Outputs/Concalls/<TICKER>/<Mon YYYY>/Transcript.pdf

Output files are written next to the PDF as:
    Outputs/Concalls/<TICKER>/<Mon YYYY>/Transcript.txt

The extraction stage is idempotent and skips PDFs that already have a text
file. The analyzer consumes the text files produced here.
"""

import os
import glob
import traceback
from collections import defaultdict

import fitz  # PyMuPDF

from period_utils import select_recent_period_items


def extract_transcript_text(pdf_path: str) -> str:
    """
    Extract all text from a transcript PDF.

    Page boundaries are preserved with a visible delimiter so raw extraction
    issues are easier to inspect when LLM output looks suspicious.
    """
    text_content = []

    try:
        with fitz.open(pdf_path) as doc:
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                page_text = page.get_text("text")
                text_content.append(page_text)

        full_text = "\n\n--- PAGE BREAK ---\n\n".join(text_content)
        return full_text

    except Exception as e:
        print(f"Error extracting text from {pdf_path}: {e} {traceback.format_exc()}")
        return ""


def _select_pdf_paths(pdf_paths: list[str], recent_quarters: int | None) -> list[str]:
    """Select the most recent N transcript PDFs per ticker. None means all."""
    grouped_paths = defaultdict(list)

    for pdf_path in pdf_paths:
        period = os.path.basename(os.path.dirname(pdf_path))
        ticker = os.path.basename(os.path.dirname(os.path.dirname(pdf_path)))
        grouped_paths[ticker].append((period, pdf_path))

    selected_paths = []
    for ticker in sorted(grouped_paths):
        selected_paths.extend(
            pdf_path
            for _, pdf_path in select_recent_period_items(grouped_paths[ticker], recent_quarters)
        )

    return selected_paths


def extract_all_transcripts(
    output_root: str = None,
    tickers: list[str] = None,
    recent_quarters: int | None = 1,
) -> dict:
    """
    Batch-extract all Transcript.pdf -> Transcript.txt under output_root.

    Skips PDFs that already have a Transcript.txt sibling.
    Returns dict with counts: {'extracted': N, 'skipped': N, 'failed': N}
    """
    if output_root is None:
        output_root = os.path.join(os.getcwd(), "Outputs", "Concalls")

    stats = {"extracted": 0, "skipped": 0, "failed": 0}

    # If tickers specified, only process those folders; otherwise process all
    if tickers:
        pdf_paths = []
        for ticker in tickers:
            pattern = os.path.join(output_root, ticker, "*", "Transcript.pdf")
            pdf_paths.extend(glob.glob(pattern))
    else:
        pattern = os.path.join(output_root, "*", "*", "Transcript.pdf")
        pdf_paths = glob.glob(pattern)

    for pdf_path in _select_pdf_paths(pdf_paths, recent_quarters):
        txt_path = pdf_path.replace("Transcript.pdf", "Transcript.txt")

        if os.path.exists(txt_path):
            stats["skipped"] += 1
            continue

        raw_text = extract_transcript_text(pdf_path)

        if raw_text:
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(raw_text)
            word_count = len(raw_text.split())
            print(f"  Extracted: {pdf_path} ({word_count:,} words)")
            stats["extracted"] += 1
        else:
            print(f"  Failed: {pdf_path}")
            stats["failed"] += 1

    return stats


# --- Execution ---
if __name__ == "__main__":
    stats = extract_all_transcripts()
    print(f"\nExtraction complete: {stats}")
