# Domain MCP scoped-graph evaluation (gemma4:26b)

| Shape | N | Answers | Grounded evidence | Correct retrieval path |
|---|---:|---:|---:|---:|
| cross_document_supersession | 3 | 3/3 | 3/3 | 3/3 |
| flat_lookup | 4 | 4/4 | 4/4 | 4/4 |
| multi_hop_control_chain | 2 | 2/2 | 2/2 | 2/2 |

## modbus_fc3_max_quantity

Tools: rag_search

According to the Modbus Application Protocol Specification V1.1b3, the maximum quantity of holding registers that can be read in a single Function Code 03 (0x03) request is 125 (or 0x7D in hexadecimal). The specification defines the "Quantity of Registers" field for this function code as 2 bytes with a valid range of 1 to 125.

## modbus_exception_address

Tools: rag_search

The numeric Modbus exception code for an ILLEGAL DATA ADDRESS is 02 (or 0x02). 

According to the Modbus Application Protocol Specification V1.1b3, this code indicates that the data address received in the query is not an allowable address for the server, specifically when the combination of the reference number and transfer length is invalid.

## snmpv3_usm_auth

Tools: rag_search

The SNMPv3 User-based Security Model (USM), as defined in RFC 3414, specifies the following HMAC authentication algorithms:

1. usmHMACMD5AuthProtocol: The HMAC-MD5-96 Digest Authentication Protocol.
2. usmHMACSHAAuthProtocol: The HMAC-SHA-96 Digest Authentication Protocol.

Evidence for these protocols can be found in the snmpAuthProtocols definition within the SNMP-USER-BASED-SM-MIB (RFC 3414), which identifies both the MD5-based and SHA-based protocols as part of the protocol identifiers for authentication.

## redfish_service_root

Tools: rag_search

According to the DSP0266 Redfish Specification, the exact URI path for the Redfish service root is /redfish/v1/.

Evidence can be found in:
- DSP0266 Table 4 (Redfish-defined URIs), which explicitly lists /redfish/v1/ as the URI that returns the Redfish service root.
- DSP0266 Section 7.2.3 (Service root request), which states: "The root URL for Redfish version 1.x services shall be /redfish/v1/."

## cip006_supersession

Tools: search_knowledge

CIP-006-7 is superseded by CIP-006-7.1, which becomes effective on March 19, 2026. This is documented in the version history metadata within the corpus frontmatter for cip_006_7.md and cip_006_7_1.md.

## cip003_supersession

Tools: search_knowledge

CIP-003-10 is superseded by CIP-003-11, which is scheduled to take effect on 2026-05-26. This is documented in the version history within the source files cip_003_10.md, which lists an inactive date of 2026-05-25, and cip_003_11.md, which lists an effective date of 2026-05-26.

## cip012_supersession

Tools: search_knowledge

CIP-012-1 is superseded by CIP-012-2. According to the version history in the knowledge base, CIP-012-1 is scheduled to become inactive on 2026-06-30, with CIP-012-2 becoming effective on 2026-07-01.

## bess_control_hierarchy

Tools: combined_search

In a utility-scale Battery Energy Storage System (BESS), coordination occurs through a hierarchical control architecture, where each layer manages a specific scope of the operation—from individual cell health to grid-level interconnection.

**Battery Management System (BMS) and EMS Coordination**
The BMS operates at the lowest level, monitoring the electrochemical state of individual cells and modules. Its primary role in coordination is providing critical telemetry and safety signals to the Energy Management System (EMS).
*   **Data Aggregation:** The EMS calculates the total site-wide energy capacity by aggregating State of Charge (SoC) data from each BMS.
*   **Safety and Alarms:** The BMS provides real-time alarms to the EMS to warn against unsafe conditions, such as over-temperature or over-voltage events.
*   **Communication:** CANBUS is a common protocol used for this low-level communication between the BMS and the EMS.

**EMS and Power Conversion System (PCS) Control**
The EMS acts as the central "brain" of the BESS site. It translates high-level economic or grid signals into actionable power setpoints.
*   **Power Flow Management:** The EMS directly controls the PCS, which is responsible for setting power levels and moving energy into or out of the battery from the grid.
*   **Response Speed:** For services like frequency regulation, the EMS enables the battery to respond to control signals within milliseconds to meet required performance standards.

**Power Plant Controller (PPC) and SCADA Integration**
The PPC serves as the interface between the BESS site and the external power grid or transmission network.
*   **Grid Coordination:** The PPC directs the EMS to ensure its operational decisions are coordinated with the requirements of an external transmission network.
*   **Network Integration:** The PPC also directs the EMS to coordinate its decisions with the SCADA (Supervisory Control and Data Acquisition) system, which provides broader monitoring and supervisory oversight across the plant.

**Fleet-Level Controls**
When multiple BESS units are deployed across different locations, a higher layer of fleet-level controls is utilized.
*   **Coordinated Response:** These controls are essential to ensure a coordinated response among various batteries operating together, allowing the fleet to act as a single, large-scale virtual power plant.

## bess_vbb_incident_chain

Tools: combined_search

According to the BESS Book §5.1, the Victorian Big Battery fire on July 30, 2021, in Geelong, Australia, was partially attributed to the fact that during commissioning, telemetry systems, fault monitoring, and electrical fault safety devices were either disabled or operating with limited functionality. This lack of telemetry and safety connectivity directly contributed to the incident. The fire destroyed two battery enclosures before the situation was brought under control.
