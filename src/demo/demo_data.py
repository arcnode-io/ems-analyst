"""ENV=demo CSV-backed mock for /measurements.

When ENV=demo, /measurements is served from a bundled CSV in memory —
the CSV pretends to be the DB. No Postgres measurements table, no
seeding. The CSV ships in the ems-analyst-agent package
(demo_data/measurements.csv).

forecasts stays on real Postgres — that's model output, not mock data.

Timestamps are shifted at load so max(ts) == now: "today" in a demo
chat always lines up with the freshest CSV hour.
"""

import csv
import io
import json
import logging
from datetime import UTC, datetime, timedelta
from importlib import resources
from typing import Final

from src.measurements.dto import Aggregation, MeasurementPoint, MeasurementSeries

log = logging.getLogger(__name__)

_PKG_DATA: Final[str] = "ems_analyst_agent.demo_data"
_CSV_NAME: Final[str] = "measurements.csv"


def _agg(values: list[float], how: Aggregation) -> float:
    """Aggregate a bucket's values per the requested function."""
    if how == "max":
        return max(values)
    if how == "min":
        return min(values)
    if how == "last":
        return values[-1]
    return sum(values) / len(values)


class _Row:
    """One parsed CSV measurement row."""

    __slots__ = ("device_id", "measurement", "site_id", "ts", "unit", "value")

    def __init__(
        self,
        ts: datetime,
        site_id: str,
        device_id: str,
        measurement: str,
        unit: str,
        value: str,
    ) -> None:
        self.ts = ts
        self.site_id = site_id
        self.device_id = device_id
        self.measurement = measurement
        self.unit = unit
        self.value = value  # raw JSON literal text


class DemoData:
    """In-memory CSV-backed stand-in for the measurements DB.

    Injected into the measurements controller in ENV=demo — duck-typed:
    it exposes `get` with the same signature MeasurementsService does.
    """

    def __init__(self) -> None:
        """Load + time-shift the bundled demo CSV once."""
        raw = resources.files(_PKG_DATA).joinpath(_CSV_NAME).read_bytes()
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8")))
        parsed = [
            (
                datetime.strptime(r["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC),
                r,
            )
            for r in reader
        ]
        if not parsed:
            self._rows: list[_Row] = []
            return
        max_ts = max(ts for ts, _ in parsed)
        now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        delta = now - max_ts
        self._rows = [
            _Row(
                ts=ts + delta,
                site_id=r["site_id"],
                device_id=r["device_id"],
                measurement=r["measurement"],
                unit=r["unit"],
                value=r["value"],
            )
            for ts, r in parsed
        ]
        log.info("ENV=demo: loaded %d mock rows from CSV", len(self._rows))

    async def get(
        self,
        site_id: str,
        device_id: str,
        measurement: str,
        start: datetime,
        end: datetime,
        aggregation: Aggregation = "mean",
    ) -> MeasurementSeries:
        """Hourly-bucketed gap-filled series — mirrors MeasurementsService."""
        buckets: dict[datetime, list[float]] = {}
        unit = ""
        for row in self._rows:
            if (
                row.site_id != site_id
                or row.device_id != device_id
                or row.measurement != measurement
                or not (start <= row.ts < end)
            ):
                continue
            unit = row.unit
            bucket = row.ts.replace(minute=0, second=0, microsecond=0)
            buckets.setdefault(bucket, []).append(float(json.loads(row.value)))
        points: list[MeasurementPoint] = []
        cursor = start.replace(minute=0, second=0, microsecond=0)
        end_hour = end.replace(minute=0, second=0, microsecond=0)
        while cursor <= end_hour:
            vals = buckets.get(cursor)
            points.append(
                MeasurementPoint(
                    ts=cursor,
                    value=_agg(vals, aggregation) if vals else None,
                )
            )
            cursor += timedelta(hours=1)
        return MeasurementSeries(
            site_id=site_id,
            device_id=device_id,
            measurement=measurement,
            unit=unit,
            points=points,
        )
