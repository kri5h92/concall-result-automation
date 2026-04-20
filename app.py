"""
Concall Result Automation — Streamlit Viewer

Interactive dashboard to explore analyzed earnings call transcripts.
Supports filtering by sector, sub-sector, company, and quarter.

Run with:
    streamlit run app.py
"""

import os
import json
import csv
import re as _re

import pandas as pd
import streamlit as st


# -----------------------------------
# DATA LOADING
# -----------------------------------

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
    "capacity_capex": "Capacity & Capex",
    "margins_commentary": "Margins Commentary",
    "order_book_demand": "Order Book / Demand",
    "red_flags": "Red Flags",
    "quarter_change": "Change vs Previous Quarter",
    "key_quotes": "Key Quotes",
    "analyst_take": "Analyst Take",
}

NOT_DISCLOSED_VALUES = {
    "",
    "n/a",
    "na",
    "none",
    "not available",
    "not disclosed",
}


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
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0
    return mtime, os.path.basename(path)


@st.cache_data
def load_ticker_metadata(csv_path: str) -> dict[str, dict]:
    """Load tickers.csv into a dict: {ticker: {company_name, sector, sub_sector}}."""
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


def load_all_analyses(output_root: str, ticker_meta: dict[str, dict]) -> pd.DataFrame:
    """
    Walk Outputs/Concalls/ and load all analysis_*.json files into a DataFrame.
    Also loads legacy analysis.json files.
    Merges sector/sub_sector from ticker metadata.
    """
    records = []

    if not os.path.isdir(output_root):
        return pd.DataFrame()

    for ticker_name in os.listdir(output_root):
        ticker_dir = os.path.join(output_root, ticker_name)
        if not os.path.isdir(ticker_dir):
            continue

        for period_name in os.listdir(ticker_dir):
            period_path = os.path.join(ticker_dir, period_name)
            if not os.path.isdir(period_path):
                continue

            analysis_paths = []
            for fname in os.listdir(period_path):
                if fname == "analysis.json" or (
                    fname.startswith("analysis_") and fname.endswith(".json")
                ):
                    analysis_paths.append(os.path.join(period_path, fname))

            if not analysis_paths:
                continue

            data = None
            selected_json_path = None
            for json_path in sorted(analysis_paths, key=_analysis_file_sort_key, reverse=True):
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except (json.JSONDecodeError, OSError):
                    continue
                selected_json_path = json_path
                break

            if data is None or selected_json_path is None:
                continue

            data = _normalize_analysis_record(data)

            # Convert key_quotes list to bullet points for display
            kq = data.get("key_quotes", [])
            if isinstance(kq, list):
                data["key_quotes"] = kq  # keep as list; rendered by _render_section

            # analyst_take stays as dict if returned that way

            # Add metadata
            meta = ticker_meta.get(ticker_name, {})
            data["company_name"] = _canonical_company_name(ticker_name, data, meta)
            data["sector"] = meta.get("sector", "Unknown")
            data["sub_sector"] = meta.get("sub_sector", "Unknown")
            data["_ticker_folder"] = ticker_name
            data["_period_folder"] = period_name
            data["_analysis_mtime"] = _analysis_file_sort_key(selected_json_path)[0]

            records.append(data)

    if not records:
        return pd.DataFrame()

    return pd.DataFrame(records)


# -----------------------------------
# APP
# -----------------------------------

