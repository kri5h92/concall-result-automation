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
    Also loads legacy analysis.json files (tagged model='unknown').
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

            # Collect all analysis JSON files in this folder
            json_files = []
            for fname in os.listdir(period_path):
                if fname == "analysis.json":
                    # Legacy file — model unknown
                    json_files.append((os.path.join(period_path, fname), "unknown"))
                elif fname.startswith("analysis_") and fname.endswith(".json"):
                    # Model-specific file — extract slug from filename
                    model_slug = fname[len("analysis_"):-len(".json")]
                    json_files.append((os.path.join(period_path, fname), model_slug))

            for json_path, model_slug in json_files:
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except (json.JSONDecodeError, OSError):
                    continue

                data = _normalize_analysis_record(data)

                # Convert key_quotes list to bullet points for display
                kq = data.get("key_quotes", [])
                if isinstance(kq, list):
                    data["key_quotes"] = kq  # keep as list; rendered by _render_section

                # analyst_take stays as dict if returned that way

                # Add metadata
                meta = ticker_meta.get(ticker_name, {})
                data["sector"] = meta.get("sector", "Unknown")
                data["sub_sector"] = meta.get("sub_sector", "Unknown")
                data["_ticker_folder"] = ticker_name
                data["_period_folder"] = period_name
                data["_model"] = model_slug

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

        # Company filter
        companies = sorted(df["company_name"].unique())
        selected_companies = st.multiselect("Company", companies, default=companies)

        df_filtered = df[df["company_name"].isin(selected_companies)]

        # Quarter filter
        periods = sorted(df_filtered["_period_folder"].unique(), key=_period_sort_key, reverse=True)
        selected_periods = st.multiselect("Quarter", periods, default=periods)

        df_filtered = df_filtered[df_filtered["_period_folder"].isin(selected_periods)]

        # Model filter
        available_models = sorted(df_filtered["_model"].unique())
        selected_models = st.multiselect("Model", available_models, default=available_models)

        df_filtered = df_filtered[df_filtered["_model"].isin(selected_models)]

    if df_filtered.empty:
        st.info("No data matches the current filters.")
        return

    n_companies = df_filtered["company_name"].nunique()
    n_periods = df_filtered["_period_folder"].nunique()
    n_models = df_filtered["_model"].nunique()

    st.caption(f"Showing {len(df_filtered)} result(s) — {n_companies} company(ies) × {n_periods} quarter(s) × {n_models} model(s)")

    # --- VIEW MODES ---
    if n_companies == 1 and n_periods == 1 and n_models > 1:
        # Best case for model comparison
        _render_model_comparison(df_filtered)
    elif n_companies == 1 and n_periods > 1:
        _render_single_company_multi_quarter(df_filtered)
    elif n_companies > 1 and n_periods == 1:
        _render_multi_company_single_quarter(df_filtered)
    else:
        _render_flat_table(df_filtered)


# -----------------------------------
# VIEW RENDERERS
# -----------------------------------


def _parse_items(text: str) -> list[str]:
    """Split a text blob into individual label-value items."""
    text = text.strip()

    # Already newline-separated
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) > 1:
        return lines

    # Pipe-separated items (most recent model format): "Label: 'quote' | Label: 'quote'"
    if " | " in text:
        parts = [p.strip() for p in text.split(" | ") if p.strip()]
        if len(parts) > 1:
            return parts

    # Numbered items inline: "1. content 2. content" — max 2 digits to avoid matching "INR 500. "
    parts = _re.split(r'(?<!\w)(\d{1,2}[\.\)]\s)', text)
    if len(parts) > 3:
        items = []
        i = 1
        while i < len(parts) - 1:
            content = (parts[i] + parts[i + 1]).strip()
            if content:
                items.append(content)
            i += 2
        if items:
            return items

    # Non-numbered: split after a closing " before a Capital word
    #               OR after sentence ". " before a Capital-starting "Label:"
    items = _re.split(
        r'(?<=["\u201d])\s+(?=[A-Z])'
        r'|(?<=\.)\s+(?=[A-Z][^:.\n]{2,60}:)',
        text,
    )
    items = [i.strip() for i in items if i.strip()]
    return items if len(items) > 1 else [text]


