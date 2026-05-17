"""Render-spec contract between analyst-agent + ems-hmi.

Mirrors `/tmp/HANDOFF-analyst-backend.md` 1:1. Pydantic-side fields are
snake_case; JSON-side fields are camelCase (TS contract). Always dump
with `by_alias=True` over the wire.

Adding a new artifact variant: extend `_ArtifactRoot` + add to
`AnalystArtifact` discriminator. The HMI's TS union must mirror.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


def _to_camel(snake: str) -> str:
    """foo_bar → fooBar."""
    head, *tail = snake.split("_")
    return head + "".join(part.capitalize() for part in tail)


class _Camel(BaseModel):
    """Base — alias_generator + populate_by_name → camelCase JSON, snake-case attrs."""

    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="forbid",
    )


# ── axes + leaf types ──────────────────────────────────────────────────────

XAxisKind = Literal["time", "category", "numeric"]
Severity = Literal["warn", "alarm"]
RowSeverity = Literal["ok", "warn", "alarm"]
ToolErrorCode = Literal[
    "not_found", "historian_down", "invalid_input", "rate_limited", "unknown"
]
Align = Literal["left", "right"]


class LineAxis(_Camel):
    """X-axis descriptor for a LineSpec — label + kind discriminator."""

    label: str
    kind: XAxisKind


class UnitAxis(_Camel):
    """Y-axis (or generic) descriptor with a unit label."""

    label: str
    unit: str


class BarAxis(_Camel):
    """X-axis descriptor for a BarSpec — label + fixed category list."""

    label: str
    categories: list[str]


class LinePoint(_Camel):
    """One (x, y) point in a LineSeries; y may be None for no-data."""

    x: float | str
    y: float | None


class LineSeries(_Camel):
    """One series on a line chart — label, optional color, list of points."""

    label: str
    color: str | None = None
    points: list[LinePoint]
    # Reserved per HMI handoff Q5 — citation source. Always None in v1.
    source_topic: str | None = None


class LineThreshold(_Camel):
    """Reference line on a LineSpec (alarm/warn bound)."""

    label: str
    y: float
    severity: Severity


class BarSeries(_Camel):
    """One bar series — parallel to LineSeries but values, not points."""

    label: str
    color: str | None = None
    values: list[float]


class TableColumn(_Camel):
    """Column descriptor for TableSpec — key + label + optional align/unit."""

    key: str
    label: str
    align: Align | None = None
    unit: str | None = None


class PieSlice(_Camel):
    """One slice of a PieSpec — label + numeric value."""

    label: str
    value: float
    color: str | None = None


class ToolTraceEntry(_Camel):
    """One row of the optional toolTrace for transparency UIs."""

    tool: str
    args: dict[str, object]
    outcome: Literal["ok", "error"]
    ms: int


# ── artifact specs ─────────────────────────────────────────────────────────


class LineSpec(_Camel):
    """Line chart render spec (timeseries or numeric)."""

    title: str
    x_axis: LineAxis
    y_axis: UnitAxis
    series: list[LineSeries]
    thresholds: list[LineThreshold] | None = None
    data_as_of: str


class BarSpec(_Camel):
    """Bar chart render spec; supports grouped or stacked."""

    title: str
    x_axis: BarAxis
    y_axis: UnitAxis
    series: list[BarSeries]
    stacked: bool | None = None
    data_as_of: str


class TableSpec(_Camel):
    """Table render spec — heterogeneous rows + optional per-row severity."""

    title: str
    columns: list[TableColumn]
    rows: list[dict[str, str | float | None]]
    row_severity: list[RowSeverity | None] | None = None
    data_as_of: str


class PieSpec(_Camel):
    """Pie / donut chart render spec."""

    title: str
    unit: str
    slices: list[PieSlice]
    data_as_of: str


class ToolError(_Camel):
    """Error variant — HMI renders an inline error card with `code` chip."""

    code: ToolErrorCode
    message: str
    data_as_of: str


# ── discriminated union ────────────────────────────────────────────────────


class _LineArtifact(_Camel):
    """Line variant of AnalystArtifact union (discriminator: kind='line')."""

    kind: Literal["line"]
    spec: LineSpec


class _BarArtifact(_Camel):
    """Bar variant of AnalystArtifact union (discriminator: kind='bar')."""

    kind: Literal["bar"]
    spec: BarSpec


class _TableArtifact(_Camel):
    """Table variant of AnalystArtifact union (discriminator: kind='table')."""

    kind: Literal["table"]
    spec: TableSpec


class _PieArtifact(_Camel):
    """Pie variant of AnalystArtifact union (discriminator: kind='pie')."""

    kind: Literal["pie"]
    spec: PieSpec


class _ErrorArtifact(_Camel):
    """Error variant of AnalystArtifact union (discriminator: kind='error')."""

    kind: Literal["error"]
    spec: ToolError


_ArtifactRoot = Annotated[
    _LineArtifact | _BarArtifact | _TableArtifact | _PieArtifact | _ErrorArtifact,
    Field(discriminator="kind"),
]


class AnalystArtifact(RootModel[_ArtifactRoot]):
    """Discriminated wrapper so consumers can `model_validate`/`model_dump`."""

    @property
    def kind(self) -> str:
        """Discriminator value: line | bar | table | pie | error."""
        return self.root.kind

    @property
    def spec(
        self,
    ) -> "LineSpec | BarSpec | TableSpec | PieSpec | ToolError":
        """Routed sub-spec for the active kind."""
        return self.root.spec


# ── message wrapper ────────────────────────────────────────────────────────


class TextContent(_Camel):
    """Plain-text segment of AnalystMessage content list."""

    type: Literal["text"]
    text: str


class ArtifactContent(_Camel):
    """Artifact-card segment of AnalystMessage content list."""

    type: Literal["artifact"]
    artifact: _ArtifactRoot  # serialized inline with discriminator on kind


AnalystContent = Annotated[
    TextContent | ArtifactContent,
    Field(discriminator="type"),
]


class AnalystMessage(_Camel):
    """One assistant turn: role + interleaved text/artifact content + tool trace."""

    role: Literal["user", "assistant"]
    content: list[AnalystContent]
    tool_trace: list[ToolTraceEntry] | None = None
