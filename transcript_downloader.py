"""
Download earnings call transcript PDFs from Screener.in.

The downloader is intentionally file-system driven: each ticker gets a folder
under Outputs/Concalls, and each concall period gets a child folder named like
"Feb 2026". Later pipeline stages rely on that deterministic layout.

This module does not parse PDFs or call the LLM. It only discovers transcript
links and saves Transcript.pdf files when they are not already present.
"""

import os
import csv
import requests
from bs4 import BeautifulSoup
import urllib3
from datetime import datetime
import time

from period_utils import select_recent_period_items

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# -----------------------------------
# CONFIG
# -----------------------------------

base_url = "https://www.screener.in/company/{}/consolidated/"

headers = {
    "User-Agent": "Mozilla/5.0"
}

DEFAULT_RETRIES = 3
DEFAULT_RETRY_DELAY = 2.0

# -----------------------------------
# AUTO CREATE OUTPUT + LOG PATHS
# -----------------------------------

cwd = os.getcwd()

output_root = os.path.join(cwd, "Outputs", "Concalls")
log_root = os.path.join(cwd, "Logs", "Concall")

os.makedirs(output_root, exist_ok=True)
os.makedirs(log_root, exist_ok=True)


# -----------------------------------
# LOGGING
# -----------------------------------

def write_log(ticker, log_type, message):
    """Append a ticker-specific downloader log entry under Logs/Concall/."""

    ticker_log_dir = os.path.join(log_root, ticker)

    os.makedirs(ticker_log_dir, exist_ok=True)

    log_file = os.path.join(ticker_log_dir, f"{log_type}.log")

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now()} | {message}\n")


# -----------------------------------
# DOWNLOAD FUNCTION
# -----------------------------------

def _request_with_retries(
    ticker: str,
    url: str,
    log_context: str,
    retries: int = DEFAULT_RETRIES,
    retry_delay: float = DEFAULT_RETRY_DELAY,
    **request_kwargs,
) -> requests.Response:
    """GET a URL with bounded retries and sleep between failed attempts."""

    attempts = max(1, int(retries or 1))
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(url, headers=headers, timeout=30, **request_kwargs)
            response.raise_for_status()
            return response
        except Exception as e:
            if attempt >= attempts:
                write_log(
                    ticker,
                    "errors",
                    f"{log_context} failed after {attempts} attempt(s) | URL: {url} | Error: {str(e)}",
                )
                raise

            sleep_for = max(0.0, float(retry_delay or 0.0))
            print(
                f"{ticker}: {log_context} failed "
                f"(attempt {attempt}/{attempts}); retrying in {sleep_for:.1f}s"
            )
            write_log(
                ticker,
                "errors",
                f"{log_context} failed attempt {attempt}/{attempts} | URL: {url} | Error: {str(e)}",
            )
            time.sleep(sleep_for)


def download_file(
    ticker,
    url,
    filepath,
    retries: int = DEFAULT_RETRIES,
    retry_delay: float = DEFAULT_RETRY_DELAY,
):
    """Download one PDF unless the target file already exists."""

    try:

        if os.path.exists(filepath):
            print("Already exists:", filepath)
            write_log(ticker, "success", f"Already exists: {filepath}")
            return

        response = _request_with_retries(
            ticker,
            url,
            "Download",
            retries=retries,
            retry_delay=retry_delay,
            verify=False,
        )

        with open(filepath, "wb") as f:
            f.write(response.content)

        print("Downloaded:", filepath)

        write_log(
            ticker,
            "success",
            f"Downloaded: {filepath} | URL: {url}"
        )

    except Exception as e:

        print("Failed downloading:", url)

        write_log(
            ticker,
            "errors",
            f"Download failed | URL: {url} | Error: {str(e)}"
        )


# -----------------------------------
# SCRAPER
# -----------------------------------