def _format_item(text: str) -> str:
    """Bold descriptor label before ':', render direct quotes as blockquotes."""
    text = text.strip()

    # Optional leading number "1. " / "1) "
    num_prefix = ""
    m_num = _re.match(r'^(\d+[\.\)]\s*)', text)
    if m_num:
        num_prefix = m_num.group(1)
        text = text[m_num.end():]

    # Find label — text before first ": " within 70 chars, no sentence-ending punctuation
    colon = text.find(": ")
    if 0 < colon < 70 and not _re.search(r'[.!?]', text[:colon]):
        label = text[:colon].strip()
        rest = text[colon + 2:].strip()
        # Entire rest is a single-quoted verbatim passage → blockquote
        if rest.startswith("'") and rest.endswith("'") and len(rest) > 15:
            rest_fmt = f"> {rest[1:-1]}"
        else:
            # Inline double-quoted text (≥5 chars) → blockquote
            rest_fmt = _re.sub(r'"([^"]{5,}?)"', r'\n> "\1"\n', rest).strip()
        return f"**{num_prefix}{label}**\n{rest_fmt}"

    return f"{num_prefix}{text}" if num_prefix else text


def _format_as_list(text: str) -> str:
    """Backward-compatible wrapper for older call sites."""
    return _format_as_markdown(text)


