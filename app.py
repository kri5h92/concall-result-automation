"""
Concall Result Automation - Streamlit Viewer

Interactive dashboard to explore analyzed earnings call transcripts.
Run with:
    streamlit run app.py
"""

import csv
import json
import math
import os
import re as _re
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st


ANALYSIS_SECTIONS = [
    "financial_guidance",
    "growth_drivers",
    "capacity_capex",
    "margins_commentary",
    "order_book_demand",
    "red_flags",
    "quarter_change",
    "key_quotes",
    "analyst_take",
]

SECTION_LABELS = {
    "financial_guidance": "Financial Guidance",
    "growth_drivers": "Growth Drivers",
    "capacity_capex": "Capacity and Capex",
    "margins_commentary": "Margins Commentary",
    "order_book_demand": "Order Book and Demand",
    "red_flags": "Red Flags",
    "quarter_change": "Change vs Previous Quarter",
    "key_quotes": "Key Quotes",
    "analyst_take": "Analyst Take",
}

SECTION_GROUPS = {
    "Highlights": [
        "financial_guidance",
        "growth_drivers",
        "margins_commentary",
    ],
    "Operations": [
        "capacity_capex",
        "order_book_demand",
        "quarter_change",
    ],
    "Risk and View": [
        "red_flags",
        "key_quotes",
        "analyst_take",
    ],
}

NOT_DISCLOSED_VALUES = {
    "",
    "n/a",
    "na",
    "none",
    "not available",
    "not disclosed",
}

RESULT_SORT_OPTIONS = [
    "Newest quarter",
    "Oldest quarter",
    "Company A-Z",
    "Company Z-A",
]