def scrape_ticker(
    ticker,
    recent_quarters: int | None = 1,
    retries: int = DEFAULT_RETRIES,
    retry_delay: float = DEFAULT_RETRY_DELAY,
):
    """
    Scrape one Screener.in ticker page and download selected transcripts.

    Args:
        ticker: Screener/NSE ticker symbol.
        recent_quarters: Number of most recent transcript periods to download.
            None means download every transcript link found on the page.
    """

    print("\nProcessing:", ticker)

    url = base_url.format(ticker)

    try:

        response = _request_with_retries(
            ticker,
            url,
            "Screener page load",
            retries=retries,
            retry_delay=retry_delay,
        )

    except Exception as e:

        print("Failed loading page:", ticker)

        write_log(
            ticker,
            "errors",
            f"Failed loading screener page | {url} | Error: {str(e)}"
        )

        return

    soup = BeautifulSoup(response.text, "html.parser")

    concalls_section = soup.select_one("div.documents.concalls")

    if not concalls_section:

        print("Concalls section not found")

        write_log(
            ticker,
            "errors",
            "Concalls section not found"
        )

        return

    rows = concalls_section.select("ul.list-links li")
    transcript_rows = []
    search_limit = recent_quarters if recent_quarters is not None else None

    for row in rows:

        try:

            date_div = row.select_one("div")

            if not date_div:
                continue

            date_text = date_div.text.strip()

            transcript_link = row.find("a", string="Transcript")

            if not transcript_link:

                # Screener lists concalls newest-first. Only log missing transcripts
                # while they can still affect the recent-N selection.
                if search_limit is None or len(transcript_rows) < search_limit:
                    print(date_text, "-> No transcript")
                    write_log(
                        ticker,
                        "errors",
                        f"{date_text} | Transcript not available"
                    )

                continue

            pdf_url = transcript_link.get("href")
            transcript_rows.append((date_text, pdf_url))

            if search_limit is not None and len(transcript_rows) >= search_limit:
                break

        except Exception as e:

            write_log(
                ticker,
                "errors",
                f"Parsing error | {ticker} | Error: {str(e)}"
            )

    selected_rows = select_recent_period_items(transcript_rows, recent_quarters)

    if recent_quarters is not None and len(selected_rows) < recent_quarters:
        message = (
            f"Only {len(selected_rows)} transcript(s) available on Screener; "
            f"requested {recent_quarters}"
        )
        print(message)
        write_log(ticker, "success", message)

    for date_text, pdf_url in selected_rows:

        folder = os.path.join(output_root, ticker, date_text)

        os.makedirs(folder, exist_ok=True)

        filepath = os.path.join(folder, "Transcript.pdf")

        download_file(
            ticker,
            pdf_url,
            filepath,
            retries=retries,
            retry_delay=retry_delay,
        )


# -----------------------------------
# TICKER LOADER
# -----------------------------------

def load_tickers(csv_path: str = None) -> list[str]:
    """Load ticker symbols from tickers.csv. Returns list of ticker strings."""
    if csv_path is None:
        csv_path = os.path.join(os.getcwd(), "tickers.csv")
    if not os.path.exists(csv_path):
        print(f"tickers.csv not found at {csv_path}")
        return []
    tickers = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticker = row.get("ticker", "").strip()
            if ticker:
                tickers.append(ticker)
    return tickers


def run_downloader(
    tickers: list[str] = None,
    recent_quarters: int | None = 1,
    retries: int = DEFAULT_RETRIES,
    retry_delay: float = DEFAULT_RETRY_DELAY,
):
    """
    Download transcripts for a ticker list.

    If tickers is None, symbols are loaded from tickers.csv. Tickers are
    processed sequentially with bounded retries for page loads and PDFs.
    """
    if tickers is None:
        tickers = load_tickers()
    if not tickers:
        print("No tickers to process.")
        return
    for ticker in tickers:
        scrape_ticker(
            ticker,
            recent_quarters=recent_quarters,
            retries=retries,
            retry_delay=retry_delay,
        )
        time.sleep(1)  # polite delay between requests


# -----------------------------------
# RUN
# -----------------------------------

if __name__ == "__main__":
    run_downloader()
