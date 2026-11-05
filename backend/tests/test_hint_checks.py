import json

from kerstin.config import BACKEND_DIR, PROJECT_DIR
from kerstin.hint_checks import check_hint


def check(answer, accept, pos="verb"):
    return check_hint(answer, {"accept": accept, "pos": pos})


NOUN = """**die Wohnung** (Pl. die Wohnungen)
Beispiel: „Die Wohnung ist klein, aber gemütlich.“"""


def test_valid_noun_answer():
    result = check(NOUN, ["die Wohnung"], "noun")

    assert result.format_ok
    assert result.lemma_ok
    assert result.pos_ok
    assert result.example_ok
    assert result.format_noise == 0
    assert result.ok


def test_valid_verb_with_separable_form():
    answer = """**anfangen** (fing an, hat angefangen)
Beispiel: „Ich fange morgen früh mit der Arbeit an.“"""

    assert check(answer, ["anfangen"]).ok


def test_valid_reflexive_with_fixed_preposition():
    answer = """**sich erinnern an** + Akk. (erinnerte sich, hat sich erinnert)
Beispiel: „Ich erinnere mich an den Termin.“"""

    assert check(answer, ["sich erinnern an"]).ok


def test_valid_adjective_with_comparative():
    answer = """**gut** (besser, am besten)
Beispiel: „Das Essen war wirklich gut.“"""

    assert check(answer, ["gut"], "adj").ok


def test_three_lines_with_alternative_are_allowed():
    answer = """**die Wohnung** (Pl. die Wohnungen)
Alternative: die Bleibe
Beispiel: „Die Wohnung ist klein, aber gemütlich.“"""

    assert check(answer, ["die Wohnung"], "noun").ok


def test_missing_bold_fails():
    answer = """die Wohnung (Pl. die Wohnungen)
Beispiel: „Die Wohnung ist klein.“"""

    result = check(answer, ["die Wohnung"], "noun")
    assert not result.format_ok
    assert not result.lemma_ok
    assert not result.ok


def test_four_lines_fail():
    answer = """**die Wohnung** (Pl. die Wohnungen)
Alternative: die Bleibe
Alternative: das Domizil
Beispiel: „Die Wohnung ist klein.“"""

    assert not check(answer, ["die Wohnung"], "noun").format_ok


def test_missing_beispiel_fails():
    answer = """**die Wohnung** (Pl. die Wohnungen)
Das ist eine schöne Wohnung."""

    assert not check(answer, ["die Wohnung"], "noun").format_ok


def test_multiple_quotes_fail():
    answer = """**die Wohnung** (Pl. die Wohnungen)
Beispiel: „Die Wohnung ist schön.“ „Wirklich.“"""

    assert not check(answer, ["die Wohnung"], "noun").format_ok


def test_latex_and_table_noise():
    latex = """**die Wohnung** (Pl. die Wohnungen)
Beispiel: „Die Wohnung ist $\\rightarrow$ schön.“"""
    table = """**die Wohnung** (Pl. die Wohnungen)
| a | b |
|---|---|
Beispiel: „Die Wohnung ist schön.“"""

    assert check(latex, ["die Wohnung"], "noun").format_noise > 0
    assert check(table, ["die Wohnung"], "noun").format_noise > 0
    assert not check(latex, ["die Wohnung"], "noun").ok


def test_lemma_must_match_accept():
    answer = """**der Vermieter** (Pl. die Vermieter)
Beispiel: „Der Vermieter ist freundlich.“"""

    result = check(answer, ["die Wohnung"], "noun")
    assert not result.lemma_ok
    assert not result.ok


def test_noun_needs_article_and_plural():
    answer = """**die Wohnung**
Beispiel: „Die Wohnung ist klein.“"""

    assert not check(answer, ["die Wohnung"], "noun").pos_ok


def test_adjective_must_not_have_verb_forms():
    answer = """**stur** (ist stur gewesen, war stur)
Beispiel: „Er ist sehr stur.“"""

    assert not check(answer, ["stur"], "adj").pos_ok


def test_example_must_contain_lemma_content_words():
    answer = """**die Wohnung** (Pl. die Wohnungen)
Beispiel: „Das Haus ist klein.“"""

    assert not check(answer, ["die Wohnung"], "noun").example_ok


def test_eval_queries_are_absent_from_the_prompt():
    cases = json.loads((PROJECT_DIR / "scripts" / "hint_cases.json").read_text())
    prompt = (BACKEND_DIR / "prompts" / "hint.md").read_text().lower()

    for case in cases["cases"]:
        assert case["query"].lower() not in prompt
