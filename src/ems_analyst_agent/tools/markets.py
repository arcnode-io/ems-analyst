"""gridstatus.io REST wrapper for ISO market data.

Mirrors weather_api.py shape: raw httpx (no SDK), env-keyed auth, friendly
error strings instead of exception propagation so the LLM can recover.
"""

import os
from typing import Any, Final

import httpx

GRIDSTATUS_BASE_URL: Final[str] = "https://api.gridstatus.io/v1"
HTTP_TIMEOUT_SEC: Final[float] = 15.0
DEFAULT_LIMIT: Final[int] = 25


async def get_market_data(
    dataset: str,
    start: str | None = None,
    end: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> str:
    """Query a gridstatus.io dataset and return an LLM-friendly summary.

    Args:
        dataset: Dataset slug. Examples: 'ercot_fuel_mix',
            'caiso_load', 'pjm_lmp_by_pnode', 'isone_real_time_lmp'.
            Full catalog: https://www.gridstatus.io/datasets.
        start: ISO-8601 start, e.g. '2026-05-15T00:00:00Z'. None = latest.
        end: ISO-8601 end. None = open-ended.
        limit: Row cap. Default 25 keeps responses LLM-context friendly.

    Returns:
        Multi-line text summary: dataset name + first N rows.
        On HTTP error returns a human-readable string instead of raising —
        keeps the agent loop alive.

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
        if e.response.status_code == 404:
            return f"Dataset '{dataset}' not found. See gridstatus.io/datasets."
        return f"Error querying {dataset}: HTTP {e.response.status_code}"
    except httpx.RequestError as e:
        return f"Network error querying {dataset}: {e!s}"

    return _format(dataset, payload)


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
