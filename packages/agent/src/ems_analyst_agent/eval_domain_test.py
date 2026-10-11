"""Answer gates reject training-data leaks and wrong retrieval routing."""

from .eval_domain import score_answer
from .eval_domain_cases import DOMAIN_CASES


def test_correct_answer_without_matching_evidence_fails() -> None:
    """A correct numeric value plus unrelated tool content is not grounding."""
    case = DOMAIN_CASES[0]
    scores = score_answer(case, "125 registers", ["rag_search"], "unrelated content")
    assert scores["answer_correct"]
    assert not scores["evidence_grounded"]


def test_graph_only_lookup_does_not_pass_flat_path_gate() -> None:
    """The graph must not become the default for self-contained lookup traffic."""
    case = DOMAIN_CASES[0]
    scores = score_answer(case, "125 registers", ["search_knowledge"], "125 registers")
    assert scores["answer_correct"] and scores["evidence_grounded"]
    assert not scores["retrieval_path_correct"]