def _parse_items(text: str) -> list[str]:
    """Split a text blob into readable display items."""
    text = _clean_text(text)
    if not text:
        return []

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) > 1:
        items = []
        current = []
        for line in lines:
            starts_new = bool(
                _re.match(r"^([-*•]|\d{1,2}[\.\)])\s+", line)
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

    numbered = [part.strip() for part in _re.split(r"(?<!\w)(?=\d{1,2}[\.\)]\s)", text) if part.strip()]
    if len(numbered) > 1:
        return numbered

    positions = [
        match.start()
        for match in _re.finditer(
            r"(?<!^)(?<!\w)(?=(?:[A-Z][A-Za-z0-9/&'()%-]{1,20}(?: [A-Za-z0-9/&'()%-]{1,20}){0,4}):\s)",
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

    if text.startswith('"') and text.endswith('"') and len(text) > 10:
        return f"> {text[1:-1]}"
    if text.startswith("'") and text.endswith("'") and len(text) > 10:
        return f"> {text[1:-1]}"

    return text.strip()


def _format_item(text: str) -> str:
    """Bold descriptor labels and keep quotes readable."""
    text = _clean_text(text)
    if _is_not_disclosed(text):
        return "_Not disclosed_"

    prefix = ""
    bullet_match = _re.match(r"^((?:[-*\u2022])\s+|\d{1,2}[\.\)]\s+)", text)
    if bullet_match:
        prefix = bullet_match.group(1)
        text = text[bullet_match.end():].strip()

    if text.endswith(":") and not _re.search(r"[.!?]", text[:-1]):
        return f"**{prefix}{text[:-1].strip()}**" if prefix else f"**{text[:-1].strip()}**"

    colon = text.find(": ")
    if 0 < colon < 80 and not _re.search(r"[.!?]", text[:colon]):
        label = text[:colon].strip()
        rest = _format_quote_blocks(text[colon + 2:].strip()) or "_Not disclosed_"
        if label.lower() in {"quote", "quotes", "pipeline"} and not rest.startswith(">"):
            rest = f"> {rest}"
        return f"**{prefix}{label}**\n{rest}"

    formatted = _format_quote_blocks(text)
    if prefix and formatted.startswith(">"):
        return f"**{prefix.strip()}**\n{formatted}"
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
        match.start()
        for match in _re.finditer(
            r"(?<!^)(?<!\w)(?=(?:[A-Z][A-Za-z0-9/&'()%-]{1,20}(?: [A-Za-z0-9/&'()%-]{1,20}){0,4}):\s)",
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


def _render_model_comparison(df: pd.DataFrame):
    """Single company, single quarter, multiple models: columns = models, rows = sections."""
    company = df["company_name"].iloc[0]
    ticker = df["_ticker_folder"].iloc[0]
    period = df["_period_folder"].iloc[0]
    st.subheader(f"{company} ({ticker}) — {period} — Model Comparison")

    models = sorted(df["_model"].unique())

    for section_key in ANALYSIS_SECTIONS:
        label = SECTION_LABELS.get(section_key, section_key)
        with st.expander(label, expanded=True):
            cols = st.columns(len(models))
            for i, model in enumerate(models):
                model_row = df[df["_model"] == model]
                with cols[i]:
                    st.markdown(f"**{model}**")
                    if not model_row.empty:
                        _render_section(section_key, model_row.iloc[0].get(section_key))
                    else:
                        st.caption("_Not analyzed with this model_")


def _render_single_company_multi_quarter(df: pd.DataFrame):
    """Single company selected, multiple quarters: columns = quarters, rows = sections."""
    company = df["company_name"].iloc[0]
    ticker = df["_ticker_folder"].iloc[0]
    model_label = f" [{df['_model'].iloc[0]}]" if df["_model"].nunique() == 1 else ""
    st.subheader(f"{company} ({ticker}) — Quarter Comparison{model_label}")

    # Sort periods chronologically; for multi-model, use first row per period
    df = df.sort_values("_period_folder", key=lambda s: s.map(_period_sort_key))
    periods = df["_period_folder"].unique().tolist()

    for section_key in ANALYSIS_SECTIONS:
        label = SECTION_LABELS.get(section_key, section_key)
        with st.expander(label, expanded=False):
            cols = st.columns(len(periods))
            for i, period in enumerate(periods):
                # If multiple models for same period, pick first
                rows = df[df["_period_folder"] == period]
                row = rows.iloc[0]
                with cols[i]:
                    model_tag = f" `{row['_model']}`" if df["_model"].nunique() > 1 else ""
                    st.markdown(f"**{period}**{model_tag}")
                    _render_section(section_key, row.get(section_key))


def _render_multi_company_single_quarter(df: pd.DataFrame):
    """Multiple companies, single quarter: one row per company."""
    period = df["_period_folder"].iloc[0]
    model_label = f" [{df['_model'].iloc[0]}]" if df["_model"].nunique() == 1 else ""
    st.subheader(f"Quarter: {period} — Company Comparison{model_label}")

    for _, row in df.sort_values("company_name").iterrows():
        company = row["company_name"]
        ticker = row["_ticker_folder"]
        model_tag = f" `{row['_model']}`" if df["_model"].nunique() > 1 else ""
        with st.expander(f"{company} ({ticker}){model_tag}", expanded=True):
            for section_key in ANALYSIS_SECTIONS:
                label = SECTION_LABELS.get(section_key, section_key)
                st.markdown(f"**{label}**")
                _render_section(section_key, row.get(section_key))
                st.divider()


def _render_flat_table(df: pd.DataFrame):
    """General view: one expander per company+quarter combination."""
    st.subheader("All Results")

    df = df.assign(_period_sort=df["_period_folder"].map(_period_sort_key))
    df = df.sort_values(["company_name", "_period_sort", "_model"], ascending=[True, False, True])

    for _, row in df.iterrows():
        company = row["company_name"]
        ticker = row["_ticker_folder"]
        period = row["_period_folder"]
        model = row["_model"]

        with st.expander(f"{company} ({ticker}) — {period} — `{model}`", expanded=False):
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
    from datetime import datetime
    if isinstance(period_str, pd.Series):
        return period_str.apply(_period_sort_key_scalar)
    return _period_sort_key_scalar(period_str)


def _period_sort_key_scalar(period_str: str) -> str:
    from datetime import datetime
    try:
        dt = datetime.strptime(period_str, "%b %Y")
        return dt.strftime("%Y-%m")
    except (ValueError, TypeError):
        return "0000-00"


# -----------------------------------
# ENTRY
# -----------------------------------

if __name__ == "__main__":
    main()
