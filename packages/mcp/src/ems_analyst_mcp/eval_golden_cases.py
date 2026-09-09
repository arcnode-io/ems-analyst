"""Golden retrieval query set for the knowledge table — task zero.

Per handoff §4 (2026-09-09): none of the RRF/chunking findings can be
validated on subjective impression — the handoff's own two retractions
prove that. Every `expected_chunk_ids` entry here was hand-verified
against the live `knowledge` table (see git history / session notes for
the SQL used) before being written down.

In-corpus cases only — see eval_golden_cases_negative.py for the
deliberately out-of-corpus set (split to keep both files under the
200-line cap; `eval_retrieval.py` runs the union of both).

Categories roughly follow handoff §4, with NREL/Basso dropped (that book
was never actually seeded — see the out-of-corpus case that stands in
for it) and Modbus/SNMPv3/NERC-CIP added: they're large, well-represented
parts of the real corpus the original 7 categories didn't touch.
"""

from pydantic import BaseModel


class GoldenQuery(BaseModel):
    """One golden-set query + its known-correct source chunk(s).

    `note` records *why* — the human-readable justification a reviewer
    can check against the live table without re-deriving it.
    """

    name: str
    query: str
    category: str
    expected_chunk_ids: list[str]
    note: str


GOLDEN_QUERIES: list[GoldenQuery] = [
    # --- DNP3 / IEC 60870-5 (Clarke) — the mushy-chunk book from §2 ---
    GoldenQuery(
        name="dnp3_min_unsol_event_delay",
        query="Min_Unsol_Event_Tx_Delay",
        category="dnp3",
        expected_chunk_ids=["1209"],
        note="Contains the literal term (as 'Min Unsol Event Tx Delay') plus "
        "'Notification Event Delay' and 'Class x Min Events'. The exact §3 "
        "probe query — RRF currently loses this to a Redfish chunk at rank 1.",
    ),
    GoldenQuery(
        name="dnp3_data_link_confirm_mode",
        query="What are the DNP3 Data Link Confirm Mode options and which is typically used?",
        category="dnp3",
        expected_chunk_ids=["1210"],
        note="'Sometimes, Never, Always' — 'usually set to Sometimes' per the "
        "Data Link Confirm Mode section.",
    ),
    # --- Redfish (DSP0266 / DSP0268 / DGX / OCP) — dominant, well-chunked ---
    GoldenQuery(
        name="redfish_service_root_uri",
        query="What is the exact URI path of the Redfish service root?",
        category="redfish",
        expected_chunk_ids=["1269"],
        note="Worked example: https://mgmt.vendor.com/redfish/v1/Systems/1 -> "
        "'redfish/v1 is the service root and version.'",
    ),
    GoldenQuery(
        name="redfish_odata_type_schema",
        query="Which property in a Redfish response determines the schema that defines the resource?",
        category="redfish",
        expected_chunk_ids=["1558"],
        note="'The schema that defines a resource can be determined from the "
        "value of the @odata.type property returned in every Redfish response.'",
    ),
    GoldenQuery(
        name="redfish_odata_id_required",
        query="Which OData property is required and holds the unique identifier for a Redfish resource?",
        category="redfish",
        expected_chunk_ids=["1561"],
        note="@odata.id row: 'required... unique identifier for the resource... "
        "form defined in the Redfish specification.'",
    ),
    GoldenQuery(
        name="dgx_b300_redfish_default_enabled",
        query="Is Redfish enabled by default on the NVIDIA DGX B300 BMC?",
        category="redfish",
        expected_chunk_ids=["3233"],
        note="'Redfish support is enabled by default in the DGX B300 BMC and the BIOS.'",
    ),
    GoldenQuery(
        name="ocp_baseline_scope",
        query="What does the OCP Baseline Hardware Management Profile Usage Guide define?",
        category="redfish",
        expected_chunk_ids=["3280"],
        note="Document overview chunk — 'requirements and usage examples for "
        "the OCP Baseline Hardware Management API v1.1.'",
    ),
    # --- BESS (cell-to-grid) — thin (6 chunks), also large/mushy ---
    GoldenQuery(
        name="bess_fifth_standard_capacity",
        query="What is the BESS capacity in MWac and MWh of the Fifth Standard project?",
        category="bess",
        expected_chunk_ids=["3502"],
        note="'nameplate capacity of 137 MWac and 548 MWh (4-hour duration)... "
        "AC-coupled with a 150 MWac PV plant.'",
    ),
    # --- Market/economics (Kirschen & Strbac) ---
    GoldenQuery(
        name="power_econ_borduria_syldavia_flow",
        query="In the Borduria/Syldavia interconnection example, what is the unconstrained flow?",
        category="power_economics",
        expected_chunk_ids=["586"],
        note="'The unconstrained flow in the interconnection is then: F = 933.33 MW (8.24)'",
    ),
    # --- HMI design (Hollifield) ---
    GoldenQuery(
        name="hmi_high_performance_graphics_gray",
        query="What color are backgrounds in a High Performance HMI designed to minimize glare?",
        category="hmi",
        expected_chunk_ids=["675"],
        note="'Gray backgrounds are used to minimize glare, along with a "
        "generally a low-contrast depiction.'",
    ),
    # --- Modbus — strong-coverage protocol, not in handoff §4 but large ---
    GoldenQuery(
        name="modbus_mask_write_register_fc",
        query="What Modbus function code implements Mask Write Register?",
        category="modbus",
        expected_chunk_ids=["1126"],
        note="Request Function code 1 Byte 0x16 — Mask Write Register uses AND/OR masks.",
    ),
    # --- ICS security (NIST SP 800-82r3) ---
    GoldenQuery(
        name="nist_80082_zta_purdue_levels",
        query="Per NIST SP 800-82r3, which Purdue model levels are realistic targets for Zero Trust in OT?",
        category="ics_security",
        expected_chunk_ids=["299"],
        note="'organizations should consider applying a ZTA to compatible "
        "devices... Purdue model Levels 3, 4, 5, and the OT DMZ.'",
    ),
    # --- NERC CIP — large real corpus slice (~200 chunks), not in §4 ---
    GoldenQuery(
        name="cip007_password_min_length",
        query="Per CIP-007-7.1, what is the minimum password length for password-only authentication?",
        category="nerc_cip",
        expected_chunk_ids=["141"],
        note="'Password length that is, at least, the lesser of eight "
        "characters or the maximum length supported by the Applicable Systems.'",
    ),
    GoldenQuery(
        name="cip005_esp_default_deny",
        query="Per CIP-005-8, what is the default policy for routable protocol traffic through the ESP?",
        category="nerc_cip",
        expected_chunk_ids=["61"],
        note="'Permit only needed routable protocol communications... and deny "
        "all other routable protocol communications, through the ESP.'",
    ),
    GoldenQuery(
        name="nerc_glossary_bes_cyber_asset_minutes",
        query="Per the NERC Glossary, within how many minutes must unavailability impact operation to qualify as a BES Cyber Asset?",
        category="nerc_cip",
        expected_chunk_ids=["233"],
        note="'within 15 minutes of its required operation, misoperation, or "
        "non-operation, adversely impact... the Bulk Electric System.'",
    ),
]
