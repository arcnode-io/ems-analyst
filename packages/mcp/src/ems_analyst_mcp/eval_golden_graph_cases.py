"""Relationship retrieval gates for the compact graph, separate from flat RAG.

Fact IDs were checked against the retained extraction and deterministic
version/incident anchors. Every required group must have evidence in top ten;
one related fact is insufficient to pass a multi-hop question.
"""

from .eval_golden_cases import GoldenQuery

GRAPH_GOLDEN_QUERIES = [
    GoldenQuery(
        name="cip006_supersession",
        query="What replaced CIP-006-7?",
        category="nerc_cip",
        query_shape="cross_document_supersession",
        expected_chunk_ids=["801470c5-ee34-52c4-b0d5-4c21d6e61fa8"],
        required_fact_groups=[["801470c5-ee34-52c4-b0d5-4c21d6e61fa8"]],
        note="Two markdown frontmatters join on 2026-03-19; CIP-006-7.1 replaces CIP-006-7.",
    ),
    GoldenQuery(
        name="cip003_supersession",
        query="What replaced CIP-003-10?",
        category="nerc_cip",
        query_shape="cross_document_supersession",
        expected_chunk_ids=["1e0c3e4f-1150-5ee3-926d-9a50a80ee886"],
        required_fact_groups=[["1e0c3e4f-1150-5ee3-926d-9a50a80ee886"]],
        note="Last active day 2026-05-25 joins next effective day 2026-05-26, CIP-003-11.",
    ),
    GoldenQuery(
        name="cip012_supersession",
        query="What replaced CIP-012-1?",
        category="nerc_cip",
        query_shape="cross_document_supersession",
        expected_chunk_ids=["46903e07-cb40-5266-8b84-b3c48f43a06d"],
        required_fact_groups=[["46903e07-cb40-5266-8b84-b3c48f43a06d"]],
        note="Last active day 2026-06-30 joins next effective day 2026-07-01, CIP-012-2.",
    ),
    GoldenQuery(
        name="bess_control_hierarchy",
        query="How do BMS EMS PPC SCADA and fleet controls coordinate in a BESS?",
        category="bess",
        query_shape="multi_hop_control_chain",
        expected_chunk_ids=[
            "29dfc0ec-2119-40e9-a7eb-9c8326a19321",
            "5adece43-5f39-4d4a-8eb7-044fa0c367ff",
            "33e7ee56-bffd-4d4c-a49a-ef02134e550a",
        ],
        required_fact_groups=[
            [
                "29dfc0ec-2119-40e9-a7eb-9c8326a19321",
                "87581a64-c9e3-45de-88ec-e05fc6b8daef",
                "92e960e6-27b1-4a4b-a591-398d0618eaeb",
                "ba53dcf4-3be4-4adc-af1b-d9f4ed8ad9f1",
            ],
            [
                "5adece43-5f39-4d4a-8eb7-044fa0c367ff",
                "1bdbcd7e-e1e2-4eb2-9eca-b3d46fe24264",
                "6a9d2d06-0f9d-48b4-8b4b-7f8e4faa16dc",
            ],
            [
                "33e7ee56-bffd-4d4c-a49a-ef02134e550a",
                "e0ec381f-4228-4581-bcd7-51189c34e5f6",
            ],
        ],
        note="BESS §5 intro and §5.4: EMS aggregates BMS data, PPC coordinates EMS with SCADA, fleet controls coordinate multiple batteries.",
    ),
    GoldenQuery(
        name="bess_vbb_incident_chain",
        query="Why did limited telemetry during commissioning contribute to the Victorian Big Battery fire?",
        category="bess",
        query_shape="multi_hop_control_chain",
        expected_chunk_ids=[
            "b3d9edf9-89ee-543b-a55a-b4377cf6cb17",
            "f9c7837e-6323-5695-bed6-e2a063d136de",
            "f879337b-03ba-5e9f-9434-f35f8f341ea3",
        ],
        required_fact_groups=[
            ["b3d9edf9-89ee-543b-a55a-b4377cf6cb17"],
            ["f9c7837e-6323-5695-bed6-e2a063d136de"],
            ["f879337b-03ba-5e9f-9434-f35f8f341ea3"],
        ],
        note="BESS §5.1 reports limited telemetry/safety functionality during commissioning, its contribution to fire, and two destroyed enclosures.",
    ),
]
