"""Unit tests for compute_forecast_accuracy — pure arithmetic, no network."""

from datetime import UTC, datetime, timedelta

from .forecast_accuracy import compute_forecast_accuracy

_T0 = datetime(2026, 1, 1, 0, tzinfo=UTC)


def _hours(*values: float) -> dict[datetime, float]:
    """{t0+i hours: values[i]} for i in range(len(values))."""
    return {_T0 + timedelta(hours=i): v for i, v in enumerate(values)}


class TestComputeForecastAccuracy:
    """Hand-verified worked examples — exact values matter for a demo."""

    def test_full_overlap_computes_signed_and_absolute_error(self) -> None:
        # Arrange — errors (actual - forecast): +1, -2, +6, 0
        forecast = _hours(30, 32, 34, 36)
        actual = _hours(31, 30, 40, 36)

        # Act
        stats = compute_forecast_accuracy(forecast, actual)

        # Assert
        assert stats is not None
        assert stats.hours_compared == 4
        assert stats.forecast_avg == 33.0
        assert stats.actual_avg == 34.25
        assert stats.mean_bias == 1.25
        assert stats.mae == 2.25
        assert stats.max_abs_error == 6.0
        assert stats.max_error_at == _T0 + timedelta(hours=2)

    def test_partial_overlap_excludes_unmatched_hours(self) -> None:
        # Arrange — forecast covers 4 hours, actual only the first 2
        forecast = _hours(30, 32, 34, 36)
        actual = {ts: v for ts, v in _hours(31, 30, 999, 999).items() if v != 999}

        # Act
        stats = compute_forecast_accuracy(forecast, actual)

        # Assert — only the 2 overlapping hours count
        assert stats is not None
        assert stats.hours_compared == 2
        assert stats.forecast_avg == 31.0
        assert stats.actual_avg == 30.5

    def test_no_overlap_returns_none(self) -> None:
        # Arrange — disjoint time ranges
        forecast = _hours(30, 32)
        actual = {_T0 + timedelta(hours=100): 50.0}

        # Act + Assert
        assert compute_forecast_accuracy(forecast, actual) is None
