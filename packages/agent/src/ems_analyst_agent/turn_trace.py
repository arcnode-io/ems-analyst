"""Tool-call trace labeling for the live turn stream.

Pure functions — a human-readable label per tool call, and a trace row
per completed call. `turn.py` calls into this while driving the live
agent loop; it never builds this shape itself.
"""

import time

from pydantic_ai.messages import FunctionToolResultEvent

# Human-readable action shown in the HMI live-trace per tool call —
# never raw args. Unknown tools fall back to DEFAULT_TOOL_LABEL.
TOOL_LABELS: dict[str, str] = {
    "describe_site": "Checking what data is queryable",
    "get_topology": "Reading site topology",
    "get_device_status": "Checking device status",
    "explain_dispatch": "Correlating dispatch against price",
    "query_timeseries": "Querying the site historian",
    "get_forecast": "Pulling the published forecast",
    "compare_forecast_to_actual": "Comparing forecast to actual price",
    "query_markets": "Computing market revenue",
    "query_energy_breakdown": "Computing the energy mix",
    "get_weather_forecast": "Checking the weather",
    "get_market_data": "Querying ERCOT market data",
    "get_energy_news": "Scanning energy news",
}
DEFAULT_TOOL_LABEL: str = "Searching the knowledge base"

# Tools whose result carries a one-line headline worth surfacing in the
# toolTrace `summary` — external-data tools only.
_SUMMARY_TOOLS: frozenset[str] = frozenset(
    {"get_energy_news", "get_market_data", "get_weather_forecast"}
)


def result_summary(tool: str, event: FunctionToolResultEvent) -> str | None:
    """One-line headline from an external tool's result; None otherwise.

    Only the external-data tools carry something headline-shaped — the
    HMI intel feed surfaces it. First non-empty line, trimmed.
    """
    if tool not in _SUMMARY_TOOLS:
        return None
    text = str(getattr(event.part, "content", "")).strip()
    if not text:
        return None
    return text.splitlines()[0].strip()[:140] or None


def trace_entry(
    tool: str, event: FunctionToolResultEvent, seq: int, t0: float
) -> dict[str, object]:
    """Build a trace row from a completed tool call (carries stream `seq`)."""
    outcome = "ok" if getattr(event.part, "part_kind", "") == "tool-return" else "error"
    return {
        "seq": seq,
        "tool": tool,
        "label": TOOL_LABELS.get(tool, DEFAULT_TOOL_LABEL),
        "outcome": outcome,
        "ms": int((time.perf_counter() - t0) * 1000),
        "summary": result_summary(tool, event),
    }
