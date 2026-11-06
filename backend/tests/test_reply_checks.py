from kerstin.reply_checks import check_reply, count_sentences, has_meta_talk


def test_too_long_positive():
    text = "Das ist schön. Ich mag Berlin. Wir sehen uns morgen. Bis dann."
    assert "too_long" in check_reply(text)


def test_too_long_negative():
    text = "Das ist schön. Ich mag Berlin. Wir sehen uns morgen."
    assert "too_long" not in check_reply(text)
    assert count_sentences(text) == 3


def test_no_question_positive():
    assert "no_question" in check_reply("Das ist schön.")


def test_no_question_negative():
    assert "no_question" not in check_reply("Wie geht es dir?")


def test_markdown_positive():
    assert "markdown_or_emoji" in check_reply("**Hallo**, wie geht es dir?")


def test_emoji_positive():
    assert "markdown_or_emoji" in check_reply("Hallo 😊")


def test_markdown_or_emoji_negative():
    assert "markdown_or_emoji" not in check_reply("Hallo, wie geht es dir?")


def test_digits_positive():
    assert "digits" in check_reply("Ich habe 2 Katzen.")


def test_digits_negative():
    assert "digits" not in check_reply("Ich habe zwei Katzen.")


def test_english_positive():
    assert "english" in check_reply("That is really nice, you know.")


def test_english_negative():
    assert "english" not in check_reply("Das ist wirklich schön, weißt du?")


def test_single_english_word_is_tolerated():
    assert "english" not in check_reply("Das ist okay.")


def test_correction_positive():
    assert "correction" in check_reply("Man sagt, das ist falsch.")


def test_correction_phrase_positive():
    assert "correction" in check_reply("Kleiner Tipp: man sagt das anders.")


def test_translation_with_man_sagt_is_not_a_correction():
    assert "correction" not in check_reply("Man sagt zum Beispiel: „Wir haben eine Frist.“")


def test_correction_negative():
    assert "correction" not in check_reply("Das klingt schön, oder?")


def test_meta_talk_words_are_detected():
    assert has_meta_talk("Heute liegt der Fokus auf dem Gespräch.")
    assert has_meta_talk("Das ist ein wichtiger Schwerpunkt.")
    assert has_meta_talk("Wollen wir Grammatik üben?")
    assert has_meta_talk("Ich korrigiere dich später.")
    assert has_meta_talk("Der Impuls ist nur ein Beispiel.")
    assert has_meta_talk("Verbposition und Nebensatz sind schwierig.")
    assert "meta_talk" in check_reply("Wollen wir Grammatik üben?")


def test_meta_talk_uses_word_boundaries():
    assert not has_meta_talk("Das ist hier völlig üblich.")
    assert not has_meta_talk("Das war nur ein Fehlalarm.")
    assert not has_meta_talk("Das klingt schön, oder?")
