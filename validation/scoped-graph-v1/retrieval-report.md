# Domain MCP retrieval eval — 2026-10-12 00:43Z

**MRR (in-corpus, n=20): 0.750**  
**Recall@5 (in-corpus): 95%**

## In-corpus queries

| Shape | Category | Query | Expected | Top-1 | RR | Recall@5 | Required evidence@10 |
|---|---|---|---|---|---:|---:|---:|
| flat_lookup | dnp3 | dnp3_min_unsol_event_delay | 1209 | 1209 | 1.00 | 1 | — |
| flat_lookup | dnp3 | dnp3_data_link_confirm_mode | 1210 | 1226 | 0.50 | 1 | — |
| flat_lookup | redfish | redfish_service_root_uri | 1269 | 1279 | 0.20 | 1 | — |
| flat_lookup | redfish | redfish_odata_type_schema | 1558 | 1558 | 1.00 | 1 | — |
| flat_lookup | redfish | redfish_odata_id_required | 1561 | 1325 | 0.50 | 1 | — |
| flat_lookup | redfish | dgx_b300_redfish_default_enabled | 3233 | 3233 | 1.00 | 1 | — |
| flat_lookup | redfish | ocp_baseline_scope | 3280 | 3280 | 1.00 | 1 | — |
| flat_lookup | bess | bess_fifth_standard_capacity | 3502 | 3502 | 1.00 | 1 | — |
| flat_lookup | power_economics | power_econ_borduria_syldavia_flow | 586 | 501 | 0.12 | 0 | — |
| flat_lookup | hmi | hmi_high_performance_graphics_gray | 675 | 653 | 0.33 | 1 | — |
| flat_lookup | modbus | modbus_mask_write_register_fc | 1126 | 1126 | 1.00 | 1 | — |
| flat_lookup | ics_security | nist_80082_zta_purdue_levels | 299 | 312 | 0.50 | 1 | — |
| flat_lookup | nerc_cip | cip007_password_min_length | 141 | 141 | 1.00 | 1 | — |
| flat_lookup | nerc_cip | cip005_esp_default_deny | 61 | 60 | 0.33 | 1 | — |
| flat_lookup | nerc_cip | nerc_glossary_bes_cyber_asset_minutes | 233 | 233 | 1.00 | 1 | — |
| cross_document_supersession | nerc_cip | cip006_supersession | 801470c5-ee34-52c4-b0d5-4c21d6e61fa8 | 801470c5-ee34-52c4-b0d5-4c21d6e61fa8 | 1.00 | 1 | 100% |
| cross_document_supersession | nerc_cip | cip003_supersession | 1e0c3e4f-1150-5ee3-926d-9a50a80ee886 | 1e0c3e4f-1150-5ee3-926d-9a50a80ee886 | 1.00 | 1 | 100% |
| cross_document_supersession | nerc_cip | cip012_supersession | 46903e07-cb40-5266-8b84-b3c48f43a06d | 46903e07-cb40-5266-8b84-b3c48f43a06d | 1.00 | 1 | 100% |
| multi_hop_control_chain | bess | bess_control_hierarchy | 29dfc0ec-2119-40e9-a7eb-9c8326a19321,87581a64-c9e3-45de-88ec-e05fc6b8daef,92e960e6-27b1-4a4b-a591-398d0618eaeb,ba53dcf4-3be4-4adc-af1b-d9f4ed8ad9f1,5adece43-5f39-4d4a-8eb7-044fa0c367ff,1bdbcd7e-e1e2-4eb2-9eca-b3d46fe24264,6a9d2d06-0f9d-48b4-8b4b-7f8e4faa16dc,33e7ee56-bffd-4d4c-a49a-ef02134e550a,e0ec381f-4228-4581-bcd7-51189c34e5f6 | 5acc3b13-fce3-4543-b7ad-75cac6ae41ad | 0.50 | 1 | 100% |
| multi_hop_control_chain | bess | bess_vbb_incident_chain | b3d9edf9-89ee-543b-a55a-b4377cf6cb17,f9c7837e-6323-5695-bed6-e2a063d136de,f879337b-03ba-5e9f-9434-f35f8f341ea3 | b3d9edf9-89ee-543b-a55a-b4377cf6cb17 | 1.00 | 1 | 100% |

## By query shape (ADR-026)

| Query shape | N | MRR | Recall@5 |
|---|---:|---:|---:|
| cross_document_supersession | 3 | 1.000 | 100% |
| flat_lookup | 15 | 0.699 | 93% |
| multi_hop_control_chain | 2 | 0.750 | 100% |

## Out-of-corpus queries (not yet scorable — see handoff §1)

_No confidence threshold exists yet (vector_score isn't surfaced), so these are captured for visibility only, not scored pass/fail._

| Category | Query | Top-1 result | Top-1 fused score |
|---|---|---|---:|
| out_of_corpus | out_of_corpus_canopen_sdo_abort | 1224 | 0.01639 |
| out_of_corpus | out_of_corpus_nrel_basso_screening | 10 | 0.01639 |
| out_of_corpus | out_of_corpus_nist_80053_access_control | 327 | 0.01639 |
| out_of_corpus | out_of_corpus_iec61850_goose | 924 | 0.03227 |
| out_of_corpus | out_of_corpus_sourdough | 2271 | 0.01639 |
| out_of_corpus | out_of_corpus_osha_psm | 311 | 0.01639 |
