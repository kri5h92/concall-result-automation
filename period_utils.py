from datetime import datetime


def normalize_recent_quarters(recent_quarters: int | None) -> int | None:
    """Clamp a recent-quarter limit to a usable value. None means no limit."""
    if recent_quarters is None:
        return None
    try:
        recent_quarters = int(recent_quarters)
    except (TypeError, ValueError):
        return 1
    return max(1, recent_quarters)


def parse_period_date(period_str: str) -> datetime:
    """Parse period labels like 'Feb 2026' for chronological sorting."""
    try:
        return datetime.strptime(period_str, "%b %Y")
    except (ValueError, TypeError):
        return datetime(1970, 1, 1)


def select_recent_period_items(items: list[tuple], recent_quarters: int | None) -> list[tuple]:
    """Sort period-keyed tuples descending and keep the most recent N when limited."""
    sorted_items = sorted(items, key=lambda item: parse_period_date(item[0]), reverse=True)
    limit = normalize_recent_quarters(recent_quarters)
    if limit is None:
        return sorted_items
    return sorted_items[:limit]
