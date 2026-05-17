"""Corpus-grounded eval cases for the with-MCP harness.

Picked so the LLM CAN'T fabricate the expected keyword from training
alone — specific numeric values, exact URI paths, and book-specific
phrasing. If RAG is broken, these cases score 0.0 (or 0.25 with the
training-data-leak penalty).
"""

from .eval import EvalCase

MCP_CASES: list[EvalCase] = [
    EvalCase(
        name="modbus_fc3_max_quantity",
        prompt=(
            "Search the knowledge base. Per the Modbus Application Protocol "
            "Specification, what is the maximum quantity of holding registers "
            "you can read in a single Function Code 3 request?"
        ),
        expect_artifact=None,
        expect_keyword="125",
    ),
    EvalCase(
        name="modbus_exception_code_illegal_data_address",
        prompt=(
            "Search the knowledge base. In the Modbus exception response, "
            "what numeric code (decimal 0-255) indicates ILLEGAL DATA ADDRESS?"
        ),
        expect_artifact=None,
        expect_keyword="02",
    ),
    EvalCase(
        name="snmpv3_usm_auth_algorithms",
        prompt=(
            "Search the knowledge base. Per the SNMPv3 USM RFC, which "
            "authentication protocols are defined for HMAC?"
        ),
        expect_artifact=None,
        expect_keyword="sha",
    ),
    EvalCase(
        name="redfish_service_root_uri",
        prompt=(
            "Search the knowledge base. Per DSP0266 Redfish, what is the "
            "exact URI path of the Service Root that every Redfish client "
            "GETs first?"
        ),
        expect_artifact=None,
        expect_keyword="/redfish/v1",
    ),
]
