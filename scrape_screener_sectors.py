"""
Scrape Screener sector/category pages into a stock ticker Excel file.

The script starts at https://www.screener.in/explore/, discovers the sector
links under "Browse sectors", visits each sub-category and each paginated
result page, then opens company pages to capture NSE and BSE tickers.

Usage:
    python scrape_screener_sectors.py
    python scrape_screener_sectors.py --output Outputs/stock_sector_tickers.xlsx
"""

from __future__ import annotations

import argparse
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.screener.in"
EXPLORE_URL = f"{BASE_URL}/explore/"
DEFAULT_OUTPUT = Path("Outputs") / "stock_sector_tickers.xlsx"


@dataclass(frozen=True)
class CategoryLink:
    category: str
    sub_category: str
    url: str


class ScreenerSectorScraper:
    def __init__(
        self,
        min_delay: float = 1.2,
        max_delay: float = 3.5,
        timeout: float = 30.0,
        retries: int = 3,
    ) -> None:
        if min_delay < 0 or max_delay < min_delay:
            raise ValueError("Delay values must satisfy 0 <= min_delay <= max_delay")

        self.min_delay = min_delay
        self.max_delay = max_delay
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Connection": "keep-alive",
            }
        )

    def polite_pause(self) -> None:
        time.sleep(random.uniform(self.min_delay, self.max_delay))

    def get_soup(self, url: str) -> BeautifulSoup:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                self.polite_pause()
                response = self.session.get(url, timeout=self.timeout)
                response.raise_for_status()
                return BeautifulSoup(response.text, "html.parser")
            except requests.RequestException as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(min(20.0, attempt * 3.0 + random.random()))
        raise RuntimeError(f"Failed to fetch {url}: {last_error}") from last_error

    def discover_sector_links(self) -> list[CategoryLink]:
        soup = self.get_soup(EXPLORE_URL)
        links: list[CategoryLink] = []
        seen: set[str] = set()

        for anchor in soup.select('a[href^="/market/"]'):
            href = anchor.get("href", "")
            url = urljoin(BASE_URL, href)
            category = clean_link_text(anchor.get_text(" ", strip=True))
            if not category or url in seen:
                continue
            seen.add(url)
            links.append(CategoryLink(category=category, sub_category=category, url=url))

        if not links:
            raise RuntimeError("No sector links found on Screener explore page.")
        return links

    def discover_sub_category_links(self, sector: CategoryLink) -> list[CategoryLink]:
        soup = self.get_soup(sector.url)
        links: list[CategoryLink] = []
        seen: set[str] = set()

        for anchor in soup.select('a[href^="/market/"]'):
            raw_text = anchor.get_text(" ", strip=True)
            match = re.match(r"^(?P<name>.+?)\s+-\s+\d+\s*$", raw_text)
            if not match:
                continue

            url = urljoin(BASE_URL, anchor.get("href", ""))
            if url in seen:
                continue

            seen.add(url)
            links.append(
                CategoryLink(
                    category=sector.category,
                    sub_category=clean_link_text(match.group("name")),
                    url=url,
                )
            )

        return links or [sector]

    def scrape_listing_pages(self, category_link: CategoryLink) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        seen_pages: set[str] = set()
        next_url: str | None = category_link.url

        while next_url and next_url not in seen_pages:
            seen_pages.add(next_url)
            soup = self.get_soup(next_url)
            company_links = list(extract_company_links(soup))

            for company_name, company_url in company_links:
                rows.append(
                    {
                        "company_name": company_name,
                        "company_url": company_url,
                        "category": category_link.category,
                        "sub_category": category_link.sub_category,
                    }
                )

            next_url = find_next_page_url(soup)

        return rows

    def enrich_with_exchange_tickers(self, row: dict[str, str]) -> dict[str, str]:
        soup = self.get_soup(row["company_url"])
        page_text = soup.get_text(" ", strip=True)
        nse_ticker = find_exchange_ticker(page_text, "NSE")
        bse_ticker = find_exchange_ticker(page_text, "BSE")

        enriched = dict(row)
        enriched["nse_ticker"] = nse_ticker or ticker_from_company_url(row["company_url"])
        enriched["bse_ticker"] = bse_ticker
        return enriched


def clean_link_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def extract_company_links(soup: BeautifulSoup) -> Iterable[tuple[str, str]]:
    seen: set[str] = set()
    for table in soup.select("table.data-table"):
        for anchor in table.select('a[href^="/company/"]'):
            href = anchor.get("href", "")
            url = urljoin(BASE_URL, href)
            parsed = urlparse(url)
            if not parsed.path.startswith("/company/") or url in seen:
                continue

            name = clean_link_text(anchor.get_text(" ", strip=True))
            if not name:
                continue

            seen.add(url)
            yield name, url


