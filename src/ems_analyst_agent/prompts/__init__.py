"""Bundled prompt loader.

Prompts live as .md files next to this module so they ship in the wheel
(same pattern as cfg.yml — package-data entry in pyproject.toml). Reading
via importlib.resources keeps the loader installable-as-dep friendly.
"""

from importlib import resources
from typing import Final, Literal

_PKG: Final[str] = __package__ or "ems_analyst_agent.prompts"

PromptCategory = Literal["tasks", "responses"]


def load_system_prompt() -> str:
    """Read the analyst persona system prompt."""
    return _read("system.md")


def load_prompt(category: PromptCategory, name: str) -> str:
    """Read prompts/<category>/<name>.md."""
    return _read(f"{category}/{name}.md")


def _read(rel_path: str) -> str:
    # Reason: as_file → guaranteed real path even when shipped inside a zipped wheel.
    parts = rel_path.split("/")
    resource = resources.files(_PKG).joinpath(*parts)
    with resources.as_file(resource) as path:
        return path.read_text(encoding="utf-8")
