"""Unit tests for RunContext wrapper behavior that isn't in a builder.

Builder artifact-shaping is tested where the builder lives
(telemetry_test.py, site_analytics_test.py). This file covers the
once-per-turn cache guard living in the describe_site/get_topology
wrappers themselves.
"""

from dataclasses import dataclass
from unittest.mock import AsyncMock, Mock

import pytest

from ..server_client import MeasurementPair, ServerClient, SiteDescription
from ._common import _TelemetryDeps
from .telemetry_tools import describe_site


@dataclass
class _FakeCtx:
    """Minimal RunContext stand-in — the wrappers only ever read `.deps`."""

    deps: _TelemetryDeps


class TestDescribeSiteCache:
    """AAA — a repeat describe_site call in the same turn skips the refetch."""

    @pytest.mark.asyncio
    async def test_second_call_reuses_cache_without_refetching(self) -> None:
        # Arrange — Mock(spec=...) satisfies the wrapper's isinstance guard
        desc = SiteDescription(
            site_id="demo-site",
            pairs=[
                MeasurementPair(
                    device_id="bess_module_01", measurement="active_power", samples=1
                )
            ],
        )
        fake_client = Mock(spec=ServerClient)
        fake_client.describe_site = AsyncMock(return_value=desc)
        deps = _TelemetryDeps(server=fake_client)
        ctx = _FakeCtx(deps=deps)

        # Act
        await describe_site(ctx)  # ty: ignore[invalid-argument-type]
        second_result = await describe_site(ctx)  # ty: ignore[invalid-argument-type]

        # Assert — server hit once; second call served from cache
        assert fake_client.describe_site.call_count == 1
        assert "already have" in second_result.lower()
        assert len(deps.artifacts) == 2  # both appended; _presentable dedupes later