def main():
    st.set_page_config(
        page_title="Concall Analyzer",
        page_icon="📊",
        layout="wide",
    )

    st.title("📊 Concall Result Analyzer")

    # Paths
    cwd = os.path.dirname(os.path.abspath(__file__))
    output_root = os.path.join(cwd, "Outputs", "Concalls")
    csv_path = os.path.join(cwd, "tickers.csv")

    # Sidebar controls
    with st.sidebar:
        st.header("Filters")

        if st.button("🔄 Refresh Data"):
            st.cache_data.clear()

    # Load data
    ticker_meta = load_ticker_metadata(csv_path)
    df = load_all_analyses(output_root, ticker_meta)

    if df.empty:
        st.warning(
            "No analyzed transcripts found. Run the pipeline first:\n\n"
            "```\npython main.py --phase all\n```"
        )
        return

    df["_period_start"] = df["_period_folder"].map(_period_month_start)
    df["_period_end"] = df["_period_folder"].map(_period_month_end)
    df["_quarter_label"] = df["_period_folder"].map(_period_quarter_label)
    df["_quarter_sort"] = df["_period_folder"].map(_period_quarter_sort)

    # --- SIDEBAR FILTERS ---
    with st.sidebar:
        # Sector filter
        # sectors = sorted(df["sector"].unique())
        # selected_sectors = st.multiselect("Sector", sectors, default=sectors)

        # df_filtered = df[df["sector"].isin(selected_sectors)]

        # # Sub-sector filter
        # sub_sectors = sorted(df_filtered["sub_sector"].unique())
        # selected_sub_sectors = st.multiselect("Sub-Sector", sub_sectors, default=sub_sectors)

        # df_filtered = df_filtered[df_filtered["sub_sector"].isin(selected_sub_sectors)]

        # Date range filter: find companies with any concall month overlapping the range.
        # Once matched, keep all available quarters/files for those companies visible.
        valid_period_df = df.dropna(subset=["_period_start", "_period_end"])
        if valid_period_df.empty:
            df_date_scope = df
            st.caption("Date range filter unavailable because period folders could not be parsed.")
        else:
            min_period_date = min(valid_period_df["_period_start"])
            max_period_date = max(valid_period_df["_period_end"])
            range_start = st.date_input(
                "Start date",
                value=min_period_date,
                help=(
                    "Matches companies with at least one concall month overlapping this range."
                ),
            )
            range_end = st.date_input(
                "End date",
                value=max_period_date,
                help=(
                    "The range selects companies only; all available quarters for matched companies are shown."
                ),
            )
            range_start, range_end = _normalize_date_bounds(range_start, range_end)
            range_mask = (
                (valid_period_df["_period_start"] <= range_end)
                & (valid_period_df["_period_end"] >= range_start)
            )
            matched_tickers = set(valid_period_df.loc[range_mask, "_ticker_folder"])
            df_date_scope = df[df["_ticker_folder"].isin(matched_tickers)]
            st.caption(
                f"{df_date_scope['_ticker_folder'].nunique()} company(ies) matched; "
                "showing all available quarters for selected companies."
            )

        # Company filter
        companies = sorted(df_date_scope["company_name"].unique())
        selected_companies = st.multiselect("Company", companies, default=companies)

        df_filtered = df_date_scope[df_date_scope["company_name"].isin(selected_companies)]

        # Quarter filter
        quarters = _sorted_quarter_labels(df_filtered)
        selected_quarters = st.multiselect("Quarter", quarters, default=quarters)

        df_filtered = df_filtered[df_filtered["_quarter_label"].isin(selected_quarters)]
        df_filtered = _collapse_quarter_records(df_filtered)

    if df_filtered.empty:
        st.info("No data matches the current filters.")
        return

    n_companies = df_filtered["company_name"].nunique()
    n_quarters = df_filtered["_quarter_label"].nunique()

    st.caption(
        f"Showing {len(df_filtered)} result(s) — "
        f"{n_companies} company(ies) × {n_quarters} quarter(s)"
    )

    # --- VIEW MODES ---
    if n_companies == 1 and n_quarters > 1:
        _render_single_company_multi_quarter(df_filtered)
    elif n_companies > 1 and n_quarters == 1:
        _render_multi_company_single_quarter(df_filtered)
    else:
        _render_flat_table(df_filtered)


# -----------------------------------
# VIEW RENDERERS
# -----------------------------------



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

    # "long quote" optionally followed by trailing prose
    leading_q = _re.match(r'^["\u201c]([^"\u201d]{10,})["\u201d]\s*(.*)', text, _re.DOTALL)
    if leading_q:
        quoted = leading_q.group(1).strip()
        trailing = leading_q.group(2).strip()
        if trailing:
            return f"> {quoted}\n\n{trailing}"
        return f"> {quoted}"

    if text.startswith("'") and text.endswith("'") and len(text) > 10:
        if text.count("'") == 2:
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
        indent = " " * len(prefix)  # indent continuation lines under the list marker
        text = text[bullet_match.end():].strip()

    if text.endswith(":") and not _re.search(r"[.!?]", text[:-1]):
        return f"{prefix}**{text[:-1].strip()}**"

    colon = text.find(": ")
    if 0 < colon < 80 and not _re.search(r"[.!?]", text[:colon]):
        label = text[:colon].strip()
        raw_rest = text[colon + 2:].strip()

        # Special handling for Quote:/Quotes:/Pipeline: labels —
        # extract ALL quoted strings and render each as its own blockquote.
        if _re.search(r"\bquotes?\b|\bpipeline\b", label.lower()):
            all_quotes = _re.findall(r'["\u201c]([^"\u201d]{5,})["\u201d]', raw_rest)
            if all_quotes:
                parts = [f"{indent}> {q.strip()}" for q in all_quotes]
                return f"{prefix}**{label}**\n" + "\n\n".join(parts)
            return f"{prefix}**{label}**\n{indent}> {raw_rest}"

        rest = _format_quote_blocks(raw_rest) or "_Not disclosed_"
        # indent blockquote lines so they sit under the list marker
        if indent and rest.startswith(">"):
            rest = f"{indent}{rest}"
        return f"{prefix}**{label}**\n{rest}"

    formatted = _format_quote_blocks(text)
    if prefix and formatted.startswith(">"):
        return f"{prefix}**{text.split(':')[0].strip() if ':' in text else text[:40].rstrip()}**\n{indent}{formatted}"
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

    # analyst_take: structured sub-sections
    if key == "analyst_take":
        if isinstance(value, dict):
            bull = value.get("bull_case", "")
            bear = value.get("bear_case", "")
            mono = value.get("monitorables", "")
            if bull:
                st.markdown("**🟢 Bull Case**")
                st.success(_format_as_markdown(bull))
            if bear:
                st.markdown("**🔴 Bear Case**")
                st.error(_format_as_markdown(bear))
            if mono:
                st.markdown("**👁 Monitorables**")
                st.info(_format_as_markdown(mono))
        else:
            st.markdown(_format_as_markdown(value))
        return

    # key_quotes: numbered list
    if key == "key_quotes":
        quotes = _normalize_key_quotes(value)
        if not quotes:
            st.caption("_Not available_")
            return
        for i, quote in enumerate(quotes, 1):
            st.markdown(f"**Quote {i}**\n> {quote}")
        return

    # red_flags: highlight box if content present and not "Not disclosed"
    if key == "red_flags":
        text = _clean_text(value)
        if not _is_not_disclosed(text):
            st.warning(_format_as_markdown(text))
        else:
            st.caption("_Not disclosed_")
        return

    # Default: detect + format lists, then render as markdown
    if _is_not_disclosed(value):
        st.caption("_Not disclosed_")
        return
    st.markdown(_format_as_markdown(value))


