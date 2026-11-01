"""Automatic update schedule: check no more than once per 24 hours."""
from datetime import datetime, timedelta, timezone


def is_update_check_due(last_checked: str, *, now: datetime | None = None, interval_hours: int = 24) -> bool:
    if not last_checked:
        return True
    try:
        previous = datetime.fromisoformat(last_checked)
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=timezone.utc)
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current - previous >= timedelta(hours=interval_hours)
    except (ValueError, TypeError, OverflowError):
        return True
