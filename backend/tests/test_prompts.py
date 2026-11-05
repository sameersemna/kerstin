import pytest

from kerstin.config import BACKEND_DIR
from kerstin.prompts import PromptStore


def store() -> PromptStore:
    return PromptStore(BACKEND_DIR / "prompts")


def test_feedback_prompt_english():
    prompt = store().feedback_prompt("Lernende Person: Hallo.", "en")
    assert "Englisch" in prompt
    assert "{explanation_language}" not in prompt


def test_feedback_prompt_german():
    prompt = store().feedback_prompt("Lernende Person: Hallo.", "de")
    assert "Deutsch (einfache Sprache" in prompt
    assert "{explanation_language}" not in prompt


def test_feedback_prompt_default_is_english():
    prompt = store().feedback_prompt("Lernende Person: Hallo.")
    assert "Englisch" in prompt


def test_feedback_prompt_rejects_unknown_language():
    with pytest.raises(ValueError):
        store().feedback_prompt("Lernende Person: Hallo.", "fr")


def test_transcript_placeholder_is_not_replaced():
    transcript = "Lernende Person: Ich sage {explanation_language}."
    prompt = store().feedback_prompt(transcript, "de")

    assert "Ich sage {explanation_language}." in prompt
    assert prompt.count("{explanation_language}") == 1
