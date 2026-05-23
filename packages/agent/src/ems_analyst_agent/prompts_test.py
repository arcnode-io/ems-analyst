"""Tests for prompt loader."""

from .prompts import load_prompt, load_system_prompt


class TestPromptLoader:
    """AAA tests for the package-data prompt loader."""

    def test_system_prompt_non_empty(self) -> None:
        """load_system_prompt returns the analyst persona text."""
        # Act
        actual = load_system_prompt()

        # Assert
        assert isinstance(actual, str)
        assert len(actual) > 100
        assert "analyst" in actual.lower()

    def test_load_task_prompt(self) -> None:
        """load_prompt resolves a category/name pair to the bundled file."""
        # Act
        actual = load_prompt("tasks", "market_analysis")

        # Assert
        assert isinstance(actual, str)
        assert len(actual) > 50

    def test_load_response_prompt(self) -> None:
        """load_prompt works for response templates."""
        # Act
        actual = load_prompt("responses", "summary")

        # Assert
        assert isinstance(actual, str)
        assert len(actual) > 20
