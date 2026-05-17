"""Render-spec contract between analyst-agent + ems-hmi.

Mirrors `/tmp/HANDOFF-analyst-backend.md` 1:1. Pydantic-side fields are
snake_case; JSON-side fields are camelCase (TS contract). Always dump
with `by_alias=True` over the wire.

Adding a new artifact variant: extend `_AnyArtifactSpec` + add to
`AnalystArtifact` discriminator. The HMI's TS union must mirror.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class _Camel(BaseModel):
    """Base — alias_generator + populate_by_name → camelCase JSON, snake-case attrs."""

    model_config = ConfigDict(
        alias_generator=lambda field_name: _to_camel(field_name),
        populate_by_name=True,
        extra="forbid",
    )


def _to_camel(snake: str) -> str:
    """foo_bar → fooBar."""
    head, *tail = snake.split("_")
    return head + "".join(part.capitalize() for part in tail)


# ── axes + leaf types ──────────────────────────────────────────────────────

XAxisKind = Literal["time", "category", "numeric"]
Severity = Literal["warn", "alarm"]
RowSeverity = Literal["ok", "warn", "alarm"]
ToolErrorCode = Literal[
    "not_found", "historian_down", "invalid_input", "rate_limited", "unknown"
]
Align = Literal["left", "right"]


class LineAxis(_Camel):
    label: str
    kind: XAxisKind


class UnitAxis(_Camel):
    label: str
    unit: str


class BarAxis(_Camel):
    label: str
    categories: list[str]


class LinePoint(_Camel):
    x: float | str
    y: float | None


class LineSeries(_Camel):
    label: str
    color: str | None = None
    points: list[LinePoint]
    # Reserved per HMI handoff Q5 — citation source. Always None in v1.
    source_topic: str | None = None


class LineThreshold(_Camel):
    label: str
    y: float
    severity: Severity


class BarSeries(_Camel):
    label: str
    color: str | None = None
    values: list[float]


class TableColumn(_Camel):
    key: str
    label: str
    align: Align | None = None
    unit: str | None = None


class PieSlice(_Camel):
    label: str
    value: float
    color: str | None = None


class ToolTraceEntry(_Camel):
    tool: str
    args: dict[str, object]
    outcome: Literal["ok", "error"]
    ms: int


# ── artifact specs ─────────────────────────────────────────────────────────


class LineSpec(_Camel):
    title: str
    x_axis: LineAxis
    y_axis: UnitAxis
    series: list[LineSeries]
    thresholds: list[LineThreshold] | None = None
    data_as_of: str


class BarSpec(_Camel):
    title: str
    x_axis: BarAxis
    y_axis: UnitAxis
    series: list[BarSeries]
    stacked: bool | None = None
    data_as_of: str


class TableSpec(_Camel):
    title: str
    columns: list[TableColumn]
    rows: list[dict[str, str | float | None]]
    row_severity: list[RowSeverity | None] | None = None
    data_as_of: str


class PieSpec(_Camel):
    title: str
    unit: str
    slices: list[PieSlice]
    data_as_of: str


class ToolError(_Camel):
    code: ToolErrorCode
    message: str
    data_as_of: str


# ── discriminated union ────────────────────────────────────────────────────


class _LineArtifact(_Camel):
    kind: Literal["line"]
    spec: LineSpec


class _BarArtifact(_Camel):
    kind: Literal["bar"]
    spec: BarSpec


class _TableArtifact(_Camel):
    kind: Literal["table"]
    spec: TableSpec


class _PieArtifact(_Camel):
    kind: Literal["pie"]
    spec: PieSpec


class _ErrorArtifact(_Camel):
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
        return self.root.kind

    @property
    def spec(
        self,
    ) -> "LineSpec | BarSpec | TableSpec | PieSpec | ToolError":
        return self.root.spec


# ── message wrapper ────────────────────────────────────────────────────────


class TextContent(_Camel):
    type: Literal["text"]
    text: str


class ArtifactContent(_Camel):
    type: Literal["artifact"]
    artifact: _ArtifactRoot  # serialized inline with discriminator on kind


AnalystContent = Annotated[
    TextContent | ArtifactContent,
    Field(discriminator="type"),
]


class AnalystMessage(_Camel):
    role: Literal["user", "assistant"]
    content: list[AnalystContent]
    tool_trace: list[ToolTraceEntry] | None = None