def find_next_page_url(soup: BeautifulSoup) -> str | None:
    for anchor in soup.find_all("a", href=True):
        if clean_link_text(anchor.get_text(" ", strip=True)).lower() == "next":
            return urljoin(BASE_URL, anchor["href"])
    return None


def find_exchange_ticker(page_text: str, exchange: str) -> str:
    match = re.search(rf"\b{exchange}\s*:\s*([A-Z0-9&.\-]+)\b", page_text)
    return match.group(1).strip() if match else ""


def ticker_from_company_url(company_url: str) -> str:
    match = re.search(r"/company/([^/]+)/", urlparse(company_url).path)
    return match.group(1).strip().upper() if match else ""


def dedupe_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        key = (
            row.get("company_url", ""),
            row.get("category", ""),
            row.get("sub_category", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def normalize_exchange_tickers(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for row in rows:
        row = dict(row)
        nse_ticker = str(row.get("nse_ticker", "") or "").strip()
        bse_ticker = str(row.get("bse_ticker", "") or "").strip()

        if nse_ticker.isdigit():
            if not bse_ticker or bse_ticker == nse_ticker:
                bse_ticker = nse_ticker
            nse_ticker = ""

        row["nse_ticker"] = nse_ticker
        row["bse_ticker"] = bse_ticker
        normalized.append(row)
    return normalized


def write_excel(rows: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "company_name",
        "nse_ticker",
        "bse_ticker",
        "category",
        "sub_category",
        "company_url",
    ]
    df = pd.DataFrame(normalize_exchange_tickers(rows))
    if df.empty:
        df = pd.DataFrame(columns=columns)
    else:
        df = df.reindex(columns=columns).sort_values(
            ["category", "sub_category", "company_name"],
            kind="stable",
        )
    df.to_excel(output_path, index=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a Screener sector stock Excel with NSE/BSE tickers."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--min-delay", type=float, default=1.2)
    parser.add_argument("--max-delay", type=float, default=3.5)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument(
        "--skip-company-pages",
        action="store_true",
        help="Do not open company pages; use Screener URL symbol as NSE ticker fallback.",
    )
    parser.add_argument(
        "--max-sectors",
        type=int,
        default=None,
        help="Optional smoke-test limit; default visits every sector.",
    )
    parser.add_argument(
        "--max-sub-categories",
        type=int,
        default=None,
        help="Optional smoke-test limit per sector; default visits every sub-category.",
    )
    parser.add_argument(
        "--max-companies",
        type=int,
        default=None,
        help="Optional smoke-test limit before ticker enrichment; default includes all companies.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    scraper = ScreenerSectorScraper(
        min_delay=args.min_delay,
        max_delay=args.max_delay,
        timeout=args.timeout,
        retries=args.retries,
    )

    sectors = scraper.discover_sector_links()
    if args.max_sectors is not None:
        sectors = sectors[: args.max_sectors]
    print(f"Discovered {len(sectors)} sector pages.")

    listing_rows: list[dict[str, str]] = []
    for sector_index, sector in enumerate(sectors, start=1):
        print(f"[{sector_index}/{len(sectors)}] Sector: {sector.category}")
        sub_categories = scraper.discover_sub_category_links(sector)
        if args.max_sub_categories is not None:
            sub_categories = sub_categories[: args.max_sub_categories]

        for sub_index, sub_category in enumerate(sub_categories, start=1):
            print(
                f"  [{sub_index}/{len(sub_categories)}] "
                f"Sub-category: {sub_category.sub_category}"
            )
            listing_rows.extend(scraper.scrape_listing_pages(sub_category))

    listing_rows = dedupe_rows(listing_rows)
    if args.max_companies is not None:
        listing_rows = listing_rows[: args.max_companies]
    print(f"Collected {len(listing_rows)} company/category rows.")

    if args.skip_company_pages:
        final_rows = []
        for row in listing_rows:
            row = dict(row)
            row["nse_ticker"] = ticker_from_company_url(row["company_url"])
            row["bse_ticker"] = ""
            final_rows.append(row)
    else:
        final_rows = []
        for index, row in enumerate(listing_rows, start=1):
            print(f"  [{index}/{len(listing_rows)}] Tickers: {row['company_name']}")
            final_rows.append(scraper.enrich_with_exchange_tickers(row))

    write_excel(final_rows, args.output)
    print(f"Saved {len(final_rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
