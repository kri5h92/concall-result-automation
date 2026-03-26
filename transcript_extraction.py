import os
import glob
import traceback

import fitz  # PyMuPDF


def extract_transcript_text(pdf_path: str) -> str:
    """
    Extracts all text from a given PDF transcript.
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


def extract_all_transcripts(output_root: str = None, tickers: list[str] = None) -> dict:
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

    for pdf_path in pdf_paths:
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