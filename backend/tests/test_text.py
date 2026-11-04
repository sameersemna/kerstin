from kerstin.text import SentenceSplitter, clean_for_tts, strip_think


def split_all(chunks, min_chars=1):
    s = SentenceSplitter(min_chars=min_chars)
    out = []
    for c in chunks:
        out += s.feed(c)
    return out + s.flush()


def test_basic_split_streaming():
    chunks = ["Hallo! Wie ", "geht es dir? Mir ", "geht es gut."]
    assert split_all(chunks) == ["Hallo!", "Wie geht es dir?", "Mir geht es gut."]


def test_abbreviations_not_split():
    text = "Ich mag z. B. Bouldern und Kochen usw. aber nicht Joggen. Und du?"
    assert split_all([text]) == [
        "Ich mag z. B. Bouldern und Kochen usw. aber nicht Joggen.",
        "Und du?",
    ]


def test_ordinal_dates_not_split():
    text = "Die Feier ist am 3. Mai im Café. Passt dir das?"
    assert split_all([text]) == ["Die Feier ist am 3. Mai im Café.", "Passt dir das?"]


def test_min_chars_merges_short_fragments():
    out = split_all(["Ja. Das finde ich auch total wichtig. Okay?"], min_chars=12)
    assert out == ["Ja. Das finde ich auch total wichtig.", "Okay?"]


def test_quotes_after_end():
    out = split_all(["Sie sagte: „Komm mit!“ Dann ging sie."])
    assert out == ["Sie sagte: „Komm mit!“", "Dann ging sie."]


def test_clean_for_tts_and_think():
    assert strip_think("<think>hmm</think>Hallo") == "Hallo"
    assert clean_for_tts("**Hallo** _du_ `x`") == "Hallo du x"
