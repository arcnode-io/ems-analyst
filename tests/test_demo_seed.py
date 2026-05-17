"""Integration tests for demo_seed against a real Postgres.

Verifies the bundled CSV loads cleanly + idempotency (re-run is no-op
when rows already present). Schema match against platform-api's
telemetry_writer.py is asserted implicitly: if COPY fails on the
NOT NULL unit column, the test fails.
"""

import os
from collections.abc import Generator

import pytest

from src.ems_analyst_agent.demo_seed import seed_measurements
from tests.fixtures.containers import start_postgres


@pytest.fixture(scope="module")
def empty_postgres_url() -> Generator[str]:
    """Fresh Postgres testcontainer with NO measurements table yet."""
    with start_postgres(
        password=os.environ["POSTGRES_PASSWORD"],
        image="postgres:15",
    ) as pg:
        yield pg.url


class TestSeedMeasurements:
    @pytest.mark.asyncio
    async def test_first_seed_loads_bundled_csv(
        self, empty_postgres_url: str
    ) -> None:
        # Arrange + Act
        rows = await seed_measurements(empty_postgres_url)

        # Assert — CSV has ~100 rows; expect at least 80
        assert rows >= 80

    @pytest.mark.asyncio
    async def test_second_seed_is_noop(
        self, empty_postgres_url: str
    ) -> None:
        # Arrange — first call already populated the table from the
        # previous test (module-scoped fixture is shared).
        # Act
        rows = await seed_measurements(empty_postgres_url)

        # Assert — returned count == existing count, no doubling
        assert rows >= 80
        # Re-running again must NOT inflate the count
        rows_again = await seed_measurements(empty_postgres_url)
        assert rows_again == rows
