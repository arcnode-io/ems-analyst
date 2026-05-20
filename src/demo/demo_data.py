"""ENV=demo CSV-backed mock for the measurement-derived endpoints.

When ENV=demo, /measurements, /devices, /description are served from a
bundled CSV in memory — the CSV pretends to be the DB. No Postgres
measurements table, no seeding. The CSV ships in the ems-analyst-agent
package (demo_data/measurements.csv).

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

from src.description.dto import MeasurementPair, SiteDescription
from src.devices.dto import DeviceList, DeviceRow
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

    One instance is shared across the measurements/devices/description
    controllers in ENV=demo — duck-typed: it exposes get/list/describe
    with the same signatures the real services do.
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

    async def list(self, site_id: str, status: list[str] | None = None) -> DeviceList:
        """Distinct devices + latest 'status' measurement — mirrors DevicesService."""
        latest_status: dict[str, tuple[datetime, str]] = {}
        devices: set[str] = set()
        for row in self._rows:
            if row.site_id != site_id:
                continue
            devices.add(row.device_id)
            if row.measurement == "status":
                prev = latest_status.get(row.device_id)
                if prev is None or row.ts > prev[0]:
                    latest_status[row.device_id] = (
                        row.ts,
                        str(json.loads(row.value)),
                    )
        rows = [
            DeviceRow(
                device_id=d,
                status=latest_status[d][1] if d in latest_status else None,
            )
            for d in sorted(devices)
        ]
        if status:
            rows = [r for r in rows if r.status in status]
        return DeviceList(site_id=site_id, devices=rows)

    async def describe(self, site_id: str) -> SiteDescription:
        """(device, measurement, sample-count) inventory — mirrors DescriptionService."""
        counts: dict[tuple[str, str], int] = {}
        for row in self._rows:
            if row.site_id != site_id:
                continue
            key = (row.device_id, row.measurement)
            counts[key] = counts.get(key, 0) + 1
        pairs = [
            MeasurementPair(device_id=dev, measurement=meas, samples=n)
            for (dev, meas), n in sorted(counts.items())
        ]
        return SiteDescription(site_id=site_id, pairs=pairs)
