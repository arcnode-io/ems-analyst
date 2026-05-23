"""RFC 3339 UTC timestamp formatting — one helper, used stack-wide.

The whole arcnode stack speaks ISO-8601 UTC with a `Z` suffix. `Z` is
deliberate over `+00:00`: the `+` decodes to a space in a URL query
string and FastAPI then rejects the datetime, so `Z` is what survives
transport.
"""

from datetime import UTC, datetime

_ISO_Z: str = "%Y-%m-%dT%H:%M:%SZ"


def iso_z(ts: datetime | None = None) -> str:
    """Format a datetime (or now) as `YYYY-MM-DDTHH:MM:SSZ`."""
    return (ts or datetime.now(UTC)).strftime(_ISO_Z)
