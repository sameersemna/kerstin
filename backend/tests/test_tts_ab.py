"""Pure tests for the TTS A/B script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AB_PATH = ROOT / "scripts" / "tts_ab.py"


def load_ab():
    spec = importlib.util.spec_from_file_location("kerstin_tts_ab", AB_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ab = load_ab()


def test_normalise_case_and_punctuation():
    assert ab.normalise("Hallo, Welt! 18:30 Uhr.") == "hallo welt 18 30 uhr"


def test_wer_perfect_and_substitution():
    assert ab.wer("Hallo Welt", "hallo, welt!") == 0.0
    assert ab.wer("Hallo Welt", "Hallo Erde") == 0.5
    assert ab.wer("eins zwei drei", "eins drei") == 1 / 3


def test_wer_empty_reference():
    assert ab.wer("", "") == 0.0
    assert ab.wer("", "etwas") == 1.0
