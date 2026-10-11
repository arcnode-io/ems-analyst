"""Unit tests for ImportProgress — the 'seed import:' lines the wizard parses.

The download is reported by `seed progress:`; applying a big dump to the
database is the long, silent part (an ISO install sat at "100%" for
minutes), so the apply loop reports its own percent.
"""

import logging

import pytest

from .seed_progress import ImportProgress

_LOG = logging.getLogger("ems_analyst_mcp.seed")


def _lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.message for r in caplog.records if r.message.startswith("seed import:")]


class TestImportProgress:
    """AAA — one line per whole percent crossed, measured in committed statements."""

    def test_logs_each_whole_percent_with_the_contract_shape(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Matches platform's contract: label, integer %, 'A of B statements'."""
        # Arrange
        progress = ImportProgress(_LOG, "graph", total=100, granularity_pct=1)

        # Act
        with caplog.at_level(logging.INFO, logger="ems_analyst_mcp.seed"):
            for _ in range(100):
                progress.advance(1)

        # Assert
        lines = _lines(caplog)
        assert len(lines) == 100
        assert lines[0] == "seed import: graph 1% (1 of 100 statements)"
        assert lines[-1] == "seed import: graph 100% (100 of 100 statements)"

    def test_batches_straddling_percent_boundaries_log_once_per_new_percent(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A real graph commits 50 statements per batch (0.5% of 10 000)."""
        # Arrange
        progress = ImportProgress(_LOG, "graph", total=10_000, granularity_pct=1)

        # Act
        with caplog.at_level(logging.INFO, logger="ems_analyst_mcp.seed"):
            for _ in range(200):
                progress.advance(50)

        # Assert — every other batch reaches a new whole percent, none skipped
        lines = _lines(caplog)
        assert len(lines) == 100
        assert lines[0] == "seed import: graph 1% (100 of 10000 statements)"
        assert lines[-1] == "seed import: graph 100% (10000 of 10000 statements)"

    def test_coarser_granularity_logs_the_bucket_not_the_raw_percent(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """granularity 10: 25% applied is reported as the 20% bucket."""
        # Arrange
        progress = ImportProgress(_LOG, "vector", total=20, granularity_pct=10)

        # Act
        with caplog.at_level(logging.INFO, logger="ems_analyst_mcp.seed"):
            for _ in range(4):
                progress.advance(5)

        # Assert — 25% -> 20, 50% -> 50, 75% -> 70, 100% -> 100
        assert _lines(caplog) == [
            "seed import: vector 20% (5 of 20 statements)",
            "seed import: vector 50% (10 of 20 statements)",
            "seed import: vector 70% (15 of 20 statements)",
            "seed import: vector 100% (20 of 20 statements)",
        ]

    def test_nothing_is_logged_before_a_statement_has_committed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The percent only moves when advance() is called — never ahead of the DB."""
        # Arrange + Act
        with caplog.at_level(logging.INFO, logger="ems_analyst_mcp.seed"):
            ImportProgress(_LOG, "graph", total=100, granularity_pct=1)

        # Assert
        assert _lines(caplog) == []
