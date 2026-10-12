"""Answer and routing checks for full markdown plus the compact relationship graph."""

from dataclasses import dataclass

from ems_analyst_mcp.eval_golden_cases import QueryShape


@dataclass(frozen=True)
class DomainCase:
    """A domain question with required answer concepts and a retrieval path."""

    name: str
    query_shape: QueryShape
    prompt: str
    answer_patterns: tuple[str, ...]


DOMAIN_CASES = [
    DomainCase(
        "modbus_fc3_max_quantity",
        "flat_lookup",
        "Per the Modbus Application Protocol Specification, what is the maximum quantity of holding registers readable in one Function Code 3 request? Use the knowledge base and cite the evidence.",
        (r"\b125\b",),
    ),
    DomainCase(
        "modbus_exception_address",
        "flat_lookup",
        "What is the numeric Modbus exception code for ILLEGAL DATA ADDRESS? Use the knowledge base and cite the evidence.",
        (r"\b(?:0x0?2|02|2)\b",),
    ),
    DomainCase(
        "snmpv3_usm_auth",
        "flat_lookup",
        "Which HMAC authentication algorithms does the SNMPv3 USM RFC define? Use the knowledge base and cite the evidence.",
        (r"md5", r"sha"),
    ),
    DomainCase(
        "redfish_service_root",
        "flat_lookup",
        "Per DSP0266, what exact URI path is the Redfish Service Root? Use the knowledge base and cite the evidence.",
        (r"/redfish/v1",),
    ),
    DomainCase(
        "cip006_supersession",
        "cross_document_supersession",
        "What replaced CIP-006-7? Use the knowledge base and cite the version-history evidence.",
        (r"cip-006-7\.1",),
    ),
    DomainCase(
        "cip003_supersession",
        "cross_document_supersession",
        "What replaced CIP-003-10? Use the knowledge base and cite the version-history evidence.",
        (r"cip-003-11",),
    ),
    DomainCase(
        "cip012_supersession",
        "cross_document_supersession",
        "What replaced CIP-012-1? Use the knowledge base and cite the version-history evidence.",
        (r"cip-012-2",),
    ),
    DomainCase(
        "bess_control_hierarchy",
        "multi_hop_control_chain",
        "Explain how BMS, EMS, PPC/SCADA, and fleet controls coordinate in a utility-scale BESS. Use the knowledge base and cite evidence for the different links.",
        (
            r"\bbms\b|battery management",
            r"\bems\b|energy management",
            r"\bppc\b|power plant controller",
            r"scada",
            r"fleet",
            r"aggregat|collect",
            r"coordinat",
        ),
    ),
    DomainCase(
        "bess_vbb_incident_chain",
        "multi_hop_control_chain",
        "According to the BESS Book, how did commissioning and limited telemetry/safety functionality contribute to the Victorian Big Battery fire, and what was destroyed? Use the knowledge base and cite the incident chain.",
        (
            r"commission",
            r"telemetry",
            r"limited|disabled",
            r"\btwo\b|\b2\b",
            r"enclosure",
        ),
    ),
]
