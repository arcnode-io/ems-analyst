"""gridstatus.io REST wrapper for ISO market data.

Mirrors weather_api.py shape: raw httpx (no SDK), env-keyed auth, friendly
error strings instead of exception propagation so the LLM can recover.

Falls back to synthetic (clearly labelled) rows when gridstatus is
unavailable (quota / rate-limit / unknown dataset). Reason: the free
tier's monthly quota exhausts mid-cycle; without a fallback the agent
loop stalls on every market question until the 1st of the month.
"""

import hashlib
import math
import os
import random
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import httpx
from pydantic import BaseModel

GRIDSTATUS_BASE_URL: Final[str] = "https://api.gridstatus.io/v1"
HTTP_TIMEOUT_SEC: Final[float] = 15.0
DEFAULT_LIMIT: Final[int] = 25
# Status codes that mean "upstream is refusing us" rather than "you sent
# a bad request" — we synthesise for these so the agent keeps working.
_SYNTHETIC_TRIGGER_STATUS: Final[frozenset[int]] = frozenset({403, 404, 429})
_SYNTHETIC_MARKER: Final[str] = (
    "⚠ SYNTHETIC DATA — gridstatus.io unavailable. Plausible "
    "magnitudes only; do NOT report as real market data."
)
# ERCOT DAM SPP HB_NORTH baseline — log-normal around ~$33/MWh with a
# small chance of a scarcity spike. Numbers chosen to LOOK reasonable,
# not to match a real distribution.
_SYNTHETIC_LOG_MEAN: Final[float] = 3.5
_SYNTHETIC_LOG_STD: Final[float] = 0.4
_SYNTHETIC_SPIKE_PROB: Final[float] = 0.05
_SYNTHETIC_SPIKE_MIN: Final[float] = 10.0
_SYNTHETIC_SPIKE_MAX: Final[float] = 40.0
_SYNTHETIC_MAX_ROWS: Final[int] = 5


class _SyntheticRow(BaseModel):
    """A single fake row returned when gridstatus is unavailable."""

    ts: str
    value: float
    note: str = "SYNTHETIC"


async def get_market_data(
    dataset: str,
    start: str | None = None,
    end: str | None = None,
    limit: int = DEFAULT_LIMIT,
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

    Returns:
        Multi-line text summary: dataset name + first N rows.
        On HTTP error returns a human-readable string instead of raising —
        keeps the agent loop alive. On 403/404/429 returns clearly-marked
        SYNTHETIC rows so downstream reasoning can still proceed.

    Raises:
        ValueError: GRIDSTATUS_API_KEY env var missing.
    """
    api_key = os.environ.get("GRIDSTATUS_API_KEY", "")
    if not api_key:
        raise ValueError(
            "GRIDSTATUS_API_KEY environment variable not set. "
            "Get a key from https://www.gridstatus.io"
        )

    params: dict[str, Any] = {"limit": limit}
    if start is not None:
        params["start_time"] = start
    if end is not None:
        params["end_time"] = end

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GRIDSTATUS_BASE_URL}/datasets/{dataset}/query",
                params=params,
                headers={"x-api-key": api_key},
                timeout=HTTP_TIMEOUT_SEC,
            )
            resp.raise_for_status()
            payload = resp.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            return "Invalid GRIDSTATUS_API_KEY. Check the env var."
        if e.response.status_code in _SYNTHETIC_TRIGGER_STATUS:
            # Reason: quota (403), unknown dataset (404), rate-limit (429) —
            # fall back so the agent can still answer with clearly-marked
            # synthetic rows.
            return _synthetic_fallback(
                dataset, start, end, limit, e.response.status_code
            )
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
) -> str:
    """Generate plausible synthetic rows when gridstatus is unavailable.

    Deterministic PRNG seeded by (dataset, start, end): repeated calls
    within a turn return the same rows so the LLM doesn't see flapping
    numbers on retry.

    Args:
        dataset: The requested dataset slug (echoed into the header).
        start: Start time from the caller (part of the seed).
        end: End time from the caller (part of the seed).
        limit: Requested row cap; capped at _SYNTHETIC_MAX_ROWS.
        status: The upstream HTTP status that triggered the fallback.
        now: Anchor time for generated row timestamps. Defaults to
            `datetime.now(UTC)` rounded to the hour. Exposed for tests.

    Returns:
        Multi-line string with the synthetic marker + a normal `_format`
        rendering so downstream code treats it uniformly.
    """
    seed_key = f"{dataset}|{start}|{end}".encode()
    seed = int(hashlib.sha256(seed_key).hexdigest()[:16], 16)
    # Reason: non-crypto — this seeds fake price rows for LLM display.
    # `random.Random` is exactly what we want; suppress ruff S311 + bandit B311.
    rng = random.Random(seed)  # noqa: S311  # nosec B311
    n_rows = min(limit, _SYNTHETIC_MAX_ROWS)
    anchor = (now or datetime.now(UTC)).replace(minute=0, second=0, microsecond=0)
    rows: list[_SyntheticRow] = []
    for i in range(n_rows):
        ts = (anchor - timedelta(hours=n_rows - i - 1)).isoformat()
        base = math.exp(rng.gauss(_SYNTHETIC_LOG_MEAN, _SYNTHETIC_LOG_STD))
        if rng.random() < _SYNTHETIC_SPIKE_PROB:
            base *= rng.uniform(_SYNTHETIC_SPIKE_MIN, _SYNTHETIC_SPIKE_MAX)
        rows.append(_SyntheticRow(ts=ts, value=round(base, 2)))
    header = f"{_SYNTHETIC_MARKER} (gridstatus HTTP {status})"
    payload: dict[str, Any] = {"data": [r.model_dump() for r in rows]}
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
