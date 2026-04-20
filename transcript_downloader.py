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

    ticker_log_dir = os.path.join(log_root, ticker)

    os.makedirs(ticker_log_dir, exist_ok=True)

    log_file = os.path.join(ticker_log_dir, f"{log_type}.log")

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now()} | {message}\n")


# -----------------------------------
# DOWNLOAD FUNCTION
# -----------------------------------

def download_file(ticker, url, filepath):

    try:

        if os.path.exists(filepath):
            print("Already exists:", filepath)
            write_log(ticker, "success", f"Already exists: {filepath}")
            return

        response = requests.get(
            url,
            headers=headers,
            verify=False,
            timeout=30
        )

        response.raise_for_status()

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

def scrape_ticker(ticker, recent_quarters: int | None = 1):

    print("\nProcessing:", ticker)

    url = base_url.format(ticker)

    try:

        response = requests.get(
            url,
            headers=headers,
            timeout=30
        )

        response.raise_for_status()

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

        download_file(ticker, pdf_url, filepath)


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


def run_downloader(tickers: list[str] = None, recent_quarters: int | None = 1):
    """Download transcripts for given tickers. If None, loads from tickers.csv."""
    if tickers is None:
        tickers = load_tickers()
    if not tickers:
        print("No tickers to process.")
        return
    for ticker in tickers:
        scrape_ticker(ticker, recent_quarters=recent_quarters)
        time.sleep(1)  # polite delay between requests


# -----------------------------------
# RUN
# -----------------------------------

if __name__ == "__main__":
    run_downloader()
