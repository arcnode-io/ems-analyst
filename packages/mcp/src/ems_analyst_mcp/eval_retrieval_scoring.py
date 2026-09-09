"""Pure IR metrics for the golden retrieval eval — no network, no DB.

Standard definitions: reciprocal rank is 1/rank of the first relevant doc
in the retrieved list (0.0 if none found); recall@k is a binary hit/miss
on whether any relevant doc lands in the top k.
"""


def reciprocal_rank(retrieved_ids: list[str], expected_ids: list[str]) -> float:
    """1/rank of the first id in retrieved_ids that's in expected_ids.

    0.0 if none of expected_ids appear at all, or expected_ids is empty
    (the out-of-corpus case — there's no "correct" doc to rank against).
    """
    for rank, doc_id in enumerate(retrieved_ids, start=1):
        if doc_id in expected_ids:
            return 1.0 / rank
    return 0.0


def recall_at_k(retrieved_ids: list[str], expected_ids: list[str], k: int) -> float:
    """1.0 if any expected_id is within the first k of retrieved_ids, else 0.0."""
    return 1.0 if set(retrieved_ids[:k]) & set(expected_ids) else 0.0
