"""The site's own facts, rendered into the system prompt.

The model answers "where/what is this site" questions from here rather than
searching tools for facts the deployment already knows. A fact that isn't
configured renders as "unknown" — never a guessed value.
"""


def site_context_text(site_id: str, settlement_point: str, location: str | None) -> str:
    """Site facts block: id, settlement point, location (or 'unknown')."""
    return (
        "Site facts for this deployment:\n"
        f"- Site id: {site_id}.\n"
        f"- Settlement point: {settlement_point}.\n"
        f"- Site location: {location or 'unknown'}."
    )
