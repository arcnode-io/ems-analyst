"""Energy-news RSS aggregator.

Fan-out fetch across the major energy RSS feeds (EIA Today in Energy,
EIA press releases, OilPrice, Utility Dive), feedparser-decoded,
summarised down to headline + link + pub time so the LLM gets compact
context.

Tests pook-mock every URL — see [[feedback-llm-calls]] for the rule.
"""

import asyncio
from typing import Final

import feedparser
import httpx

# All four verified live + free (no key, no signup, no paywall). EIA is
# the authoritative US energy source; OilPrice covers commodities;
# Utility Dive covers grid + power markets (PJM/CAISO/ERCOT).
ENERGY_FEED_URLS: Final[tuple[str, ...]] = (
    "https://www.eia.gov/rss/todayinenergy.xml",
    "https://www.eia.gov/rss/press_rss.xml",
    "https://oilprice.com/rss/main",
    "https://www.utilitydive.com/feeds/news/",
)
HTTP_TIMEOUT_SEC: Final[float] = 10.0
PER_FEED_HEADLINE_CAP: Final[int] = 5


async def get_energy_news(limit: int = 10) -> str:
    """Aggregate recent energy-news headlines across RSS feeds.

    Args:
        limit: Max total headlines to return across all feeds.

    Returns:
        Multi-line text: "<source> — <headline> (<pub_date>)" per row, or
        a friendly message if every feed failed.
    """
    fetched = await asyncio.gather(
        *(_fetch_feed(url) for url in ENERGY_FEED_URLS),
        return_exceptions=False,
    )
    headlines: list[str] = []
    for source_url, body in fetched:
        if body is None:
            continue
        headlines.extend(_extract_headlines(source_url, body))
    if not headlines:
        return "Energy news feeds unavailable — no headlines fetched."
    return "\n".join(headlines[:limit])


async def _fetch_feed(url: str) -> tuple[str, str | None]:
    """Best-effort fetch; returns (url, body or None on any error)."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=HTTP_TIMEOUT_SEC)
            resp.raise_for_status()
            return url, resp.text
    except (httpx.HTTPError, httpx.RequestError):
        return url, None


def _extract_headlines(source_url: str, body: str) -> list[str]:
    """feedparser → list of formatted lines, capped per feed."""
    parsed = feedparser.parse(body)
    source = parsed.feed.get("title", source_url)
    out: list[str] = []
    for entry in parsed.entries[:PER_FEED_HEADLINE_CAP]:
        title = entry.get("title", "<no title>")
        pub = entry.get("published", "")
        out.append(f"{source} — {title} ({pub})" if pub else f"{source} — {title}")
    return out
