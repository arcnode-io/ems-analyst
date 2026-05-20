"""Unit tests for HMI device-id → energy category mapping."""

from .topology import category_of, devices_in_category, template_of


def test_template_of_bess() -> None:
    assert template_of("bess_module_01") == "bess_module"


def test_template_of_compute() -> None:
    assert template_of("compute_module_01") == "compute_module"


def test_template_of_market() -> None:
    assert template_of("market_01") == "market"


def test_template_of_unknown_returns_none() -> None:
    assert template_of("ghost_device_99") is None


def test_category_of_bess() -> None:
    assert category_of("bess_module_01") == "bess"


def test_category_of_revenue_meter() -> None:
    assert category_of("revenue_meter_01") == "grid_intertie"


def test_category_of_cdu() -> None:
    assert category_of("cdu_01") == "compute_support"


def test_devices_in_category_filters_and_sorts() -> None:
    # Arrange
    devs = ["compute_module_01", "bess_module_02", "bess_module_01", "cdu_01"]

    # Act
    actual = devices_in_category(devs, "bess")

    # Assert — sorted alphabetically, filtered to bess
    assert actual == ["bess_module_01", "bess_module_02"]
