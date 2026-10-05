"""Per-device-family health-signal → severity derivation.

Real fleet telemetry publishes raw, family-specific signals (a boolean
trip relay, a numeric fault bitfield, a link-status string, several
per-GPU throttle reasons) rather than one universal `status` enum.
This is the single place that interprets those raw signals into the
same ok/warn/alarm vocabulary the literal `status` measurement already
uses, so build_device_status() has one consistent output shape no
matter which signal(s) back a given device.

Scope: only families with an unambiguous, self-evident FAULT signal are
graded here. Devices whose only available data is an operational MODE
(pump_state, operating_state, dispatch_mode) are deliberately left
ungraded — guessing which mode values mean "broken" without a known
complete enum would be inventing meaning, not deriving it. Checked the
domain corpus for BESS operating-state and GPU throttle-reason severity
convention first (rag_search): both queries scored well below the 0.02
top-1 coverage threshold, so the corpus doesn't cover this — not guessed.
"""

import re
from collections.abc import Callable
from typing import Final, NamedTuple

from ..schemas import RowSeverity

_FAMILY_SUFFIX: Final[re.Pattern[str]] = re.compile(r"_\d+$")

RawValues = dict[str, float | str | bool | None]
_Rule = Callable[[RawValues], tuple["RowSeverity | None", str]]


def device_family(device_id: str) -> str:
    """Strip a trailing _<N> instance suffix — 'gpu_node_42' -> 'gpu_node'."""
    return _FAMILY_SUFFIX.sub("", device_id)


def _protective_relay(values: RawValues) -> tuple[RowSeverity | None, str]:
    """Trip or ground fault = alarm. Both are real protection-operated signals."""
    trip = values.get("trip_status")
    ground = values.get("ground_fault")
    if trip is None and ground is None:
        return None, "unknown"
    if trip is True:
        return "alarm", "tripped"
    if ground is True:
        return "alarm", "ground fault"
    return "ok", "normal"


def _cooler(values: RawValues) -> tuple[RowSeverity | None, str]:
    """fault_word is a standard alarm-bitfield convention: 0 = no active fault."""
    word = values.get("fault_word")
    if word is None:
        return None, "unknown"
    return ("ok", "normal") if word == 0.0 else ("alarm", f"fault_word={word:g}")


def _network_switch(values: RawValues) -> tuple[RowSeverity | None, str]:
    link = values.get("port_link_status")
    if link is None:
        return None, "unknown"
    return ("ok", "UP") if link == "UP" else ("alarm", str(link))


def _gpu_node(values: RawValues) -> tuple[RowSeverity | None, str]:
    """Any GPU throttling ('NA' means not throttled) is a degraded-performance
    signal worth surfacing, but it's often routine power/thermal management
    rather than a hard failure — warn, not alarm."""
    reasons = [v for k, v in values.items() if k.endswith("_throttle_reason")]
    reasons = [r for r in reasons if r is not None]
    if not reasons:
        return None, "unknown"
    active = sorted({str(r) for r in reasons if r != "NA"})
    if not active:
        return "ok", "normal"
    return "warn", ", ".join(active)


class FamilyRule(NamedTuple):
    """The measurements a family's health depends on + how to derive severity."""

    measurements: list[str]
    derive: _Rule


FAMILY_RULES: Final[dict[str, FamilyRule]] = {
    "protective_relay": FamilyRule(["trip_status", "ground_fault"], _protective_relay),
    "cooler": FamilyRule(["fault_word"], _cooler),
    "network_switch": FamilyRule(["port_link_status"], _network_switch),
    "gpu_node": FamilyRule(
        [f"gpu_{i}_throttle_reason" for i in range(1, 9)], _gpu_node
    ),
}
