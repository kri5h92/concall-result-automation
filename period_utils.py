"""
Helpers for working with transcript period labels.

The pipeline stores periods as folder names such as "Feb 2026". These helpers
keep date parsing and recent-period selection consistent across downloading,
PDF extraction, and LLM analysis.
"""

from datetime import datetime


def normalize_recent_quarters(recent_quarters: int | None) -> int | None:
    """
    Clamp a recent-period limit to a usable value.

    None means no limit. Invalid values fall back to 1, and numeric values are
    clamped to at least 1.
    """
    if recent_quarters is None:
        return None
    try:
        recent_quarters = int(recent_quarters)
    except (TypeError, ValueError):
        return 1
    return max(1, recent_quarters)


def parse_period_date(period_str: str) -> datetime:
    """
    Parse period labels like "Feb 2026" for chronological sorting.

    Unparseable labels intentionally sort to the oldest position.
    """
    try:
        return datetime.strptime(period_str, "%b %Y")
    except (ValueError, TypeError):
        return datetime(1970, 1, 1)


def select_recent_period_items(items: list[tuple], recent_quarters: int | None) -> list[tuple]:
    """
    Sort period-keyed tuples descending and keep the most recent N when limited.

    Each tuple must store its period label in item[0]. Additional tuple values
    are preserved unchanged.
    """
    sorted_items = sorted(items, key=lambda item: parse_period_date(item[0]), reverse=True)
    limit = normalize_recent_quarters(recent_quarters)
    if limit is None:
        return sorted_items
    return sorted_items[:limit]