PAGE_SIZE_OPTIONS = [5, 8, 12, 20]
DEFAULT_PAGE_SIZE = 8
ENABLE_SECTOR_FILTERS = False


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
            .block-container {
                max-width: 1420px;
                padding-top: 1.75rem;
                padding-bottom: 2rem;
            }
            div[data-testid="stMetric"] {
                background: linear-gradient(
                    135deg,
                    rgba(14, 116, 144, 0.08),
                    rgba(249, 115, 22, 0.09)
                );
                border: 1px solid rgba(15, 23, 42, 0.08);
                border-radius: 18px;
                padding: 0.85rem 1rem;
            }
            div[data-testid="stExpander"] {
                border: 1px solid rgba(15, 23, 42, 0.08);
                border-radius: 16px;
                overflow: hidden;
            }
            div[data-testid="stDataFrame"] {
                border: 1px solid rgba(15, 23, 42, 0.08);
                border-radius: 16px;
                overflow: hidden;
            }
            section[data-testid="stSidebar"] {
                border-right: 1px solid rgba(15, 23, 42, 0.08);
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _clean_text(value) -> str:
    """Normalize whitespace and line endings for display."""
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    text = _re.sub(r"[ \t]+", " ", text)
    text = _re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _is_not_disclosed(value) -> bool:
    text = _clean_text(value).lower().strip(" .:-_")
    return text in NOT_DISCLOSED_VALUES


def _normalize_analyst_take(value):
    """Support both legacy string and current dict analyst_take shapes."""
    if isinstance(value, dict):
        return {
            "bull_case": _clean_text(value.get("bull_case", "")),
            "bear_case": _clean_text(value.get("bear_case", "")),
            "monitorables": _clean_text(value.get("monitorables", "")),
        }

    if not isinstance(value, str):
        return value

    text = _clean_text(value)
    match = _re.search(
        r"(?is)\bbull\s*case\b\s*:\s*(.*?)\s*\bbear\s*case\b\s*:\s*(.*?)\s*\bmonitorables\b\s*:\s*(.*)$",
        text,
    )
    if not match:
        return text

    return {
        "bull_case": _clean_text(match.group(1)),
        "bear_case": _clean_text(match.group(2)),
        "monitorables": _clean_text(match.group(3)),
    }


def _normalize_key_quotes(value) -> list[str]:
    if isinstance(value, list):
        return [_clean_text(item) for item in value if _clean_text(item)]
    if _clean_text(value):
        return [_clean_text(value)]
    return []


def _normalize_analysis_record(data: dict) -> dict:
    """Coerce loaded JSON into a consistent shape for rendering."""
    normalized = dict(data)

    for key, value in list(normalized.items()):
        if key == "analyst_take":
            normalized[key] = _normalize_analyst_take(value)
        elif key == "key_quotes":
            normalized[key] = _normalize_key_quotes(value)
        elif isinstance(value, str):
            normalized[key] = _clean_text(value)

    return normalized


def _normalize_company_suffixes(name: str) -> str:
    """Normalize common company suffix variants used by generated JSON."""
    text = _clean_text(name)
    text = _re.sub(r"\bLtd\.?\b", "Limited", text, flags=_re.IGNORECASE)
    return text


def _canonical_company_name(ticker: str, data: dict, meta: dict) -> str:
    """Use ticker metadata as the display/grouping source, with JSON fallback."""
    meta_name = _clean_text(meta.get("company_name", ""))
    if meta_name:
        return meta_name

    json_name = _clean_text(data.get("company_name", ""))
    if json_name:
        return _normalize_company_suffixes(json_name)

    return ticker


def _analysis_file_sort_key(path: str) -> tuple[float, str]:
    """Sort analysis files by modification time with filename as a tie-breaker."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0
    return mtime, os.path.basename(path)


def _latest_analysis_path(period_path: str) -> str | None:
    analysis_paths = []
    try:
        filenames = os.listdir(period_path)
    except OSError:
        return None

    for fname in filenames:
        if fname == "analysis.json" or (
            fname.startswith("analysis_") and fname.endswith(".json")
        ):
            analysis_paths.append(os.path.join(period_path, fname))

    if not analysis_paths:
        return None

    return sorted(analysis_paths, key=_analysis_file_sort_key, reverse=True)[0]


@st.cache_data(show_spinner=False)
def load_ticker_metadata(csv_path: str) -> dict[str, dict]:
    """Load tickers.csv into a dict keyed by ticker."""
    info = {}
    if not os.path.exists(csv_path):
        return info

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


@st.cache_data(show_spinner=False)
def load_analysis_index(output_root: str, ticker_meta: dict[str, dict]) -> pd.DataFrame:
    """
    Index analyses without opening every JSON payload.

    The index is enough for filters, pagination, and summaries. Full analysis
    content is loaded only for the active record or comparison subset.
    """
    records = []

    if not os.path.isdir(output_root):
        return pd.DataFrame()

    for ticker_name in sorted(os.listdir(output_root)):
        ticker_dir = os.path.join(output_root, ticker_name)
        if not os.path.isdir(ticker_dir):
            continue

        meta = ticker_meta.get(ticker_name, {})
        indexed_company_name = _clean_text(meta.get("company_name", "")) or ticker_name

        for period_name in sorted(os.listdir(ticker_dir)):
            period_path = os.path.join(ticker_dir, period_name)
            if not os.path.isdir(period_path):
                continue

            selected_json_path = _latest_analysis_path(period_path)
            if not selected_json_path:
                continue

            records.append(
                {
                    "company_name": indexed_company_name,
                    "sector": meta.get("sector", "Unknown") or "Unknown",
                    "sub_sector": meta.get("sub_sector", "Unknown") or "Unknown",
                    "_ticker_folder": ticker_name,
                    "_period_folder": period_name,
                    "_analysis_path": selected_json_path,
                    "_analysis_mtime": _analysis_file_sort_key(selected_json_path)[0],
                }
            )

    if not records:
        return pd.DataFrame()

    return pd.DataFrame(records)


@st.cache_data(show_spinner=False)
def load_analysis_record(
    json_path: str,
    analysis_mtime: float,
    ticker: str,
    period_name: str,
    indexed_company_name: str,
    sector: str,
    sub_sector: str,
) -> dict:
    """Load and normalize one analysis JSON file."""
    del analysis_mtime

    fallback_record = {
        "company_name": indexed_company_name or ticker,
        "sector": sector or "Unknown",
        "sub_sector": sub_sector or "Unknown",
        "_ticker_folder": ticker,
        "_period_folder": period_name,
        "_analysis_path": json_path,
        "_analysis_mtime": _analysis_file_sort_key(json_path)[0],
        "_quarter_label": _period_quarter_label(period_name),
        "_quarter_sort": _period_quarter_sort(period_name),
        "_period_start": _period_month_start(period_name),
        "_period_end": _period_month_end(period_name),
    }

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        fallback_record["_load_error"] = str(exc)
        return fallback_record

    data = _normalize_analysis_record(data)
    meta = {
        "company_name": indexed_company_name if indexed_company_name != ticker else "",
        "sector": sector,
        "sub_sector": sub_sector,
    }

    data["company_name"] = _canonical_company_name(ticker, data, meta)
    data["sector"] = sector or "Unknown"
    data["sub_sector"] = sub_sector or "Unknown"
    data["_ticker_folder"] = ticker
    data["_period_folder"] = period_name
    data["_analysis_path"] = json_path
    data["_analysis_mtime"] = _analysis_file_sort_key(json_path)[0]
    data["_quarter_label"] = _period_quarter_label(period_name)
    data["_quarter_sort"] = _period_quarter_sort(period_name)
    data["_period_start"] = _period_month_start(period_name)
    data["_period_end"] = _period_month_end(period_name)
    return data


def _with_period_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    work = df.copy()
    work["_period_start"] = work["_period_folder"].map(_period_month_start)
    work["_period_end"] = work["_period_folder"].map(_period_month_end)
    work["_quarter_label"] = work["_period_folder"].map(_period_quarter_label)
    work["_quarter_sort"] = work["_period_folder"].map(_period_quarter_sort)
    return work


def _sort_results(df: pd.DataFrame, sort_order: str) -> pd.DataFrame:
    if df.empty:
        return df

    if sort_order == "Oldest quarter":
        return df.sort_values(
            ["_quarter_sort", "company_name", "_analysis_mtime"],
            ascending=[True, True, False],
        )
    if sort_order == "Company A-Z":
        return df.sort_values(
            ["company_name", "_quarter_sort", "_analysis_mtime"],
            ascending=[True, False, False],
        )
    if sort_order == "Company Z-A":
        return df.sort_values(
            ["company_name", "_quarter_sort", "_analysis_mtime"],
            ascending=[False, False, False],
        )

    return df.sort_values(
        ["_quarter_sort", "company_name", "_analysis_mtime"],
        ascending=[False, True, False],
    )


def _latest_record_per_company(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    ordered = df.sort_values(
        ["_ticker_folder", "_quarter_sort", "_analysis_mtime"],
        ascending=[True, False, False],
    )
    return ordered.drop_duplicates("_ticker_folder", keep="first")


def _load_row_analysis(row: pd.Series) -> dict:
    return load_analysis_record(
        json_path=row["_analysis_path"],
        analysis_mtime=float(row["_analysis_mtime"]),
        ticker=row["_ticker_folder"],
        period_name=row["_period_folder"],
        indexed_company_name=row["company_name"],
        sector=row["sector"],
        sub_sector=row["sub_sector"],
    )


def _materialize_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    records = [_load_row_analysis(row) for _, row in df.iterrows()]
    return pd.DataFrame(records)


def _summary_frame(df: pd.DataFrame) -> pd.DataFrame:
    summary = df[
        ["company_name", "_ticker_folder", "_quarter_label", "_period_folder", "sector", "sub_sector"]
    ].copy()
    summary.columns = ["Company", "Ticker", "Quarter", "Period", "Sector", "Sub-sector"]
    return summary.reset_index(drop=True)


def _record_label(row: pd.Series) -> str:
    return f"{row['company_name']} ({row['_ticker_folder']}) - {row['_quarter_label']}"


def _page_slice(df: pd.DataFrame, page_size: int, key_prefix: str) -> tuple[pd.DataFrame, int, int]:
    if df.empty:
        return df, 1, 1

    total_pages = max(1, math.ceil(len(df) / page_size))
    page = int(
        st.number_input(
            "Page",
            min_value=1,
            max_value=total_pages,
            value=1,
            step=1,
            key=f"{key_prefix}_page",
        )
    )
    start = (page - 1) * page_size
    end = start + page_size
    return df.iloc[start:end], page, total_pages


def _latest_update_label(df: pd.DataFrame) -> str:
    if df.empty or "_analysis_mtime" not in df.columns:
        return "N/A"

    latest_ts = pd.to_numeric(df["_analysis_mtime"], errors="coerce").max()
    if pd.isna(latest_ts):
        return "N/A"

    return datetime.fromtimestamp(float(latest_ts)).strftime("%d %b %Y")


def _format_quote_blocks(text: str) -> str:
    """Convert explicit quote labels into cleaner markdown blocks."""
    text = _clean_text(text)

    def replace_double(match):
        label = match.group(1).title()
        quote = match.group(2).strip()
        return f"\n\n**{label}**\n> {quote}\n"

    def replace_single(match):
        label = match.group(1).title()
        quote = match.group(2).strip()
        return f"\n\n**{label}**\n> {quote}\n"

    text = _re.sub(r"\(\s*(Quote|Quotes|Pipeline)\s*:\s*", r"\n\n\1: ", text, flags=_re.IGNORECASE)
    text = _re.sub(r'(?i)\b(Quote|Quotes|Pipeline)\b\s*:\s*"([^"]{5,}?)"', replace_double, text)
    text = _re.sub(r"(?i)\b(Quote|Quotes|Pipeline)\b\s*:\s*'([^']{5,}?)'", replace_single, text)
    text = _re.sub(r'(?i)\b(Quote|Quotes|Pipeline)\b\s+"([^"]{5,}?)"', replace_double, text)
    text = _re.sub(r"(?i)\b(Quote|Quotes|Pipeline)\b\s+'([^']{5,}?)'", replace_single, text)

    leading_q = _re.match(r'^["\u201c]([^"\u201d]{10,})["\u201d]\s*(.*)', text, _re.DOTALL)
    if leading_q:
        quoted = leading_q.group(1).strip()
        trailing = leading_q.group(2).strip()
        if trailing:
            return f"> {quoted}\n\n{trailing}"
        return f"> {quoted}"

    if text.startswith("'") and text.endswith("'") and len(text) > 10 and text.count("'") == 2:
        return f"> {text[1:-1]}"

    return text.strip()


def _format_item(text: str) -> str:
    """Bold descriptor labels and keep quotes readable."""
    text = _clean_text(text)
    if _is_not_disclosed(text):
        return "_Not disclosed_"

    prefix = ""
    indent = ""
    bullet_match = _re.match(r"^((?:[-*\u2022])\s+|\d{1,2}[\.\)]\s+)", text)
    if bullet_match:
        prefix = bullet_match.group(1)
        indent = " " * len(prefix)
        text = text[bullet_match.end():].strip()

    if text.endswith(":") and not _re.search(r"[.!?]", text[:-1]):
        return f"{prefix}**{text[:-1].strip()}**"

    colon = text.find(": ")
    if 0 < colon < 80 and not _re.search(r"[.!?]", text[:colon]):
        label = text[:colon].strip()
        raw_rest = text[colon + 2:].strip()

        if _re.search(r"\bquotes?\b|\bpipeline\b", label.lower()):
            all_quotes = _re.findall(r'["\u201c]([^"\u201d]{5,})["\u201d]', raw_rest)
            if all_quotes:
                parts = [f"{indent}> {q.strip()}" for q in all_quotes]
                return f"{prefix}**{label}**\n" + "\n\n".join(parts)
            return f"{prefix}**{label}**\n{indent}> {raw_rest}"

        rest = _format_quote_blocks(raw_rest) or "_Not disclosed_"
        if indent and rest.startswith(">"):
            rest = f"{indent}{rest}"
        return f"{prefix}**{label}**\n{rest}"

    formatted = _format_quote_blocks(text)
    if prefix and formatted.startswith(">"):
        fallback_label = text.split(":")[0].strip() if ":" in text else text[:40].rstrip()
        return f"{prefix}**{fallback_label}**\n{indent}{formatted}"
    return f"{prefix}{formatted}" if prefix else formatted


def _parse_items_safe(text: str) -> list[str]:
    """Parse display items without treating arbitrary sentence numbers as list markers."""
    text = _clean_text(text)
    if not text:
        return []

    blocks = [block.strip() for block in _re.split(r"\n\s*\n", text) if block.strip()]
    if len(blocks) > 1:
        def is_short_block(block: str) -> bool:
            words = block.split()
            return len(words) <= 3 and len(block) <= 24 and not _re.search(r"[.:;!?]", block)

        merged_blocks = []
        pending = []
        i = 0
        while i < len(blocks):
            block = blocks[i]
            lower = block.lower()

            if lower in {"quote", "quotes", "pipeline"} and i + 1 < len(blocks):
                if pending:
                    merged_blocks.append(" ".join(pending).strip())
                    pending = []
                merged_blocks.append(f"{block}: {blocks[i + 1]}")
                i += 2
                continue

            if is_short_block(block):
                pending.append(block)
                i += 1
                continue

            if pending:
                merged_blocks.append(" ".join(pending + [block]).strip())
                pending = []
            else:
                merged_blocks.append(block)
            i += 1

        if pending:
            merged_blocks.append(" ".join(pending).strip())

        if len(merged_blocks) > 1:
            return merged_blocks

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) > 1:
        items = []
        current = []
        for line in lines:
            starts_new = bool(
                _re.match(r"^((?:[-*\u2022])|\d{1,2}[\.\)])\s+", line)
                or _re.match(r"^[A-Z][^:]{1,70}:\s", line)
            )
            if current and starts_new:
                items.append(" ".join(current).strip())
                current = [line]
            else:
                current.append(line)
        if current:
            items.append(" ".join(current).strip())
        if len(items) > 1:
            return items

    if " | " in text:
        parts = [part.strip() for part in text.split(" | ") if part.strip()]
        if len(parts) > 1:
            return parts

    candidate_numbered = [part.strip() for part in _re.split(r"(?<!\w)(?=\d{1,2}[\.\)]\s)", text) if part.strip()]
    has_leading_text = False
    numbered_values = []
    normalized_parts = []

    for idx, part in enumerate(candidate_numbered):
        match = _re.match(r"^(\d{1,2})[\.\)]\s+", part)
        if not match:
            if idx == 0:
                has_leading_text = True
                normalized_parts.append(part)
            elif normalized_parts:
                normalized_parts[-1] = f"{normalized_parts[-1]} {part}".strip()
            else:
                normalized_parts.append(part)
            continue

        number = int(match.group(1))
        if not numbered_values or number == numbered_values[-1] + 1:
            normalized_parts.append(part)
            numbered_values.append(number)
        elif normalized_parts:
            normalized_parts[-1] = f"{normalized_parts[-1]} {part}".strip()
        else:
            normalized_parts.append(part)

    if (
        len(numbered_values) >= 2
        and (
            numbered_values[0] == 1
            or (has_leading_text and numbered_values[0] == 2)
        )
        and all(curr == prev + 1 for prev, curr in zip(numbered_values, numbered_values[1:]))
    ):
        if has_leading_text and numbered_values[0] == 2:
            return [f"1. {normalized_parts[0]}"] + normalized_parts[1:]
        return normalized_parts

    positions = [
        m.end(1)
        for m in _re.finditer(
            r"([.!?]['\"\u2019]?\s+)(?=[A-Z][A-Za-z0-9/&'()%-]{1,25}(?:\s[A-Za-z0-9/&'()%-]{1,25}){0,7}:\s)",
            text,
        )
    ]
    if positions:
        parts = []
        start = 0
        for pos in positions:
            part = text[start:pos].strip()
            if part:
                parts.append(part)
            start = pos
        last = text[start:].strip()
        if last:
            parts.append(last)
        if len(parts) > 1:
            return parts

    return [text]


def _format_as_markdown(value) -> str:
    items = _parse_items_safe(_clean_text(value))
    if not items:
        return "_Not available_"
    return "\n\n".join(_format_item(item) for item in items)


def _render_section(key: str, value) -> None:
    """Render a single analysis section with appropriate formatting."""
    if value is None or value == "" or value == "N/A":
        st.caption("_Not available_")
        return

    if key == "analyst_take":
        if isinstance(value, dict):
            bull = value.get("bull_case", "")
            bear = value.get("bear_case", "")
            monitorables = value.get("monitorables", "")
            if bull:
                st.markdown("**Bull Case**")
                st.success(_format_as_markdown(bull))
            if bear:
                st.markdown("**Bear Case**")
                st.error(_format_as_markdown(bear))
            if monitorables:
                st.markdown("**Monitorables**")
                st.info(_format_as_markdown(monitorables))
        else:
            st.markdown(_format_as_markdown(value))
        return

    if key == "key_quotes":
        quotes = _normalize_key_quotes(value)
        if not quotes:
            st.caption("_Not available_")
            return
        for i, quote in enumerate(quotes, 1):
            st.markdown(f"**Quote {i}**\n> {quote}")
        return

    if key == "red_flags":
        text = _clean_text(value)
        if not _is_not_disclosed(text):
            st.warning(_format_as_markdown(text))
        else:
            st.caption("_Not disclosed_")
        return

    if _is_not_disclosed(value):
        st.caption("_Not disclosed_")
        return
    st.markdown(_format_as_markdown(value))


def _render_record_details(record: dict, key_prefix: str) -> None:
    if record.get("_load_error"):
        st.error(
            f"Could not load analysis for {record['company_name']} ({record['_ticker_folder']}) "
            f"- {record['_quarter_label']}."
        )
        st.caption(record["_load_error"])
        return

    company = record["company_name"]
    ticker = record["_ticker_folder"]
    quarter = record["_quarter_label"]
    period = record["_period_folder"]

    st.subheader(f"{company} ({ticker})")
    meta_cols = st.columns(5)
    meta_cols[0].metric("Quarter", quarter)
    meta_cols[1].metric("Period", period)
    meta_cols[2].metric("Sector", record.get("sector", "Unknown"))
    meta_cols[3].metric("Sub-sector", record.get("sub_sector", "Unknown"))
    meta_cols[4].metric("Updated", _latest_update_label(pd.DataFrame([record])))

    group_name = st.radio(
        "Detail group",
        list(SECTION_GROUPS.keys()),
        horizontal=True,
        key=f"{key_prefix}_group",
    )

    section_keys = SECTION_GROUPS[group_name]
    for idx, section_key in enumerate(section_keys):
        with st.expander(
            SECTION_LABELS.get(section_key, section_key),
            expanded=idx == 0,
        ):
            _render_section(section_key, record.get(section_key))


def _render_single_company_multi_quarter(df: pd.DataFrame) -> None:
    company = df["company_name"].iloc[0]
    ticker = df["_ticker_folder"].iloc[0]
    st.subheader(f"{company} ({ticker}) - Quarter Comparison")

    quarter_options = _sorted_quarter_labels(df)
    selected_quarters = st.multiselect(
        "Visible quarters",
        quarter_options,
        default=quarter_options,
        help="Only the selected quarters are loaded into the comparison grid.",
        key="single_company_visible_quarters",
    )

    if not selected_quarters:
        st.info("Select at least one quarter to compare.")
        return

    compare_index = df[df["_quarter_label"].isin(selected_quarters)]
    compare_index = compare_index.sort_values("_quarter_sort")

    with st.spinner("Loading selected quarters..."):
        compare_df = _materialize_rows(compare_index)

    if compare_df.empty:
        st.info("No analysis files could be loaded for the selected quarters.")
        return

    quarters = compare_df["_quarter_label"].tolist()
    for section_key in ANALYSIS_SECTIONS:
        label = SECTION_LABELS.get(section_key, section_key)
        with st.expander(label, expanded=False):
            cols = st.columns(len(quarters))
            for i, quarter in enumerate(quarters):
                row = compare_df.iloc[i]
                with cols[i]:
                    st.markdown(f"**{quarter}**")
                    _render_section(section_key, row.get(section_key))


def _render_record_sections(record: dict) -> None:
    for section_key in ANALYSIS_SECTIONS:
        label = SECTION_LABELS.get(section_key, section_key)
        st.markdown(f"**{label}**")
        _render_section(section_key, record.get(section_key))
        st.divider()


def _render_paginated_browser(
    df: pd.DataFrame,
    title: str,
    page_size: int,
    key_prefix: str,
    show_quarter_in_title: bool,
    default_expanded: bool,
) -> None:
    st.subheader(title)
    page_df, page_number, total_pages = _page_slice(df, page_size, key_prefix)
    st.caption(
        f"Page {page_number} of {total_pages}. The table is indexed data only; "
        "full analysis content loads for this page."
    )
    st.dataframe(_summary_frame(page_df), width="stretch")

    browse_mode = st.radio(
        "Browse mode",
        ["List view", "Focus view"],
        horizontal=True,
        key=f"{key_prefix}_browse_mode",
        help="List view restores the earlier expander workflow. Focus view loads one record at a time.",
    )

    if browse_mode == "Focus view":
        labels = [_record_label(row) for _, row in page_df.iterrows()]
        selected_label = st.selectbox(
            "Inspect result",
            labels,
            key=f"{key_prefix}_selected_record",
        )
        selected_row = page_df.iloc[labels.index(selected_label)]

        with st.spinner("Loading analysis details..."):
            record = _load_row_analysis(selected_row)
        _render_record_details(record, key_prefix=key_prefix)
        return

    with st.spinner("Loading analyses for this page..."):
        page_records = _materialize_rows(page_df)

    if page_records.empty:
        st.info("No analysis files could be loaded for this page.")
        return

    for _, row in page_records.iterrows():
        company = row["company_name"]
        ticker = row["_ticker_folder"]
        quarter = row["_quarter_label"]
        period = row["_period_folder"]
        expander_label = (
            f"{company} ({ticker}) - {quarter}"
            if show_quarter_in_title
            else f"{company} ({ticker})"
        )
        with st.expander(expander_label, expanded=default_expanded):
            if not show_quarter_in_title:
                st.caption(f"{quarter} | {period}")
            _render_record_sections(row)


def _render_multi_company_single_quarter(df: pd.DataFrame, page_size: int) -> None:
    quarter = df["_quarter_label"].iloc[0]
    _render_paginated_browser(
        df,
        title=f"Quarter: {quarter} - Company Comparison",
        page_size=page_size,
        key_prefix="company_comparison",
        show_quarter_in_title=False,
        default_expanded=True,
    )


def _render_flat_table(df: pd.DataFrame, page_size: int) -> None:
    _render_paginated_browser(
        df,
        title="All Results",
        page_size=page_size,
        key_prefix="all_results",
        show_quarter_in_title=True,
        default_expanded=False,
    )


def _period_sort_key(period_str) -> str:
    """Convert 'Feb 2026' to '2026-02' for chronological sorting."""
    if isinstance(period_str, pd.Series):
        return period_str.apply(_period_sort_key_scalar)
    return _period_sort_key_scalar(period_str)


def _period_sort_key_scalar(period_str: str) -> str:
    dt = _parse_period_date(period_str)
    return dt.strftime("%Y-%m") if dt else "0000-00"


def _parse_period_date(period_str: str):
    text = _clean_text(period_str)
    for fmt in ("%b %Y", "%B %Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _period_quarter_info(period_str: str):
    """Return (quarter, fiscal_year) for period labels using Indian FY buckets."""
    dt = _parse_period_date(period_str)
    if dt is None:
        return None

    month = dt.month
    if month in (7, 8, 9):
        return 1, dt.year + 1
    if month in (10, 11, 12):
        return 2, dt.year + 1
    if month in (1, 2, 3):
        return 3, dt.year
    return 4, dt.year


def _period_quarter_label(period_str: str) -> str:
    """Format a period folder name as a dashboard quarter label, e.g. Q3 FY26."""
    info = _period_quarter_info(period_str)
    if info is None:
        return _clean_text(period_str) or "Unknown Quarter"

    quarter, fiscal_year = info
    return f"Q{quarter} FY{fiscal_year % 100:02d}"


def _period_quarter_sort(period_str: str) -> int:
    """Return a sortable fiscal-quarter key where larger values are newer."""
    info = _period_quarter_info(period_str)
    if info is None:
        return 0

    quarter, fiscal_year = info
    return fiscal_year * 10 + quarter


def _sorted_quarter_labels(df: pd.DataFrame) -> list[str]:
    """Return unique dashboard quarter labels sorted newest first."""
    if df.empty:
        return []

    return (
        df[["_quarter_label", "_quarter_sort"]]
        .drop_duplicates()
        .sort_values("_quarter_sort", ascending=False)["_quarter_label"]
        .tolist()
    )


def _collapse_quarter_records(df: pd.DataFrame) -> pd.DataFrame:
    """
    Keep one row per ticker and fiscal quarter for model-free dashboard views.

    If multiple calendar months or analysis files map to the same displayed
    quarter, the most recent period and newest analysis file wins.
    """
    if df.empty:
        return df

    work = df.copy()
    period_starts = (
        work["_period_start"]
        if "_period_start" in work.columns
        else pd.Series([None] * len(work), index=work.index)
    )
    analysis_mtime = (
        work["_analysis_mtime"]
        if "_analysis_mtime" in work.columns
        else pd.Series([0] * len(work), index=work.index)
    )

    work["_quarter_record_order"] = period_starts.map(
        lambda value: value.toordinal() if value else 0
    )
    work["_analysis_order"] = pd.to_numeric(analysis_mtime, errors="coerce").fillna(0)

    work = work.sort_values(
        [
            "_ticker_folder",
            "_quarter_label",
            "_quarter_record_order",
            "_analysis_order",
        ],
        ascending=[True, True, False, False],
    )
    work = work.drop_duplicates(["_ticker_folder", "_quarter_label"], keep="first")
    return work.drop(columns=["_quarter_record_order", "_analysis_order"])


def _period_month_start(period_str: str):
    dt = _parse_period_date(period_str)
    return dt.date() if dt else None


def _period_month_end(period_str: str):
    start = _period_month_start(period_str)
    if start is None:
        return None

    if start.month == 12:
        next_month = start.replace(year=start.year + 1, month=1)
    else:
        next_month = start.replace(month=start.month + 1)
    return next_month - timedelta(days=1)


def _normalize_date_bounds(start, end):
    if start > end:
        start, end = end, start
    return start, end


def main():
    st.set_page_config(
        page_title="Concall Analyzer",
        page_icon="CA",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _inject_styles()

    st.title("Concall Result Analyzer")
    st.caption(
        "The app now indexes analysis files first and loads full JSON content only "
        "for the result you inspect or compare."
    )

    cwd = os.path.dirname(os.path.abspath(__file__))
    output_root = os.path.join(cwd, "Outputs", "Concalls")
    csv_path = os.path.join(cwd, "tickers.csv")

    with st.sidebar:
        st.header("Filters")
        if st.button("Refresh data", width="stretch"):
            st.cache_data.clear()
            st.rerun()
        st.caption("Use search, filters, and pagination to keep the view focused.")

    with st.spinner("Indexing available analyses..."):
        ticker_meta = load_ticker_metadata(csv_path)
        df = load_analysis_index(output_root, ticker_meta)

    if df.empty:
        st.warning(
            "No analyzed transcripts found. Run the pipeline first:\n\n"
            "```\npython main.py --phase all\n```"
        )
        return

    df = _with_period_columns(df)

    with st.sidebar:
        if ENABLE_SECTOR_FILTERS:
            sectors = sorted(df["sector"].dropna().unique().tolist())
            selected_sectors = st.multiselect("Sector", sectors, default=sectors)
            df_sector_scope = df[df["sector"].isin(selected_sectors)]

            sub_sectors = sorted(df_sector_scope["sub_sector"].dropna().unique().tolist())
            selected_sub_sectors = st.multiselect("Sub-sector", sub_sectors, default=sub_sectors)
            df_scope = df_sector_scope[df_sector_scope["sub_sector"].isin(selected_sub_sectors)]
        else:
            df_scope = df

        valid_period_df = df_scope.dropna(subset=["_period_start", "_period_end"])
        if valid_period_df.empty:
            df_date_scope = df_scope
            st.caption("Date range filter unavailable because period folders could not be parsed.")
        else:
            min_period_date = min(valid_period_df["_period_start"])
            max_period_date = max(valid_period_df["_period_end"])
            range_start = st.date_input(
                "Start date",
                value=min_period_date,
                help="Matches companies with at least one concall month in this range.",
            )
            range_end = st.date_input(
                "End date",
                value=max_period_date,
                help="All available quarters remain visible for matching companies.",
            )
            range_start, range_end = _normalize_date_bounds(range_start, range_end)
            range_mask = (
                (valid_period_df["_period_start"] <= range_end)
                & (valid_period_df["_period_end"] >= range_start)
            )
            matched_tickers = set(valid_period_df.loc[range_mask, "_ticker_folder"])
            df_date_scope = df_scope[df_scope["_ticker_folder"].isin(matched_tickers)]
            st.caption(
                f"{df_date_scope['_ticker_folder'].nunique()} company(ies) matched the date range."
            )

        search_term = _clean_text(
            st.text_input(
                "Search company or ticker",
                placeholder="Type part of a company name or ticker",
            )
        )
        if search_term:
            company_mask = df_date_scope["company_name"].str.contains(search_term, case=False, na=False)
            ticker_mask = df_date_scope["_ticker_folder"].str.contains(search_term, case=False, na=False)
            df_date_scope = df_date_scope[company_mask | ticker_mask]

        companies = sorted(df_date_scope["company_name"].unique().tolist())
        selected_companies = st.multiselect("Company", companies, default=companies)
        df_filtered = df_date_scope[df_date_scope["company_name"].isin(selected_companies)]

        quarters = _sorted_quarter_labels(df_filtered)
        selected_quarters = st.multiselect("Quarter", quarters, default=quarters)
        df_filtered = df_filtered[df_filtered["_quarter_label"].isin(selected_quarters)]

        df_filtered = _collapse_quarter_records(df_filtered)

        latest_only = st.checkbox("Only latest quarter per company", value=False)
        if latest_only:
            df_filtered = _latest_record_per_company(df_filtered)

        sort_order = st.selectbox("Sort results", RESULT_SORT_OPTIONS, index=0)
        page_size = st.selectbox(
            "Results per page",
            PAGE_SIZE_OPTIONS,
            index=PAGE_SIZE_OPTIONS.index(DEFAULT_PAGE_SIZE),
        )

    if df_filtered.empty:
        st.info("No data matches the current filters.")
        return

    df_filtered = _sort_results(df_filtered, sort_order)

    n_results = len(df_filtered)
    n_companies = df_filtered["company_name"].nunique()
    n_quarters = df_filtered["_quarter_label"].nunique()
    latest_update = _latest_update_label(df_filtered)

    metric_cols = st.columns(4)
    metric_cols[0].metric("Results", f"{n_results}")
    metric_cols[1].metric("Companies", f"{n_companies}")
    metric_cols[2].metric("Quarters", f"{n_quarters}")
    metric_cols[3].metric("Latest update", latest_update)
    st.caption(
        "Quarter comparison appears when one company and multiple quarters are selected."
    )

    if n_companies == 1 and n_quarters > 1:
        _render_single_company_multi_quarter(df_filtered)
    elif n_companies > 1 and n_quarters == 1:
        _render_multi_company_single_quarter(df_filtered, page_size)
    else:
        _render_flat_table(df_filtered, page_size)


if __name__ == "__main__":
    main()
