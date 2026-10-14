"""Unit tests for site_context_text — the site's own facts, rendered for the prompt."""

from .site_context import site_context_text


class TestSiteContextText:
    """AAA — every configured site fact reaches the model; unset ones are marked unknown."""

    def test_includes_site_location_when_configured(self) -> None:
        # Arrange + Act
        actual = site_context_text(
            site_id="device_demo_site",
            settlement_point="HB_NORTH",
            location="Dallas, TX",
        )

        # Assert
        assert "Site location: Dallas, TX." in actual

    def test_marks_location_unknown_when_not_configured(self) -> None:
        # Arrange + Act — never invent a location for a site that didn't set one
        actual = site_context_text(
            site_id="device_demo_site", settlement_point="HB_NORTH", location=None
        )

        # Assert
        assert "Site location: unknown." in actual

    def test_includes_site_id_and_settlement_point(self) -> None:
        # Arrange + Act
        actual = site_context_text(
            site_id="device_demo_site", settlement_point="HB_NORTH", location=None
        )

        # Assert
        assert "Site id: device_demo_site." in actual
        assert "Settlement point: HB_NORTH." in actual
