"""Unit tests for build_topology — DtmView → TableSpec."""

from ..device_api import DtmView
from ..schemas import TableSpec
from .topology_tool import build_topology

_DTM = {
    "deployment_uuid": "00000000-0000-0000-0000-000000000001",
    "devices": {
        "bess_module_01": {
            "device_id": "bess_module_01",
            "template": "bess_module",
            "parent": None,
            "display_name": "BESS-01",
        },
        "cdu_01": {
            "device_id": "cdu_01",
            "template": "cdu",
            "parent": "compute_module_01",
            "display_name": "CDU-01",
        },
    },
}


def test_build_topology_renders_device_table() -> None:
    # Arrange
    dtm = DtmView.model_validate(_DTM)

    # Act
    art = build_topology(dtm)

    # Assert
    assert art.kind == "table"
    assert isinstance(art.spec, TableSpec)
    assert len(art.spec.rows) == 2
    # sorted by device_id — bess before cdu
    assert art.spec.rows[0]["device"] == "bess_module_01"
    assert art.spec.rows[1]["parent"] == "compute_module_01"


def test_build_topology_empty_dtm_returns_error() -> None:
    # Arrange
    dtm = DtmView.model_validate(
        {"deployment_uuid": "00000000-0000-0000-0000-000000000001", "devices": {}}
    )

    # Act
    art = build_topology(dtm)

    # Assert
    assert art.kind == "error"
