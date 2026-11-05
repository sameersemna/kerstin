from kerstin.feedback_checks import (
    best_window_ratio,
    check_feedback,
    check_planted,
    check_quote_grounding,
    check_structure,
    count_false_corrections,
    count_format_noise,
    count_noop_corrections,
    explanation_language_ok,
    has_language_mismatch,
    parse_errors,
)

MESSAGES = [
    {"role": "assistant", "content": "Wie geht es dir?"},
    {"role": "user", "content": "Ich wohne seit zwei Jahre in Berlin."},
    {"role": "assistant", "content": "Schön."},
    {"role": "user", "content": "Ich bin müde, weil ich bin müde."},
]
CORRECT_TRICKY = [
    "Ich habe mich darüber gefreut.",
    "Wegen des Wetters bin ich zu Hause geblieben.",
]

WELL_FORMED = """\
### Was gut war
- Gute Aussprache.

### Wichtigste Fehler
- ❌ „Ich wohne seit zwei Jahre in Berlin“
  ✅ „Ich wohne seit zwei Jahren in Berlin“
  💡 The preposition "seit" requires the dative.
- ❌ „weil ich bin müde“
  ✅ „weil ich müde bin“
  💡 In a subordinate clause, the verb goes at the end.

### Besser ausdrücken
- „Ich bin müde“ klingt natürlich.

### Tipp für das nächste Gespräch
Achte auf die Verbposition.
"""


def test_well_formed_feedback_passes_all_checks():
    planted = [
        {
            "utterance_index": 1,
            "wrong": "seit zwei Jahre",
            "right": "seit zwei Jahren",
            "category": "kasus",
        },
        {
            "utterance_index": 3,
            "wrong": "weil ich bin müde",
            "right": "weil ich müde bin",
            "category": "verbposition",
        },
    ]
    result = check_feedback(WELL_FORMED, MESSAGES, CORRECT_TRICKY, "en")

    assert result.structure_ok
    assert len(result.errors) == 2
    assert result.ungrounded == 0
    assert result.quotes_kerstin == 0
    assert result.false_corrections == 0
    assert result.noop_corrections == 0
    assert result.format_noise == 0
    assert not result.lang_mismatch
    assert check_planted(result.errors, planted) == [True, True]


def test_structure_accepts_sibling_bullets():
    sibling = WELL_FORMED.replace(
        "  ✅ „Ich wohne seit zwei Jahren in Berlin“",
        "- ✅ „Ich wohne seit zwei Jahren in Berlin“",
    ).replace(
        "  💡 The preposition \"seit\" requires the dative.",
        "- 💡 The preposition \"seit\" requires the dative.",
    )
    assert check_structure(sibling)


def test_structure_missing_section():
    missing = WELL_FORMED.replace(
        "### Besser ausdrücken\n- „Ich bin müde“ klingt natürlich.\n\n", ""
    )
    assert not check_structure(missing)


def test_structure_six_errors():
    errors = "\n".join(
        f"- ❌ „Fehler {index}“\n  ✅ „Korrektur {index}“\n  💡 The rule is clear."
        for index in range(6)
    )
    markdown = (
        "### Was gut war\n- Gut.\n\n"
        "### Wichtigste Fehler\n"
        f"{errors}\n\n"
        "### Besser ausdrücken\n- Besser.\n\n"
        "### Tipp für das nächste Gespräch\nTipp.\n"
    )
    assert not check_structure(markdown)


def test_structure_error_without_explanation():
    missing = WELL_FORMED.replace(
        "  💡 In a subordinate clause, the verb goes at the end.", ""
    )
    assert not check_structure(missing)


def test_quote_from_kerstin_is_reported():
    errors = parse_errors(
        "- ❌ „Wie geht es dir?“\n"
        "  ✅ „Wie geht es Ihnen?“\n"
        "  💡 The pronoun should be formal."
    )
    ungrounded, quotes_kerstin = check_quote_grounding(errors, MESSAGES)

    assert ungrounded == 1
    assert quotes_kerstin == 1


def test_ungrounded_quote_is_reported():
    errors = parse_errors(
        "- ❌ „Das habe ich nie gesagt.“\n"
        "  ✅ „Das habe ich nicht gesagt.“\n"
        "  💡 The negation is wrong."
    )
    ungrounded, quotes_kerstin = check_quote_grounding(errors, MESSAGES)

    assert ungrounded == 1
    assert quotes_kerstin == 0


def test_planted_found_but_wrong_correction():
    errors = parse_errors(
        "- ❌ „Ich wohne seit zwei Jahre in Berlin“\n"
        "  ✅ „Ich wohne seit drei Jahren in Berlin“\n"
        "  💡 The dative is required."
    )
    planted = [
        {
            "utterance_index": 1,
            "wrong": "seit zwei Jahre",
            "right": "seit zwei Jahren",
            "category": "kasus",
        }
    ]

    assert check_planted(errors, planted) == [False]


def test_planted_found_with_markdown_emphasis_in_correction():
    errors = parse_errors(
        "- ❌ „Ich habe gestern mit ein Freund gesprochen“\n"
        "  ✅ „Ich habe gestern mit ein**em** Freund gesprochen“\n"
        "  💡 The dative is required."
    )
    planted = [
        {
            "utterance_index": 1,
            "wrong": "mit ein Freund",
            "right": "mit einem Freund",
            "category": "kasus",
        }
    ]

    assert check_planted(errors, planted) == [True]


def test_planted_missed():
    errors = parse_errors(
        "- ❌ „Ich wohne in Berlin“\n"
        "  ✅ „Ich wohne in Berlin.“\n"
        "  💡 The sentence is fine."
    )
    planted = [
        {
            "utterance_index": 1,
            "wrong": "seit zwei Jahre",
            "right": "seit zwei Jahren",
            "category": "kasus",
        }
    ]

    assert check_planted(errors, planted) == [False]


def test_explanation_language_heuristic():
    assert explanation_language_ok("The verb is at the end.", "en")
    assert explanation_language_ok(
        "Use this form for future events and for finished actions.", "en"
    )
    assert explanation_language_ok("Das Verb steht am Ende.", "de")
    assert not explanation_language_ok("The verb is at the end.", "de")
    assert has_language_mismatch("💡 The verb is at the end.", "de")
    assert not has_language_mismatch("💡 Das Verb steht am Ende.", "de")


def test_false_correction():
    errors = parse_errors(
        "- ❌ „Ich habe mich darüber gefreut.“\n"
        "  ✅ „Ich habe mich gefreut.“\n"
        "  💡 This is a false correction."
    )

    assert count_false_corrections(errors, CORRECT_TRICKY) == 1


def test_noop_correction():
    errors = parse_errors(
        "- ❌ „Ich bin müde“\n"
        "  ✅ „Ich bin müde“\n"
        "  💡 This changes nothing."
    )

    assert count_noop_corrections(errors) == 1


def test_format_noise():
    noise = "text $x$ and \\rightarrow and <b>\n|---"
    assert count_format_noise(noise) == 4


def test_best_window_ratio_finds_substring():
    assert best_window_ratio("seit zwei Jahre", "Ich wohne seit zwei Jahre in Berlin.") >= 0.8
