"""Integration test for the Neptune seed path — pook-mocked HTTP.

Per test-taxonomy: this is an integration test because it crosses the
HTTP boundary (sigv4-signed httpx calls). pook intercepts in-process so
CI doesn't need real AWS / Neptune access. No real Neptune emulator
exists; bulk-loader behavior is the contract pook verifies.
"""

from unittest.mock import AsyncMock

import pook
import pytest

from src.python_mcp_server.seed import seed_graph_neptune

NEPTUNE_HOST = "neptune.example.invalid"
AOSS_HOST = "aoss.example.invalid"
LOADER_ROLE = "arn:aws:iam::123456789012:role/NeptuneLoaderRole"
LOAD_ID = "abc-load-id-xyz"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Boto3 needs creds to sign; supply test ones so SigV4 succeeds."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIATEST")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testsecret")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("NEPTUNE_HOST", NEPTUNE_HOST)
    monkeypatch.setenv("NEPTUNE_LOADER_ROLE_ARN", LOADER_ROLE)
    monkeypatch.setenv("AOSS_HOST", AOSS_HOST)


@pytest.fixture
def _stub_aoss(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Replace _populate_aoss_indexes — its own pook coverage lives in
    a dedicated unit test (would otherwise require mocking graphiti's
    full NeptuneDriver init + OpenSearch client + 4 index-create POSTs)."""
    stub = AsyncMock(return_value=None)
    monkeypatch.setattr("src.python_mcp_server.seed._populate_aoss_indexes", stub)
    return stub


@pytest.mark.asyncio
async def test_seed_graph_neptune_starts_load_and_writes_marker(
    _stub_aoss: AsyncMock,
) -> None:
    """Happy path — marker absent, load completes, AOSS populated, marker written."""
    # Arrange — pook intercepts the openCypher marker-check, the loader
    # POST, the GET status poll, and the marker-write MERGE.
    pook.on()
    pook.enable_network()

    # marker absent → empty results
    pook.post(f"https://{NEPTUNE_HOST}:8182/opencypher").times(1).reply(200).json(
        {"results": []}
    )
    # bulk-load POST returns a loadId
    pook.post(f"https://{NEPTUNE_HOST}:8182/loader").times(1).reply(200).json(
        {"status": "200 OK", "payload": {"loadId": LOAD_ID}}
    )
    # status poll returns COMPLETED on first check
    pook.get(f"https://{NEPTUNE_HOST}:8182/loader/{LOAD_ID}").times(1).reply(200).json(
        {"payload": {"overallStatus": {"status": "LOAD_COMPLETED"}}}
    )
    # marker write MERGE
    pook.post(f"https://{NEPTUNE_HOST}:8182/opencypher").times(1).reply(200).json(
        {"results": []}
    )

    try:
        # Act
        await seed_graph_neptune()

        # Assert — all 4 mocks consumed + AOSS populate called between
        # Neptune-load-complete and marker-write
        assert pook.isdone(), f"pending mocks: {pook.pending()}"
        _stub_aoss.assert_awaited_once()
    finally:
        pook.off()


@pytest.mark.asyncio
async def test_seed_graph_neptune_skips_when_marker_present() -> None:
    """Idempotent — marker present → no loader call, immediate return."""
    # Arrange — marker check returns a row; no loader call should fire
    pook.on()
    pook.enable_network()
    pook.post(f"https://{NEPTUNE_HOST}:8182/opencypher").times(1).reply(200).json(
        {"results": [{"m": {"slice": "graph"}}]}
    )

    try:
        # Act
        await seed_graph_neptune()

        # Assert — only the marker check fired; no loader POST mocked
        assert pook.isdone(), f"pending mocks: {pook.pending()}"
    finally:
        pook.off()


@pytest.mark.asyncio
async def test_seed_graph_neptune_raises_when_load_fails() -> None:
    """Load failure surfaces as RuntimeError with the status payload."""
    # Arrange — load reaches LOAD_FAILED terminal state
    pook.on()
    pook.enable_network()
    pook.post(f"https://{NEPTUNE_HOST}:8182/opencypher").times(1).reply(200).json(
        {"results": []}
    )
    pook.post(f"https://{NEPTUNE_HOST}:8182/loader").times(1).reply(200).json(
        {"status": "200 OK", "payload": {"loadId": LOAD_ID}}
    )
    pook.get(f"https://{NEPTUNE_HOST}:8182/loader/{LOAD_ID}").times(1).reply(200).json(
        {"payload": {"overallStatus": {"status": "LOAD_FAILED", "reason": "bad csv"}}}
    )

    try:
        # Act + Assert
        with pytest.raises(RuntimeError, match="LOAD_FAILED"):
            await seed_graph_neptune()
    finally:
        pook.off()
