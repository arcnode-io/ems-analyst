"""Unit tests for geopolitical.py — business logic only.

Full-stack HTTP integration lives in `tests/test_integration.py` per
[[feedback-test-taxonomy]].
"""

from .geopolitical import _extract_headlines


_SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Fake Energy Feed</title>
  <link>https://example.com</link>
  <description>test</description>
  <item>
    <title>OPEC+ surprise output cut sends Brent to $95</title>
    <link>https://example.com/opec</link>
    <description>Brent crude jumped 4%</description>
    <pubDate>Sat, 16 May 2026 12:00:00 GMT</pubDate>
  </item>
  <item>
    <title>European gas storage at 78% ahead of summer</title>
    <link>https://example.com/gas</link>
    <description>TTF eased</description>
    <pubDate>Sat, 16 May 2026 09:00:00 GMT</pubDate>
  </item>
</channel></rss>"""


class TestExtractHeadlines:
    """AAA tests for the feedparser → formatted-line helper."""

    def test_extracts_titles_and_pub_dates(self) -> None:
        # Arrange + Act
        actual = _extract_headlines("https://example.com", _SAMPLE_RSS)

        # Assert
        assert len(actual) == 2
        assert any("OPEC+" in line for line in actual)
        assert any("16 May 2026" in line for line in actual)
        assert all(line.startswith("Fake Energy Feed — ") for line in actual)

    def test_empty_feed_returns_empty(self) -> None:
        # Arrange
        empty_rss = """<?xml version="1.0"?><rss version="2.0"><channel>
            <title>Empty</title></channel></rss>"""

        # Act
        actual = _extract_headlines("https://example.com", empty_rss)

        # Assert
        assert actual == []
