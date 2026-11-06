"""DateTime utility helpers for NEXA."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def parse_datetime(val: Any) -> datetime:
    """Parse various datetime representations into a timezone-aware datetime.

    Tries Python's native fromisoformat first, and falls back to dateutil.parser
    for non-standard formats.
    """
    if isinstance(val, datetime):
        return val if val.tzinfo is not None else val.replace(tzinfo=UTC)

    if not isinstance(val, str):
        raise ValueError(f"Expected datetime or string, got {type(val).__name__}")

    s = val.strip()
    iso_candidate = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso_candidate)
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
    except ValueError:
        pass

    try:
        import importlib

        dt_parser = importlib.import_module("dateutil.parser")
        dt = dt_parser.parse(s)
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
    except Exception as exc:
        raise ValueError(f"Unable to parse datetime from '{val}': {exc}") from exc
