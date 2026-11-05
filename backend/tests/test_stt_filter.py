import pytest

from kerstin.stt_filter import clean_transcript


@pytest.mark.parametrize(
    "text",
    [
        "Untertitel der Amara.org-Community",
        "Amara.org",
        "Untertitel im Auftrag des ZDF für funk, 2017",
        "Untertitelung des ZDF",
        "Untertitelung im Auftrag",
        "Copyright WDR",
        "SWR 2024",
        "www.example.com",
        "Vielen Dank fürs Zuschauen!",
        "DANKE FÜRS ZUSCHAUEN.",
        "Bis zum nächsten Mal!",
        "Tschüss!",
        "Untertitel",
        "Vielen Dank.",
        "Amen.",
    ],
)
def test_known_hallucinations_are_dropped(text):
    assert clean_transcript(text) == ("", "hallucination")


def test_subtitle_discussion_is_kept():
    text = "Die Untertitel der Serie waren schlecht."
    assert clean_transcript(text) == (text, None)


def test_tschüss_mid_sentence_is_kept():
    text = "Ich habe tschüss gesagt und bin gegangen."
    assert clean_transcript(text) == (text, None)


@pytest.mark.parametrize(
    "text",
    [
        "[Musik]",
        "(Applaus)",
        "*Lachen*",
        "[BLANK_AUDIO]",
        "[Stille]",
        "[Geräusche]",
        "[music]",
        "[silence]",
    ],
)
def test_tags_only_are_dropped(text):
    assert clean_transcript(text) == ("", "tags_only")


def test_mixed_tag_keeps_the_sentence():
    assert clean_transcript("[Musik] Ich war gestern im Kino.") == (
        "Ich war gestern im Kino.",
        None,
    )


def test_repetition_single_word_is_trimmed():
    assert clean_transcript("sehr sehr sehr sehr gut") == ("sehr gut", "repetition_trimmed")


def test_repetition_ngram_is_trimmed():
    text = "ich weiß nicht ich weiß nicht ich weiß nicht ich weiß nicht"
    assert clean_transcript(text) == ("ich weiß nicht", "repetition_trimmed")


def test_three_repetitions_are_kept():
    text = "sehr sehr sehr gut"
    assert clean_transcript(text) == (text, None)


def test_empty_is_handled():
    assert clean_transcript("") == ("", "empty")
