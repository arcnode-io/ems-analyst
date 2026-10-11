"""Unit tests for load_config — reads the real cfg.yml shipped in the package."""

from ipaddress import IPv4Address
from pathlib import Path

import pytest

from .config import load_config

_PACKAGE_DIR = Path(__file__).parent.parent


class TestLoadConfig:
    """AAA — ENV picks the cfg.yml block; load_config opens ./cfg.yml."""

    def test_device_demo_binds_all_interfaces(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A bridged container can't be reached on its own loopback."""
        # Arrange
        monkeypatch.chdir(_PACKAGE_DIR)
        monkeypatch.setenv("ENV", "device-demo")

        # Act
        actual = load_config()

        # Assert
        assert actual.host.is_unspecified  # 0.0.0.0 — all interfaces
        assert actual.port == 8000
        assert actual.e2e is False

    def test_unknown_env_still_falls_back_to_local(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unrecognized ENV (e.g. ENV=ci in pipelines) lands on the local block."""
        # Arrange
        monkeypatch.chdir(_PACKAGE_DIR)
        monkeypatch.setenv("ENV", "ci")

        # Act
        actual = load_config()

        # Assert
        assert actual.host == IPv4Address("127.0.0.1")
