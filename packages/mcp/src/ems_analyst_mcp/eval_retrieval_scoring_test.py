"""Unit tests for recall@k / MRR — pure functions, hand-verified numbers."""

from .eval_retrieval_scoring import recall_at_k, reciprocal_rank


def test_reciprocal_rank_expected_doc_at_rank_1() -> None:
    """A hit at rank 1 scores 1.0."""
    # Arrange
    retrieved = ["a", "b", "c"]
    expected = ["a"]

    # Act
    actual = reciprocal_rank(retrieved, expected)

    # Assert
    assert actual == 1.0


def test_reciprocal_rank_expected_doc_at_rank_3() -> None:
    """A hit at rank 3 scores 1/3."""
    # Arrange
    retrieved = ["x", "y", "a"]
    expected = ["a"]

    # Act
    actual = reciprocal_rank(retrieved, expected)

    # Assert
    assert actual == 1.0 / 3


def test_reciprocal_rank_expected_doc_missing_scores_zero() -> None:
    """No expected id anywhere in the retrieved list scores 0.0."""
    # Arrange
    retrieved = ["x", "y", "z"]
    expected = ["a"]

    # Act
    actual = reciprocal_rank(retrieved, expected)

    # Assert
    assert actual == 0.0


def test_reciprocal_rank_multiple_expected_ids_uses_earliest_hit() -> None:
    """Either 'a' or 'b' counts as correct; 'b' hits first at rank 2."""
    # Arrange
    retrieved = ["x", "b", "a"]
    expected = ["a", "b"]

    # Act
    actual = reciprocal_rank(retrieved, expected)

    # Assert
    assert actual == 1.0 / 2


def test_reciprocal_rank_empty_expected_scores_zero() -> None:
    """Out-of-corpus case (expected=[]): nothing counts as a hit."""
    # Arrange
    retrieved = ["x", "y", "z"]
    expected: list[str] = []

    # Act
    actual = reciprocal_rank(retrieved, expected)

    # Assert
    assert actual == 0.0


def test_recall_at_k_hit_within_k_scores_one() -> None:
    """An expected id inside the top-k window scores 1.0."""
    # Arrange
    retrieved = ["x", "y", "a", "z"]
    expected = ["a"]

    # Act
    actual = recall_at_k(retrieved, expected, k=5)

    # Assert
    assert actual == 1.0


def test_recall_at_k_hit_beyond_k_scores_zero() -> None:
    """'a' at rank 6 falls outside a k=5 window -> 0.0."""
    # Arrange
    retrieved = ["v", "w", "x", "y", "z", "a"]
    expected = ["a"]

    # Act
    actual = recall_at_k(retrieved, expected, k=5)

    # Assert
    assert actual == 0.0


def test_recall_at_k_no_hit_scores_zero() -> None:
    """Expected id absent entirely scores 0.0."""
    # Arrange
    retrieved = ["x", "y", "z"]
    expected = ["a"]

    # Act
    actual = recall_at_k(retrieved, expected, k=5)

    # Assert
    assert actual == 0.0