def _render_single_company_multi_quarter(df: pd.DataFrame):
    """Single company selected, multiple quarters: columns = quarters, rows = sections."""
    company = df["company_name"].iloc[0]
    ticker = df["_ticker_folder"].iloc[0]
    st.subheader(f"{company} ({ticker}) — Quarter Comparison")

    df = df.sort_values("_quarter_sort")
    quarters = df["_quarter_label"].unique().tolist()

    for section_key in ANALYSIS_SECTIONS:
        label = SECTION_LABELS.get(section_key, section_key)
        with st.expander(label, expanded=False):
            cols = st.columns(len(quarters))
            for i, quarter in enumerate(quarters):
                rows = df[df["_quarter_label"] == quarter]
                row = rows.iloc[0]
                with cols[i]:
                    st.markdown(f"**{quarter}**")
                    _render_section(section_key, row.get(section_key))


def _render_multi_company_single_quarter(df: pd.DataFrame):
    """Multiple companies, single quarter: one row per company."""
    quarter = df["_quarter_label"].iloc[0]
    st.subheader(f"Quarter: {quarter} — Company Comparison")

    for _, row in df.sort_values("company_name").iterrows():
        company = row["company_name"]
        ticker = row["_ticker_folder"]
        with st.expander(f"{company} ({ticker})", expanded=True):
            for section_key in ANALYSIS_SECTIONS:
                label = SECTION_LABELS.get(section_key, section_key)
                st.markdown(f"**{label}**")
                _render_section(section_key, row.get(section_key))
                st.divider()


def _render_flat_table(df: pd.DataFrame):
    """General view: one expander per company+quarter combination."""
    st.subheader("All Results")

    df = df.sort_values(["company_name", "_quarter_sort"], ascending=[True, False])

    for _, row in df.iterrows():
        company = row["company_name"]
        ticker = row["_ticker_folder"]
        quarter = row["_quarter_label"]

        with st.expander(f"{company} ({ticker}) — {quarter}", expanded=False):
            for section_key in ANALYSIS_SECTIONS:
                label = SECTION_LABELS.get(section_key, section_key)
                st.markdown(f"**{label}**")
                _render_section(section_key, row.get(section_key))
                st.divider()


# -----------------------------------
# HELPERS
# -----------------------------------

def _period_sort_key(period_str) -> str:
    """Convert 'Feb 2026' to '2026-02' for chronological sorting."""
    if isinstance(period_str, pd.Series):
        return period_str.apply(_period_sort_key_scalar)
    return _period_sort_key_scalar(period_str)


def _period_sort_key_scalar(period_str: str) -> str:
    dt = _parse_period_date(period_str)
    return dt.strftime("%Y-%m") if dt else "0000-00"


def _parse_period_date(period_str: str):
    from datetime import datetime

    text = _clean_text(period_str)
    for fmt in ("%b %Y", "%B %Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _period_quarter_info(period_str: str):
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
    info = _period_quarter_info(period_str)
    if info is None:
        return _clean_text(period_str) or "Unknown Quarter"

    quarter, fiscal_year = info
    return f"Q{quarter} FY{fiscal_year % 100:02d}"


def _period_quarter_sort(period_str: str) -> int:
    info = _period_quarter_info(period_str)
    if info is None:
        return 0

    quarter, fiscal_year = info
    return fiscal_year * 10 + quarter


def _sorted_quarter_labels(df: pd.DataFrame) -> list[str]:
    if df.empty:
        return []

    return (
        df[["_quarter_label", "_quarter_sort"]]
        .drop_duplicates()
        .sort_values("_quarter_sort", ascending=False)["_quarter_label"]
        .tolist()
    )


def _collapse_quarter_records(df: pd.DataFrame) -> pd.DataFrame:
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
    from datetime import datetime, timedelta
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


# -----------------------------------
# ENTRY
# -----------------------------------

if __name__ == "__main__":
    main()
