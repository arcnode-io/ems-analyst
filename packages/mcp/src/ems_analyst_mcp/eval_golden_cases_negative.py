"""Deliberately out-of-corpus golden queries — split from eval_golden_cases.py
to keep that file under the 200-line cap.

`expected_chunk_ids=[]` on every case here: no chunk in `knowledge` should
be considered a correct answer. Validates handoff §1 — the client's ability
to tell "nothing relevant" apart from a real hit, once vector_score ships.
"""

from .eval_golden_cases import GoldenQuery

OUT_OF_CORPUS_QUERIES: list[GoldenQuery] = [
    GoldenQuery(
        name="out_of_corpus_canopen_sdo_abort",
        query="What is the CANopen SDO abort code for 'object does not exist in object dictionary'?",
        category="out_of_corpus",
        expected_chunk_ids=[],
        note="CANopen was never seeded (corpus docs: 'Pfeiffer aborted during seed').",
    ),
    GoldenQuery(
        name="out_of_corpus_nrel_basso_screening",
        query="Per Basso's interconnection handbook, what are NREL's fast-track screening criteria?",
        category="out_of_corpus",
        expected_chunk_ids=[],
        note="Stands in for handoff §4's NREL/Basso category — that book "
        "isn't actually in `knowledge` (confirmed via book listing).",
    ),
    GoldenQuery(
        name="out_of_corpus_nist_80053_access_control",
        query="Per NIST SP 800-53, which control family covers account management (AC-2)?",
        category="out_of_corpus",
        expected_chunk_ids=[],
        note="SP 800-53 is a different NIST document from the seeded SP 800-82r3 "
        "— adjacent-sounding, genuinely absent.",
    ),
    GoldenQuery(
        name="out_of_corpus_iec61850_goose",
        query="What is the structure of an IEC 61850 GOOSE message?",
        category="out_of_corpus",
        expected_chunk_ids=[],
        note="Different substation protocol, not represented in the book list.",
    ),
    GoldenQuery(
        name="out_of_corpus_sourdough",
        query="How long should a sourdough starter ferment before its first feeding?",
        category="out_of_corpus",
        expected_chunk_ids=[],
        note="Generic off-topic control — no plausible corpus overlap at all.",
    ),
    GoldenQuery(
        name="out_of_corpus_osha_psm",
        query="What does OSHA's Process Safety Management standard require for a PHA?",
        category="out_of_corpus",
        expected_chunk_ids=[],
        note="Industrial-safety-adjacent but a different regulatory body/standard "
        "from anything seeded (NERC CIP != OSHA).",
    ),
]
