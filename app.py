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

                # Convert key_quotes list to formatted string for display
                kq = data.get("key_quotes", [])
                if isinstance(kq, list):
                    data["key_quotes"] = "\n".join(f"• {q}" for q in kq)

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
        sectors = sorted(df["sector"].unique())
        selected_sectors = st.multiselect("Sector", sectors, default=sectors)

        df_filtered = df[df["sector"].isin(selected_sectors)]

        # Sub-sector filter
        sub_sectors = sorted(df_filtered["sub_sector"].unique())
        selected_sub_sectors = st.multiselect("Sub-Sector", sub_sectors, default=sub_sectors)

        df_filtered = df_filtered[df_filtered["sub_sector"].isin(selected_sub_sectors)]

        # Company filter
        companies = sorted(df_filtered["company_name"].unique())
        selected_companies = st.multiselect("Company", companies, default=companies)

        df_filtered = df_filtered[df_filtered["company_name"].isin(selected_companies)]

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
                        st.markdown(str(model_row.iloc[0].get(section_key, "N/A")))
                    else:
                        st.markdown("_Not analyzed with this model_")


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
                    st.markdown(str(row.get(section_key, "N/A")))


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
                st.markdown(str(row.get(section_key, "N/A")))
                st.divider()


def _render_flat_table(df: pd.DataFrame):
    """General view: one expander per company+quarter combination."""
    st.subheader("All Results")

    df = df.sort_values(["company_name", "_period_folder"])

    for _, row in df.iterrows():
        company = row["company_name"]
        ticker = row["_ticker_folder"]
        period = row["_period_folder"]
        model = row["_model"]

        with st.expander(f"{company} ({ticker}) — {period} — `{model}`", expanded=False):
            for section_key in ANALYSIS_SECTIONS:
                label = SECTION_LABELS.get(section_key, section_key)
                st.markdown(f"**{label}**")
                st.markdown(str(row.get(section_key, "N/A")))
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
