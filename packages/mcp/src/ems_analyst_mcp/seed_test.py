"""Unit tests for _download_with_progress — pure, no network/containers.

Container-backed integration tests for the seed flows themselves live in
tests/test_seed.py; this file only covers the chunked-download + progress
logging helper those flows now share.
"""

import logging
from unittest.mock import patch

import pytest

from .seed import _download_with_progress

_ONE_MIB = 1024 * 1024


class _FakeHttpResponse:
    """Minimal stand-in for http.client.HTTPResponse — headers + chunked read."""

    def __init__(self, body: bytes, content_length: int | None) -> None:
        self._body = body
        self._pos = 0
        self.headers = (
            {"Content-Length": str(content_length)}
            if content_length is not None
            else {}
        )

    def read(self, n: int | None = None) -> bytes:
        end = len(self._body) if n is None else self._pos + n
        chunk = self._body[self._pos : end]
        self._pos += len(chunk)
        return chunk

    def __enter__(self) -> "_FakeHttpResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class TestDownloadWithProgress:
    """AAA — fetch in chunks, log one line per 10% crossed, return full bytes."""

    def test_returns_full_body_unchanged(self) -> None:
        """Chunked reads reassemble into the exact original body."""
        # Arrange — 3 MiB body, read in 1 MiB chunks
        body = b"x" * (3 * _ONE_MIB)
        fake = _FakeHttpResponse(body, content_length=len(body))

        # Act
        with patch("ems_analyst_mcp.seed.urllib.request.urlopen", return_value=fake):
            actual = _download_with_progress("https://example.invalid/x.gz", "vector")

        # Assert
        assert actual == body

    def test_logs_one_line_per_decile_crossed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """One 'seed progress' line per 10% crossed, not per chunk."""
        # Arrange — 10 MiB body, 1 MiB chunks -> crosses each decile exactly once
        body = b"x" * (10 * _ONE_MIB)
        fake = _FakeHttpResponse(body, content_length=len(body))

        # Act
        with (
            patch("ems_analyst_mcp.seed.urllib.request.urlopen", return_value=fake),
            caplog.at_level(logging.INFO, logger="ems_analyst_mcp.seed"),
        ):
            _download_with_progress("https://example.invalid/x.gz", "graph")

        # Assert — 10 progress lines, each naming the label + a rising percentage
        progress_lines = [
            r.message for r in caplog.records if "seed progress:" in r.message
        ]
        assert len(progress_lines) == 10
        assert progress_lines[0] == "seed progress: graph 10% (1 MiB of 10 MiB)"
        assert progress_lines[-1] == "seed progress: graph 100% (10 MiB of 10 MiB)"

    def test_logs_one_line_per_1pct_crossed_when_requested(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """granularity_pct=1 -> a line per 1%, not just per 10% (Joe's ask)."""
        # Arrange — 100-byte body, 1-byte chunks -> crosses each of 100 percents
        body = b"x" * 100
        fake = _FakeHttpResponse(body, content_length=len(body))

        # Act
        with (
            patch("ems_analyst_mcp.seed.urllib.request.urlopen", return_value=fake),
            caplog.at_level(logging.INFO, logger="ems_analyst_mcp.seed"),
        ):
            _download_with_progress(
                "https://example.invalid/x.gz",
                "graph",
                granularity_pct=1,
                chunk_bytes=1,
            )

        # Assert — 100 progress lines, one per percent
        progress_lines = [
            r.message for r in caplog.records if "seed progress:" in r.message
        ]
        assert len(progress_lines) == 100
        assert "1%" in progress_lines[0]
        assert "100%" in progress_lines[-1]

    def test_missing_content_length_skips_progress_but_still_returns_body(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """No Content-Length -> no progress lines, but the body still comes back whole."""
        # Arrange — no Content-Length header, can't compute a percentage
        body = b"some bytes"
        fake = _FakeHttpResponse(body, content_length=None)

        # Act
        with (
            patch("ems_analyst_mcp.seed.urllib.request.urlopen", return_value=fake),
            caplog.at_level(logging.INFO, logger="ems_analyst_mcp.seed"),
        ):
            actual = _download_with_progress("https://example.invalid/x.gz", "vector")

        # Assert
        assert actual == body
        assert not any("seed progress:" in r.message for r in caplog.records)
