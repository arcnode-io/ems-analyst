"""gridstatus.io REST wrapper for ISO market data — LLM-facing text tool.

Mirrors weather_api.py shape: friendly error strings instead of
exception propagation so the LLM can recover. Falls back to synthetic
(clearly labelled) rows when gridstatus is unavailable (quota /
rate-limit / unknown dataset) — the free tier's monthly quota exhausts
mid-cycle; without a fallback the agent loop stalls on every market
question until the 1st of the month.

The actual HTTP call + fallback-trigger logic lives in market_prices.py
and is shared with fetch_market_series (the typed counterpart used by
compare_forecast_to_actual) — this module only turns that into text.
"""

from datetime import UTC, datetime
from typing import Any, Final

import httpx
from pydantic import BaseModel

from .market_prices import GRIDSTATUS_BASE_URL as GRIDSTATUS_BASE_URL
from .market_prices import _fetch_payload, _GridstatusUnavailableError, _InvalidApiKeyError, _synthetic_points

DEFAULT_LIMIT: Final[int] = 25
_SYNTHETIC_MARKER: Final[str] = (
    "⚠ SYNTHETIC DATA — gridstatus.io unavailable. Plausible "
    "magnitudes only; do NOT report as real market data."
)
_SYNTHETIC_MAX_ROWS: Final[int] = 5


class _SyntheticRow(BaseModel):
    """A single fake row returned when gridstatus is unavailable."""

    ts: str
    value: float
    note: str = "SYNTHETIC"
    location: str | None = None


async def get_market_data(
    dataset: str,
    start: str | None = None,
    end: str | None = None,
    limit: int = DEFAULT_LIMIT,
    location: str | None = None,
) -> str:
    """Query a gridstatus.io dataset and return an LLM-friendly summary.

    Args:
        dataset: Dataset slug. Examples: 'ercot_fuel_mix',
            'caiso_load', 'pjm_lmp_by_pnode', 'isone_real_time_lmp',
            'ercot_spp_day_ahead_hourly'. Full catalog:
            https://www.gridstatus.io/datasets.
        start: ISO-8601 start, e.g. '2026-05-15T00:00:00Z'. None = latest.
        end: ISO-8601 end. None = open-ended.
        limit: Row cap. Default 25 keeps responses LLM-context friendly.
        location: Exact value of the dataset's `location` column, e.g.
            'HB_NORTH' for an ERCOT trading hub. Without this, a
            multi-node dataset like ercot_spp_day_ahead_hourly returns
            whatever node sorts first — never necessarily the settlement
            point a forecast was made for. None = no location filter.

    Returns:
        Multi-line text summary: dataset name + first N rows.
        On HTTP error returns a human-readable string instead of raising —
        keeps the agent loop alive. On 403/404/429 returns clearly-marked
        SYNTHETIC rows so downstream reasoning can still proceed.

    Raises:
        ValueError: GRIDSTATUS_API_KEY env var missing.
    """
    try:
        payload = await _fetch_payload(dataset, start, end, limit, location)
    except _InvalidApiKeyError:
        return "Invalid GRIDSTATUS_API_KEY. Check the env var."
    except _GridstatusUnavailableError as e:
        # Reason: quota (403), unknown dataset (404), rate-limit (429) —
        # fall back so the agent can still answer with clearly-marked
        # synthetic rows.
        return _synthetic_fallback(dataset, start, end, limit, e.status, location=location)
    except httpx.HTTPStatusError as e:
        return f"Error querying {dataset}: HTTP {e.response.status_code}"
    except httpx.RequestError as e:
        return f"Network error querying {dataset}: {e!s}"

    return _format(dataset, payload)


def _synthetic_fallback(
    dataset: str,
    start: str | None,
    end: str | None,
    limit: int,
    status: int,
    now: datetime | None = None,
    location: str | None = None,
) -> str:
    """Generate plausible synthetic rows when gridstatus is unavailable.

    Deterministic PRNG seeded by (dataset, start, end, location): repeated
    calls within a turn return the same rows so the LLM doesn't see
    flapping numbers on retry.

    Args:
        dataset: The requested dataset slug (echoed into the header).
        start: Start time from the caller (part of the seed).
        end: End time from the caller (part of the seed).
        limit: Requested row cap; capped at _SYNTHETIC_MAX_ROWS.
        status: The upstream HTTP status that triggered the fallback.
        now: Anchor time for generated row timestamps. Defaults to
            `datetime.now(UTC)` rounded to the hour. Exposed for tests.
        location: Echoed into each fake row so a synthetic-fallback
            response still names the location it's standing in for —
            without this, a comparison against a real forecast would
            silently look like it was for the right hub when gridstatus
            was never actually reached. None = omitted from the rows.

    Returns:
        Multi-line string with the synthetic marker + a normal `_format`
        rendering so downstream code treats it uniformly.
    """
    seed_key = f"{dataset}|{start}|{end}|{location}"
    anchor = (now or datetime.now(UTC)).replace(minute=0, second=0, microsecond=0)
    n_rows = min(limit, _SYNTHETIC_MAX_ROWS)
    points = _synthetic_points(anchor, n_rows, seed_key)
    rows = [
        _SyntheticRow(ts=p.ts.isoformat(), value=p.value, location=location) for p in points
    ]
    header = f"{_SYNTHETIC_MARKER} (gridstatus HTTP {status})"
    payload: dict[str, Any] = {"data": [r.model_dump(exclude_none=True) for r in rows]}
    return f"{header}\n{_format(dataset, payload)}"


def _format(dataset: str, payload: dict[str, Any]) -> str:
    """Squash the JSON envelope into an LLM-friendly text blob."""
    rows = payload.get("data", [])
    if not rows:
        return f"{dataset}: no rows returned."
    head = rows[:5]
    lines = [f"{dataset} — {len(rows)} row(s):"]
    for row in head:
        snippet = ", ".join(f"{k}={v}" for k, v in row.items())
        lines.append(f"  - {snippet}")
    if len(rows) > 5:
        lines.append(f"  ... +{len(rows) - 5} more rows")
    return "\n".join(lines)
