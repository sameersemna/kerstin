"""Session pipeline tests with fake STT / LLM / TTS (no GPU, no network)."""

import asyncio
import logging
import math
import struct
import time
from array import array

from kerstin.audio import pcm16_rms_dbfs
from kerstin.config import BACKEND_DIR
from kerstin.exam import MODERATION_PREFIX, is_moderation, load_presets, make_plan
from kerstin.prompts import PromptStore
from kerstin.session import Deps, Session, format_feedback_transcript
from kerstin.thermal import ThermalStatus


class FakeSTT:
    def __init__(self, text="Ich wohne seit einem Jahr in Berlin."):
        self.text = text

    async def transcribe(self, pcm16):
        return self.text


class FakeLLM:
    def __init__(
        self,
        pieces,
        delay=0.0,
        warmup_delay=0.0,
        chat_delay=0.0,
        chat_text="### Was gut war\n- Gute Aussprache",
        chat_error=None,
        scripts=None,
    ):
        self.pieces = pieces
        self.scripts = [list(script) for script in scripts] if scripts else None
        self.delay = delay
        self.warmup_delay = warmup_delay
        self.chat_delay = chat_delay
        self.chat_text = chat_text
        self.chat_error = chat_error
        self.last_messages = None
        self.last_stream_max_tokens = None
        self.stream_calls = 0
        self.last_chat_messages = None
        self.warmup_calls = []
        self.chat_calls = 0
        self.last_chat_temperature = None
        self.last_chat_model = None
        self.last_chat_keep_alive = None
        self.loaded = []
        self.loaded_error = None
        self.loaded_calls = 0
        self.unloaded = []

    async def stream_chat(self, messages, max_tokens=None):
        self.stream_calls += 1
        self.last_messages = messages
        self.last_stream_max_tokens = max_tokens
        pieces = self.scripts.pop(0) if self.scripts else self.pieces
        for p in pieces:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield p

    async def chat(
        self,
        messages,
        max_tokens=None,
        temperature=None,
        model=None,
        keep_alive=None,
    ):
        self.chat_calls += 1
        self.last_chat_messages = messages
        self.last_chat_temperature = temperature
        self.last_chat_model = model
        self.last_chat_keep_alive = keep_alive
        if self.chat_delay:
            await asyncio.sleep(self.chat_delay)
        if self.chat_error:
            raise self.chat_error
        return self.chat_text

    async def loaded_models(self):
        self.loaded_calls += 1
        if self.loaded_error:
            raise self.loaded_error
        return list(self.loaded)

    async def unload(self, model):
        self.unloaded.append(model)

    async def warmup(self, messages):
        self.warmup_calls.append(messages)
        if self.warmup_delay:
            await asyncio.sleep(self.warmup_delay)


class FakeTTS:
    async def synthesize(self, text):
        return b"RIFF" + text.encode()


class FakeMistakeLog:
    def __init__(self, error=None, summary=None):
        self.calls = []
        self.error = error
        self.summary_data = summary or {"sessions": 0, "categories": []}
        self.summary_days = []

    async def record(self, scenario, lang, categories):
        self.calls.append((scenario, lang, list(categories)))
        if self.error:
            raise self.error
        return len(categories)

    async def summary(self, days=90):
        self.summary_days.append(days)
        if self.error:
            raise self.error
        return self.summary_data


class CountingSTT:
    def __init__(self, text=""):
        self.text = text
        self.calls = 0

    async def transcribe(self, pcm16):
        self.calls += 1
        return self.text


class ScriptedSTT:
    """Returns one scripted result per call; useful for draft/fallback paths."""

    def __init__(self, texts=None, delay=0.0, errors=None):
        self.texts = list(texts or ["Draft transcript.", "Final transcript."])
        self.delay = delay
        self.errors = list(errors or [])
        self.calls = 0
        self.pcm = []
        self.started = asyncio.Event()

    async def transcribe(self, pcm16):
        index = self.calls
        self.calls += 1
        self.pcm.append(pcm16)
        self.started.set()
        if self.delay:
            await asyncio.sleep(self.delay)
        if index < len(self.errors) and self.errors[index] is not None:
            raise self.errors[index]
        return self.texts[min(index, len(self.texts) - 1)]


class FakeThermalGuard:
    def __init__(self, status):
        self.status = status
        self.calls = 0

    async def check(self):
        self.calls += 1
        return self.status


def make_session(
    llm,
    stt=None,
    llm_warmup=True,
    stt_min_rms_dbfs=-55.0,
    stt_filter=True,
    early_stt=True,
    thermal=None,
    feedback_lang="en",
    ollama_model="gemma4:26b",
    feedback_model=None,
    feedback_temperature=0.3,
    ollama_max_loaded=2,
    mistakes=None,
    focus=None,
    exam=None,
):
    sent_json, sent_bytes = [], []

    async def sj(o):
        sent_json.append(o)

    async def sb(b):
        sent_bytes.append(b)

    deps = Deps(
        stt=stt or FakeSTT(),
        llm=llm,
        tts=FakeTTS(),
        prompts=PromptStore(BACKEND_DIR / "prompts"),
        llm_warmup=llm_warmup,
        stt_min_rms_dbfs=stt_min_rms_dbfs,
        stt_filter=stt_filter,
        early_stt=early_stt,
        thermal=thermal,
        feedback_lang=feedback_lang,
        ollama_model=ollama_model,
        feedback_model=feedback_model,
        feedback_temperature=feedback_temperature,
        ollama_max_loaded=ollama_max_loaded,
        mistakes=mistakes,
    )
    return Session(
        deps=deps,
        send_json=sj,
        send_bytes=sb,
        scenario_key="freies_gespraech",
        focus=focus or [],
        exam=exam,
    ), sent_json, sent_bytes


PCM_1S = array(
    "h", (int(20000 * math.sin(2 * math.pi * 440 * i / 16000)) for i in range(16000))
).tobytes()
PCM_SILENCE = b"\x00\x00" * 16000


async def test_start_triggers_warmup_with_system_and_opener():
    llm = FakeLLM(["Hallo."])
    s, js, _ = make_session(llm)
    await s.start()
    assert s._warmup_task is not None
    await s._warmup_task
    assert len(llm.warmup_calls) == 1
    messages = llm.warmup_calls[0]
    opener = s.deps.prompts.scenario("freies_gespraech").opener
    assert messages[0]["role"] == "system"
    assert "Kreuzberg" in messages[0]["content"]
    assert messages[1] == {"role": "assistant", "content": opener}
    assert any(m["type"] == "reply_text" and m["turn"] == 0 for m in js)


async def test_start_without_warmup():
    llm = FakeLLM(["Hallo."])
    s, js, _ = make_session(llm, llm_warmup=False)
    await s.start()
    assert s._warmup_task is None
    assert llm.warmup_calls == []
    assert any(m["type"] == "reply_text" and m["turn"] == 0 for m in js)


async def test_warmup_does_not_delay_opener_and_close_cancels():
    llm = FakeLLM(["Hallo."], warmup_delay=10)
    s, js, _ = make_session(llm)
    await asyncio.wait_for(s.start(), timeout=1.0)
    assert any(m["type"] == "reply_text" and m["turn"] == 0 for m in js)
    await asyncio.sleep(0)  # let the warm-up task start and hit its sleep
    assert s._warmup_task is not None
    assert not s._warmup_task.done()
    assert llm.warmup_calls
    await asyncio.wait_for(s.close(), timeout=1.0)
    assert s._warmup_task is None


async def test_opener_and_turn():
    llm = FakeLLM(["Oh, cool! Und ", "wie gefällt dir ", "Berlin bisher?"])
    s, js, bs = make_session(llm)
    await s.start()
    assert js[0]["type"] == "session"
    assert js[0]["focus"] == []
    assert any(m["type"] == "reply_text" for m in js)

    await s.handle_audio(PCM_1S)
    await s._turn_task
    types = [m["type"] for m in js]
    assert "transcript" in types and "reply_done" in types and "metrics" in types
    metrics = next(m for m in js if m["type"] == "metrics")
    assert metrics["first_sentence_ms"] >= 0
    assert metrics["tts_first_ms"] >= 0
    assert metrics["first_sentence_ms"] <= metrics["first_audio_ms"]
    assert metrics["audio_dbfs"] == round(pcm16_rms_dbfs(PCM_1S), 1)
    texts = [m["text"] for m in js if m["type"] == "reply_text" and m["turn"] == 1]
    assert texts == ["Oh, cool! Und wie gefällt dir Berlin bisher?"] or texts == [
        "Oh, cool!", "Und wie gefällt dir Berlin bisher?"
    ]
    # audio frames carry the turn id header
    assert struct.unpack(">I", bs[-1][:4])[0] == 1
    # history: opener, user, assistant
    assert [m["role"] for m in s.history] == ["assistant", "user", "assistant"]
    # system prompt is first and contains the scenario
    assert llm.last_messages[0]["role"] == "system"
    assert "Kreuzberg" in llm.last_messages[0]["content"]


async def test_first_clause_is_sent_as_its_own_chunk():
    llm = FakeLLM(["Das klingt wirklich schön, ", "weil ich gern Rad fahre."])
    s, js, _ = make_session(llm)
    await s.start()
    await s.handle_audio(PCM_1S)
    await s._turn_task
    texts = [m["text"] for m in js if m["type"] == "reply_text" and m["turn"] == 1]
    assert texts == ["Das klingt wirklich schön,", "weil ich gern Rad fahre."]
    assert s.history[-1] == {
        "role": "assistant",
        "content": "Das klingt wirklich schön, weil ich gern Rad fahre.",
    }


async def test_barge_in_cancels_turn():
    llm = FakeLLM(["Das ist ein langer Satz, der langsam kommt. "] * 20, delay=0.05)
    s, js, _ = make_session(llm)
    await s.start()
    await s.handle_audio(PCM_1S)
    await asyncio.sleep(0.15)
    await s.interrupt()
    assert any(m["type"] == "reply_interrupted" for m in js)


async def test_short_utterance_reports_too_short():
    stt = CountingSTT()
    s, js, _ = make_session(FakeLLM(["Hallo."]), stt=stt)
    await s.start()
    await s.handle_audio(b"\x00\x00" * 1000)  # 0.06 s
    await s._turn_task
    empty = [m for m in js if m["type"] == "stt_empty"]
    assert empty and empty[-1]["reason"] == "too_short"
    assert stt.calls == 0
    assert not any(m["type"] == "transcript" for m in js)


async def test_quiet_utterance_reports_too_quiet_without_stt():
    stt = CountingSTT()
    s, js, _ = make_session(FakeLLM(["Hallo."]), stt=stt)
    await s.start()
    await s.handle_audio(PCM_SILENCE)
    await s._turn_task
    empty = [m for m in js if m["type"] == "stt_empty"]
    assert empty and empty[-1]["reason"] == "too_quiet"
    assert stt.calls == 0
    assert not any(m["type"] == "transcript" for m in js)


async def test_hallucination_is_dropped_before_llm_and_history():
    stt = CountingSTT("Untertitel der Amara.org-Community")
    llm = FakeLLM(["Hallo."])
    s, js, _ = make_session(llm, stt=stt)
    await s.start()
    history_before = list(s.history)
    await s.handle_audio(PCM_1S)
    await s._turn_task
    empty = [m for m in js if m["type"] == "stt_empty"]
    assert empty and empty[-1]["reason"] == "hallucination"
    assert s.history == history_before
    assert llm.last_messages is None
    assert not any(m["type"] == "transcript" for m in js)


async def test_echo_is_dropped_before_llm_and_history():
    opener = PromptStore(BACKEND_DIR / "prompts").scenario("freies_gespraech").opener
    stt = CountingSTT(opener)
    llm = FakeLLM(["Hallo."])
    s, js, _ = make_session(llm, stt=stt)
    await s.start()
    history_before = list(s.history)
    await s.handle_audio(PCM_1S)
    await s._turn_task
    empty = [m for m in js if m["type"] == "stt_empty"]
    assert empty and empty[-1]["reason"] == "echo"
    assert s.history == history_before
    assert stt.calls == 1
    assert llm.last_messages is None
    assert not any(m["type"] == "transcript" for m in js)


async def test_hot_guard_skips_start_warmup_and_opener():
    llm = FakeLLM(["Hallo."])
    thermal = FakeThermalGuard(ThermalStatus("hot", 82))
    s, js, bs = make_session(llm, thermal=thermal)

    await s.start()

    assert [m["type"] for m in js] == ["session", "thermal"]
    assert js[1] == {"type": "thermal", "state": "hot", "temp_c": 82}
    assert s._warmup_task is None
    assert llm.warmup_calls == []
    assert bs == []
    assert s.history == []


async def test_hot_guard_blocks_turn_before_stt_and_llm():
    stt = CountingSTT()
    llm = FakeLLM(["Hallo."])
    thermal = FakeThermalGuard(ThermalStatus("hot", 82))
    s, js, bs = make_session(llm, stt=stt, thermal=thermal)

    await s.handle_audio(PCM_1S)
    await s._turn_task

    assert js == [{"type": "thermal", "state": "hot", "temp_c": 82, "turn": 1}]
    assert stt.calls == 0
    assert llm.last_messages is None
    assert s.history == []
    assert bs == []
    assert thermal.calls == 1


async def test_hot_guard_blocks_feedback_llm():
    llm = FakeLLM(["Hallo."])
    thermal = FakeThermalGuard(ThermalStatus("hot", 82))
    s, js, _ = make_session(llm, thermal=thermal)
    s.history.append({"role": "user", "content": "Ich war im Kino."})
    history_before = list(s.history)

    await s.feedback()

    assert js == [{"type": "thermal", "state": "hot", "temp_c": 82}]
    assert llm.chat_calls == 0
    assert s.history == history_before


async def test_ok_guard_allows_start_and_turn():
    llm = FakeLLM(["Hallo."])
    thermal = FakeThermalGuard(ThermalStatus("ok", 65))
    s, js, _ = make_session(llm, thermal=thermal)

    await s.start()
    await s.handle_audio(PCM_1S)
    await s._turn_task

    assert any(m["type"] == "reply_text" and m["turn"] == 0 for m in js)
    assert any(m["type"] == "reply_done" and m["turn"] == 1 for m in js)
    assert not any(m["type"] == "thermal" for m in js)
    assert thermal.calls == 2


async def test_hint_returns_markdown_without_touching_history():
    llm = FakeLLM(
        ["Hallo."],
        chat_text="**der Vermieter** (Pl. die Vermieter)\nBeispiel: „Mein Vermieter repariert die Heizung nicht.“",
    )
    s, js, _ = make_session(llm)

    await s.hint("  landlord  ")
    await s._hint_task

    hints = [m for m in js if m["type"] == "hint"]
    assert hints == [
        {
            "type": "hint",
            "query": "landlord",
            "markdown": "**der Vermieter** (Pl. die Vermieter)\n"
            "Beispiel: „Mein Vermieter repariert die Heizung nicht.“",
        }
    ]
    assert s.history == []
    assert "landlord" in llm.last_chat_messages[0]["content"]
    assert llm.last_chat_temperature == 0.2


async def test_hint_during_turn_does_not_cancel_turn():
    llm = FakeLLM(["Hallo."], delay=0.03)
    s, js, _ = make_session(llm)

    await s.handle_audio(PCM_1S)
    await s.hint("landlord")
    await asyncio.gather(s._turn_task, s._hint_task)

    assert any(m["type"] == "reply_done" and m["turn"] == 1 for m in js)
    assert any(m["type"] == "hint" and m["query"] == "landlord" for m in js)
    assert not any(m["type"] == "reply_interrupted" for m in js)
    assert all("landlord" not in m["content"] for m in s.history)


async def test_audio_during_hint_does_not_cancel_hint():
    llm = FakeLLM(["Hallo."], chat_delay=0.05)
    s, js, _ = make_session(llm)

    await s.hint("landlord")
    await s.handle_audio(PCM_1S)
    await asyncio.gather(s._hint_task, s._turn_task)

    assert any(m["type"] == "hint" and m["query"] == "landlord" for m in js)
    assert any(m["type"] == "reply_done" and m["turn"] == 1 for m in js)


async def test_second_hint_cancels_first():
    llm = FakeLLM(["Hallo."], chat_delay=0.05)
    s, js, _ = make_session(llm)

    await s.hint("first")
    await s.hint("second")
    await s._hint_task

    hints = [m for m in js if m["type"] == "hint"]
    assert len(hints) == 1
    assert hints[0]["query"] == "second"


async def test_hint_too_long():
    llm = FakeLLM(["Hallo."])
    s, js, _ = make_session(llm)
    query = "x" * 121

    await s.hint(query)

    assert js == [{"type": "hint", "query": query[:120], "error": "too_long"}]
    assert llm.chat_calls == 0


async def test_hint_thermal_hot_skips_llm():
    llm = FakeLLM(["Hallo."])
    thermal = FakeThermalGuard(ThermalStatus("hot", 82))
    s, js, _ = make_session(llm, thermal=thermal)

    await s.hint("landlord")

    assert js == [
        {
            "type": "hint",
            "query": "landlord",
            "error": "thermal",
            "temp_c": 82,
        }
    ]
    assert llm.chat_calls == 0


async def test_hint_llm_exception_logs_type_only(caplog):
    llm = FakeLLM(["Hallo."], chat_error=RuntimeError("boom"))
    s, js, _ = make_session(llm)

    with caplog.at_level(logging.INFO, logger="kerstin.session"):
        await s.hint("landlord")
        await s._hint_task

    assert js == [{"type": "hint", "query": "landlord", "error": "failed"}]
    assert "RuntimeError" in caplog.text
    assert "landlord" not in caplog.text


async def test_empty_hint_is_ignored():
    llm = FakeLLM(["Hallo."])
    s, js, _ = make_session(llm)

    await s.hint("   ")

    assert js == []
    assert s._hint_task is None
    assert llm.chat_calls == 0


async def test_feedback_after_hint_contains_no_hint_text():
    llm = FakeLLM(["Hallo."], chat_text="**der Vermieter**")
    s, _js, _ = make_session(llm)
    s.history.extend(
        [
            {"role": "assistant", "content": "Hallo!"},
            {"role": "user", "content": "Ich suche eine Wohnung."},
        ]
    )

    await s.hint("GEHEIMER_HINT_TEXT")
    await s._hint_task
    history_before = list(s.history)
    await s.feedback()

    assert s.history == history_before
    prompt = llm.last_chat_messages[0]["content"]
    assert "GEHEIMER_HINT_TEXT" not in prompt


async def test_close_cancels_running_hint():
    llm = FakeLLM(["Hallo."], chat_delay=10)
    s, js, _ = make_session(llm)

    await s.hint("landlord")
    await s.close()

    assert s._hint_task is None
    assert not any(m["type"] == "hint" for m in js)


async def test_feedback_uses_requested_german_prompt():
    llm = FakeLLM(["Hallo."])
    s, _, _ = make_session(llm)
    s.history.append({"role": "user", "content": "Ich wohne seit zwei Jahre in Berlin."})

    await s.feedback("de")

    prompt = llm.last_chat_messages[0]["content"]
    assert "Deutsch (einfache Sprache" in prompt
    assert "Englisch" not in prompt


async def test_feedback_uses_server_default_language():
    llm = FakeLLM(["Hallo."])
    s, _, _ = make_session(llm, feedback_lang="de")
    s.history.append({"role": "user", "content": "Ich wohne seit zwei Jahre in Berlin."})

    await s.feedback()

    prompt = llm.last_chat_messages[0]["content"]
    assert "Deutsch (einfache Sprache" in prompt


async def test_feedback_invalid_language_uses_server_default(caplog):
    llm = FakeLLM(["Hallo."])
    s, _, _ = make_session(llm, feedback_lang="de")
    s.history.append({"role": "user", "content": "Ich wohne seit zwei Jahre in Berlin."})

    with caplog.at_level(logging.INFO, logger="kerstin.session"):
        await s.feedback("fr")

    prompt = llm.last_chat_messages[0]["content"]
    assert "Deutsch (einfache Sprache" in prompt
    assert any(
        "invalid" in record.message and record.levelno == logging.INFO
        for record in caplog.records
    )
    assert "Ich wohne" not in caplog.text


async def test_feedback():
    llm = FakeLLM(["Gut. Und du?"])
    s, js, _ = make_session(llm)
    await s.start()
    await s.handle_audio(PCM_1S)
    await s._turn_task
    await s.feedback()
    fb = [m for m in js if m["type"] == "feedback"]
    assert fb and "Was gut war" in fb[0]["markdown"]
    assert llm.last_chat_temperature == 0.3
    assert llm.last_chat_model == "gemma4:26b"
    assert llm.last_chat_keep_alive is None
    assert llm.loaded_calls == 0
    assert llm.unloaded == []


async def test_feedback_model_unloads_chat_when_slot_needed():
    llm = FakeLLM(["Gut. Und du?"], chat_text="### Feedback")
    llm.loaded = ["gemma4:26b", "llama3.2:1b"]
    s, _, _ = make_session(llm, feedback_model="gemma4:31b")
    s.history.append({"role": "user", "content": "Ich war im Kino."})

    await s.feedback()

    assert llm.loaded_calls == 1
    assert llm.unloaded == ["gemma4:26b"]
    assert llm.last_chat_model == "gemma4:31b"
    assert llm.last_chat_keep_alive == "0"
    assert llm.last_chat_temperature == 0.3


async def test_feedback_model_falls_back_when_slots_are_busy(caplog):
    llm = FakeLLM(["Gut. Und du?"], chat_text="### Feedback")
    llm.loaded = ["llama3.2:1b", "qwen3:14b"]
    s, _, _ = make_session(llm, feedback_model="gemma4:31b")
    s.history.append({"role": "user", "content": "Ich war im Kino."})

    with caplog.at_level(logging.INFO, logger="kerstin.session"):
        await s.feedback()

    assert llm.loaded_calls == 1
    assert llm.unloaded == []
    assert llm.last_chat_model == "gemma4:26b"
    assert llm.last_chat_keep_alive is None
    assert "feedback model fallback (slots busy)" in caplog.text


async def test_feedback_model_falls_back_when_ps_fails(caplog):
    llm = FakeLLM(["Gut. Und du?"], chat_text="### Feedback")
    llm.loaded_error = RuntimeError("/api/ps down")
    s, _, _ = make_session(llm, feedback_model="gemma4:31b")
    s.history.append({"role": "user", "content": "Ich war im Kino."})

    with caplog.at_level(logging.INFO, logger="kerstin.session"):
        await s.feedback()

    assert llm.loaded_calls == 1
    assert llm.unloaded == []
    assert llm.last_chat_model == "gemma4:26b"
    assert llm.last_chat_keep_alive is None
    assert "feedback model fallback (ps failed: RuntimeError)" in caplog.text


async def test_feedback_model_needs_no_unload_with_free_slots():
    llm = FakeLLM(["Gut. Und du?"], chat_text="### Feedback")
    llm.loaded = ["gemma4:26b"]
    s, _, _ = make_session(llm, feedback_model="gemma4:31b")
    s.history.append({"role": "user", "content": "Ich war im Kino."})

    await s.feedback()

    assert llm.loaded_calls == 1
    assert llm.unloaded == []
    assert llm.last_chat_model == "gemma4:31b"
    assert llm.last_chat_keep_alive == "0"
    assert llm.last_chat_temperature == 0.3


FEEDBACK_WITH_ERRORS = """### Was gut war
- Gute Aussprache

### Wichtigste Fehler
1. ❌ mit ein Freund
   ✅ mit einem Freund
   💡 The preposition "mit" always requires the dative case.
2. ❌ weil ich bin seit zwei Wochen im Team
   ✅ weil ich seit zwei Wochen im Team bin
   💡 In a subordinate clause starting with "weil", the verb must go to the end.
"""


async def test_feedback_saves_mistake_categories_when_opted_in():
    llm = FakeLLM(["Hallo."], chat_text=FEEDBACK_WITH_ERRORS)
    mistakes = FakeMistakeLog()
    s, js, _ = make_session(llm, mistakes=mistakes)
    s.history.append({"role": "user", "content": "Ich war im Kino."})

    await s.feedback(save_mistakes=True)

    assert mistakes.calls == [
        ("freies_gespraech", "en", ["kasus", "verbposition"])
    ]
    saved = [m for m in js if m["type"] == "mistakes_saved"]
    assert saved == [{"type": "mistakes_saved", "count": 2}]
    assert any(m["type"] == "feedback" for m in js)


async def test_feedback_does_not_save_mistakes_by_default():
    llm = FakeLLM(["Hallo."], chat_text=FEEDBACK_WITH_ERRORS)
    mistakes = FakeMistakeLog()
    s, js, _ = make_session(llm, mistakes=mistakes)
    s.history.append({"role": "user", "content": "Ich war im Kino."})

    await s.feedback()

    assert mistakes.calls == []
    assert not any(m["type"] == "mistakes_saved" for m in js)


async def test_feedback_zero_errors_records_a_practice_session():
    llm = FakeLLM(["Hallo."], chat_text="### Was gut war\n- Gute Aussprache")
    mistakes = FakeMistakeLog()
    s, js, _ = make_session(llm, mistakes=mistakes)
    s.history.append({"role": "user", "content": "Ich war im Kino."})

    await s.feedback(save_mistakes=True)

    assert mistakes.calls == [("freies_gespraech", "en", [])]
    assert [m for m in js if m["type"] == "mistakes_saved"] == [
        {"type": "mistakes_saved", "count": 0}
    ]


async def test_feedback_survives_mistake_log_error(caplog):
    llm = FakeLLM(["Hallo."], chat_text=FEEDBACK_WITH_ERRORS)
    mistakes = FakeMistakeLog(error=RuntimeError("boom"))
    s, js, _ = make_session(llm, mistakes=mistakes)
    s.history.append({"role": "user", "content": "Ich war im Kino."})

    with caplog.at_level(logging.WARNING, logger="kerstin.session"):
        await s.feedback(save_mistakes=True)

    assert any(m["type"] == "feedback" for m in js)
    assert [m for m in js if m["type"] == "mistakes_saved"] == [
        {"type": "mistakes_saved", "count": 0, "error": "failed"}
    ]
    assert "RuntimeError" in caplog.text
    assert "boom" not in caplog.text


async def test_feedback_thermal_does_not_save_mistakes():
    llm = FakeLLM(["Hallo."], chat_text=FEEDBACK_WITH_ERRORS)
    mistakes = FakeMistakeLog()
    thermal = FakeThermalGuard(ThermalStatus("hot", 82))
    s, js, _ = make_session(llm, mistakes=mistakes, thermal=thermal)
    s.history.append({"role": "user", "content": "Ich war im Kino."})

    await s.feedback(save_mistakes=True)

    assert mistakes.calls == []
    assert not any(m["type"] == "mistakes_saved" for m in js)
    assert llm.chat_calls == 0


async def test_feedback_without_learner_lines_does_not_save_mistakes():
    llm = FakeLLM(["Hallo."], chat_text=FEEDBACK_WITH_ERRORS)
    mistakes = FakeMistakeLog()
    s, js, _ = make_session(llm, mistakes=mistakes)

    await s.feedback(save_mistakes=True)

    assert mistakes.calls == []
    assert [m for m in js if m["type"] == "feedback"] == [
        {"type": "feedback", "markdown": "_Noch keine Äußerungen._"}
    ]
    assert not any(m["type"] == "mistakes_saved" for m in js)
    assert llm.chat_calls == 0


async def test_focus_session_reuses_one_system_prompt_and_reports_labels():
    llm = FakeLLM(["Hallo."])
    s, js, _ = make_session(llm, focus=["verbposition", "kasus"])

    await s.start()
    assert s._warmup_task is not None
    await s._warmup_task
    await s.handle_audio(PCM_1S)
    await s._turn_task

    assert js[0]["focus"] == ["Verbposition", "Kasus"]
    assert llm.warmup_calls[0][0]["content"] == s._system
    assert llm.last_messages[0]["content"] == s._system
    assert "## Gesprächsimpulse (geheim)" in s._system


async def test_start_focus_is_strict_and_uses_the_mistake_log():
    from kerstin.main import _focus_for_start

    mistakes = FakeMistakeLog(
        summary={
            "sessions": 3,
            "categories": [
                {"key": "wortwahl", "label": "Wortwahl", "count": 9},
                {"key": "verbposition", "label": "Verbposition", "count": 4},
                {"key": "kasus", "label": "Kasus", "count": 2},
            ],
        }
    )
    deps = Deps(
        stt=None,
        llm=None,
        tts=None,
        prompts=PromptStore(BACKEND_DIR / "prompts"),
        mistakes=mistakes,
    )

    assert await _focus_for_start(deps, "true") == []
    assert mistakes.summary_days == []
    assert await _focus_for_start(deps, True) == ["verbposition", "kasus"]
    assert mistakes.summary_days == [30]


EXAM_CATALOG = load_presets(BACKEND_DIR / "prompts")


def exam_plan(key="praesentation_diskussion_planung", seed=1234):
    return make_plan(key, EXAM_CATALOG, seed)


async def test_full_telc_style_exam_flow():
    llm = FakeLLM(
        ["Hallo."],
        scripts=[
            ["Was war deine wichtigste Erfahrung?"],
            ["Das klingt spannend, danke!"],
            ["Ich bin nach Berlin gekommen, weil ich hier studieren wollte. " * 8],
            ["Ja, am Anfang war es schwierig."],
            ["Ich habe viele Freunde im Kurs gefunden."],
            ["Ich finde, Städte sollten mehr Platz für Fahrräder haben."],
            ["Das sehe ich ähnlich."],
            ["Gute Idee, wie viel würde das kosten?"],
            ["Wir könnten zuerst einen Ort suchen."],
            ["Dann machen wir eine Liste mit Aufgaben."],
            ["Das klingt fair, ich übernehme die Getränke."],
        ],
    )
    plan = exam_plan()
    stt = FakeSTT("Ich halte jetzt meinen Vortrag.")
    s, js, _ = make_session(llm, stt=stt, llm_warmup=False, exam=plan)

    await s.start()
    session = js[0]
    assert session["type"] == "session"
    assert session["focus"] == []
    assert session["exam"]["preset"] == plan.preset
    assert [part["kind"] for part in session["exam"]["parts"]] == [
        "prep",
        "learner_talk",
        "kerstin_talk",
        "dialog",
        "dialog",
    ]
    assert js[-1]["type"] == "exam_part" and js[-1]["index"] == 0
    assert llm.stream_calls == 0

    await s.exam_next()
    assert js[-1]["type"] == "exam_part" and js[-1]["index"] == 1
    assert js[-1]["kind"] == "learner_talk"
    assert s._collecting()
    assert llm.stream_calls == 0

    for index in range(4):
        stt.text = f"Mein Vortrag Punkt {index + 1}."
        await s.handle_audio(PCM_1S)
        await s._turn_task
    collected = [m for m in js if m["type"] == "collected"]
    assert len(collected) == 4
    assert llm.stream_calls == 0

    await s.exam_next()
    assert llm.stream_calls == 1
    assert not s._collecting()
    assert any(m["type"] == "reply_text" for m in js)
    assert s.part_index == 1

    stt.text = "Das war die Erfahrung mit meinem ersten Job."
    await s.handle_audio(PCM_1S)
    await s._turn_task
    assert llm.stream_calls == 2

    await s.exam_next()
    assert s.part_index == 2
    part2 = next(m for m in js if m["type"] == "exam_part" and m["index"] == 2)
    assert part2["kind"] == "kerstin_talk"
    assert part2["card"] == {"title": plan.parts[2].card["title"]}
    assert llm.stream_calls == 3
    assert llm.last_stream_max_tokens == 450

    for text in ("Wie war das für dich?", "Was hast du daraus gelernt?"):
        stt.text = text
        await s.handle_audio(PCM_1S)
        await s._turn_task
    assert llm.stream_calls == 5

    await s.exam_next()
    assert s.part_index == 3
    assert any(m["type"] == "exam_part" and m["index"] == 3 for m in js)
    assert llm.stream_calls == 6

    for text in ("Ich finde das auch wichtig.", "Aber was ist mit den Kosten?"):
        stt.text = text
        await s.handle_audio(PCM_1S)
        await s._turn_task
    assert llm.stream_calls == 8

    await s.exam_next()
    assert s.part_index == 4
    assert any(m["type"] == "exam_part" and m["index"] == 4 for m in js)
    assert llm.stream_calls == 9

    for text in ("Wir könnten das im Kursraum machen.", "Ich frage die anderen."):
        stt.text = text
        await s.handle_audio(PCM_1S)
        await s._turn_task
    assert llm.stream_calls == 11

    await s.exam_next()
    assert js[-1] == {"type": "exam_part", "kind": "done"}
    assert llm.stream_calls == 11
    assert any(is_moderation(m) for m in s.history)


async def test_collect_mode_makes_no_llm_calls_and_grows_history():
    llm = FakeLLM(["Hallo."])
    plan = exam_plan()
    stt = FakeSTT("Ein Satz.")
    s, js, _ = make_session(llm, stt=stt, llm_warmup=False, exam=plan)

    await s.start()
    await s.exam_next()
    before = len(s.history)
    for index in range(4):
        stt.text = f"Satz {index + 1}."
        await s.handle_audio(PCM_1S)
        await s._turn_task

    assert llm.stream_calls == 0
    assert len(s.history) == before + 4
    assert len([m for m in js if m["type"] == "collected"]) == 4


async def test_follow_up_happens_exactly_once():
    llm = FakeLLM(
        ["Hallo."],
        scripts=[["Welche Erfahrung war wichtig?"], ["Danke für die Antwort."], ["Mein Vortrag."]],
    )
    plan = exam_plan()
    stt = FakeSTT("Ein Satz.")
    s, _js, _ = make_session(llm, stt=stt, llm_warmup=False, exam=plan)

    await s.start()
    await s.exam_next()
    for index in range(4):
        stt.text = f"Satz {index + 1}."
        await s.handle_audio(PCM_1S)
        await s._turn_task
    await s.exam_next()
    assert s.part_index == 1
    assert s._collect_followup_done
    assert llm.stream_calls == 1

    stt.text = "Meine Antwort."
    await s.handle_audio(PCM_1S)
    await s._turn_task
    assert llm.stream_calls == 2
    await s.exam_next()
    assert s.part_index == 2
    assert llm.stream_calls == 3


async def test_exam_uses_one_system_prompt_for_warmup_and_turns():
    llm = FakeLLM(["Hallo."])
    plan = exam_plan()
    s, _, _ = make_session(llm, exam=plan)
    await s.start()
    assert s._warmup_task is not None
    await s._warmup_task
    await s._respond(1)
    assert llm.warmup_calls[0][0]["content"] == s._system
    assert llm.last_messages[0]["content"] == s._system
    assert "Karte von Kerstin" in s._system


async def test_exam_ignores_focus():
    llm = FakeLLM(["Hallo."])
    s, js, _ = make_session(llm, exam=exam_plan(), focus=["kasus"], llm_warmup=False)
    await s.start()
    assert js[0]["focus"] == []
    assert "Gesprächsimpulse" not in s._system


async def test_exam_next_outside_exam_mode_is_an_error():
    llm = FakeLLM(["Hallo."])
    s, js, _ = make_session(llm)
    await s.exam_next()
    assert js == [{"type": "error", "message": "exam_next outside exam mode"}]
    assert llm.stream_calls == 0


async def test_exam_part_handles_a_hot_kerstin_says_turn():
    llm = FakeLLM(["Hallo."])
    thermal = FakeThermalGuard(ThermalStatus("hot", 82))
    s, js, _ = make_session(llm, thermal=thermal, exam=exam_plan(), llm_warmup=False)

    await s._kerstin_says("Teil 2 – Kerstins Kurzvortrag beginnt.")

    assert js == [{"type": "thermal", "state": "hot", "temp_c": 82, "turn": 1}]
    assert llm.stream_calls == 0
    assert s.history and is_moderation(s.history[0])


async def test_moderation_markers_are_kept_when_trimming():
    llm = FakeLLM(["Hallo."])
    s, _, _ = make_session(llm, exam=exam_plan(), llm_warmup=False)
    s.deps.history_max_turns = 2
    s._system = "SYSTEM"
    s.history = [
        {"role": "assistant", "content": "alt"},
        {"role": "user", "content": "normal"},
        {"role": "user", "content": MODERATION_PREFIX + "Teil 2 – Diskussion"},
        {"role": "assistant", "content": "neu"},
        {"role": "user", "content": "spät"},
    ]

    messages = s._messages()

    assert messages[0] == {"role": "system", "content": "SYSTEM"}
    assert {"role": "user", "content": MODERATION_PREFIX + "Teil 2 – Diskussion"} in messages


async def test_feedback_transcript_renders_markers_as_headings():
    transcript = format_feedback_transcript(
        [
            {"role": "user", "content": "Ich habe einen Fehler gemacht."},
            {"role": "user", "content": MODERATION_PREFIX + "Teil 2 – Diskussion"},
            {"role": "assistant", "content": "Das klingt gut."},
        ]
    )

    assert "Lernende Person: Ich habe einen Fehler gemacht." in transcript
    assert "--- Teil 2 – Diskussion ---" in transcript
    assert "Lernende Person: [Moderation]" not in transcript


async def test_feedback_ignores_markers_for_learner_lines():
    llm = FakeLLM(["Hallo."])
    s, js, _ = make_session(llm, exam=exam_plan(), llm_warmup=False)
    s.history = [
        {"role": "user", "content": MODERATION_PREFIX + "Teil 2 – Diskussion"},
        {"role": "assistant", "content": "Hallo!"},
    ]

    await s.feedback()

    assert js == [{"type": "feedback", "markdown": "_Noch keine Äußerungen._"}]
    assert llm.chat_calls == 0


async def test_feedback_transcript_has_no_marker_as_learner_line():
    llm = FakeLLM(["Hallo."], chat_text="### Feedback")
    s, _, _ = make_session(llm, exam=exam_plan(), llm_warmup=False)
    s.history = [
        {"role": "user", "content": "Ich war im Kino."},
        {"role": "user", "content": MODERATION_PREFIX + "Teil 2 – Diskussion"},
    ]

    await s.feedback()

    prompt = llm.last_chat_messages[0]["content"]
    assert "--- Teil 2 – Diskussion ---" in prompt
    assert "Lernende Person: [Moderation]" not in prompt


async def test_hint_context_ignores_markers():
    llm = FakeLLM(["Hallo."], chat_text="**der Termin**")
    s, _, _ = make_session(llm, exam=exam_plan(), llm_warmup=False)
    s.history = [
        {"role": "user", "content": "Ich habe einen Termin."},
        {"role": "user", "content": MODERATION_PREFIX + "Teil 2 – Diskussion"},
    ]

    await s.hint("appointment")
    await s._hint_task

    prompt = llm.last_chat_messages[0]["content"]
    assert "Moderation" not in prompt
    assert "Ich habe einen Termin." in prompt


async def test_session_reports_selected_and_unknown_voice():
    s, js, _ = make_session(FakeLLM(["Hallo."]))
    s.voice_id = "piper-thorsten"
    await s.start()
    assert js[0]["voice"] == {"id": "piper-thorsten", "label": "Thorsten (Piper)"}

    s, js, _ = make_session(FakeLLM(["Hallo."]))
    s.voice_id = "not-a-voice"
    await s.start()
    assert js[0]["voice"]["id"] == "kokoro-kerstin"


# ---------- early STT (T007) ----------


async def test_early_stt_commit_reuses_the_draft_transcript():
    stt = ScriptedSTT(["Draft transcript."])
    s, js, _ = make_session(FakeLLM(["Hallo."]), stt=stt, llm_warmup=False)
    await s.start()
    assert js[0]["early_stt"] is True

    await s.handle_draft(7, PCM_1S)
    assert s._draft is not None and s._draft.task is not None
    await s._draft.task
    await s.handle_commit(7)
    await s.handle_audio(PCM_1S)
    await s._turn_task

    assert stt.calls == 1
    transcript = next(m for m in js if m["type"] == "transcript")
    assert transcript["text"] == "Draft transcript."
    metrics = next(m for m in js if m["type"] == "metrics")
    assert metrics["stt_early"] is True
    assert metrics["stt_wait_ms"] < 100
    assert metrics["stt_ms"] == metrics["stt_wait_ms"]
    assert s.drafts_sent == 1
    assert s.drafts_committed == 1
    assert s.drafts_wasted_stt == 0


async def test_early_stt_draft_without_commit_gets_fresh_stt():
    stt = ScriptedSTT(["Draft transcript.", "Final transcript."])
    s, js, _ = make_session(FakeLLM(["Hallo."]), stt=stt, llm_warmup=False)
    await s.start()

    await s.handle_draft(1, PCM_1S)
    await s._draft.task
    await s.handle_audio(PCM_1S)
    await s._turn_task

    assert stt.calls == 2
    transcript = next(m for m in js if m["type"] == "transcript")
    assert transcript["text"] == "Final transcript."
    metrics = next(m for m in js if m["type"] == "metrics")
    assert metrics["stt_early"] is False
    assert s.drafts_committed == 0
    assert s.drafts_wasted_stt == 1


async def test_early_stt_new_draft_cancels_the_previous_one():
    stt = ScriptedSTT(["old draft", "new draft", "final"], delay=0.2)
    s, js, _ = make_session(FakeLLM(["Hallo."]), stt=stt, llm_warmup=False)
    await s.start()

    await s.handle_draft(1, PCM_1S)
    await stt.started.wait()
    await s.handle_draft(2, PCM_1S)
    await s._draft.task
    await s.handle_commit(2)
    await s.handle_audio(PCM_1S)
    await s._turn_task

    assert stt.calls == 2
    transcript = next(m for m in js if m["type"] == "transcript")
    assert transcript["text"] == "new draft"
    assert s.drafts_committed == 1
    assert s.drafts_wasted_stt == 1


async def test_early_stt_committed_draft_error_falls_back_to_final_audio():
    stt = ScriptedSTT(["draft", "final"], errors=[RuntimeError("whisper down")])
    s, js, _ = make_session(FakeLLM(["Hallo."]), stt=stt, llm_warmup=False)
    await s.start()

    await s.handle_draft(1, PCM_1S)
    await s.handle_commit(1)
    await s.handle_audio(PCM_1S)
    await s._turn_task

    assert stt.calls == 2
    transcript = next(m for m in js if m["type"] == "transcript")
    assert transcript["text"] == "final"
    metrics = next(m for m in js if m["type"] == "metrics")
    assert metrics["stt_early"] is False
    assert s.drafts_wasted_stt == 1


async def test_early_stt_unknown_commit_uses_normal_path():
    stt = ScriptedSTT(["draft", "final"])
    s, js, _ = make_session(FakeLLM(["Hallo."]), stt=stt, llm_warmup=False)
    await s.start()

    await s.handle_draft(1, PCM_1S)
    await s._draft.task
    await s.handle_commit(99)
    await s.handle_audio(PCM_1S)
    await s._turn_task

    assert stt.calls == 2
    assert next(m for m in js if m["type"] == "transcript")["text"] == "final"
    assert s.drafts_committed == 0
    assert s.drafts_wasted_stt == 1


async def test_early_stt_stale_draft_is_dropped():
    stt = ScriptedSTT(["draft", "final"])
    s, js, _ = make_session(FakeLLM(["Hallo."]), stt=stt, llm_warmup=False)
    await s.start()

    await s.handle_draft(1, PCM_1S)
    await s._draft.task
    s._draft.created_at = time.monotonic() - 11
    await s.handle_commit(1)
    assert s._draft is None
    await s.handle_audio(PCM_1S)
    await s._turn_task

    assert stt.calls == 2
    assert next(m for m in js if m["type"] == "transcript")["text"] == "final"
    assert s.drafts_committed == 0
    assert s.drafts_wasted_stt == 1


async def test_early_stt_ignored_when_disabled():
    stt = ScriptedSTT(["final"])
    s, js, _ = make_session(FakeLLM(["Hallo."]), stt=stt, early_stt=False, llm_warmup=False)
    await s.start()

    assert js[0]["early_stt"] is False
    await s.handle_draft(1, PCM_1S)
    assert stt.calls == 0
    assert s._draft is None
    assert s.drafts_sent == 1


async def test_early_stt_ignored_during_exam_prep():
    stt = ScriptedSTT(["final"])
    s, js, _ = make_session(
        FakeLLM(["Hallo."]),
        stt=stt,
        exam=exam_plan(),
        llm_warmup=False,
    )
    await s.start()
    assert js[-1]["type"] == "exam_part" and js[-1]["kind"] == "prep"

    await s.handle_draft(1, PCM_1S)
    assert stt.calls == 0
    assert s._draft is None


async def test_early_stt_ignored_when_thermal_hot():
    stt = ScriptedSTT(["final"])
    s, _, _ = make_session(
        FakeLLM(["Hallo."]),
        stt=stt,
        thermal=FakeThermalGuard(ThermalStatus("hot", 82)),
        llm_warmup=False,
    )
    await s.start()

    await s.handle_draft(1, PCM_1S)
    assert stt.calls == 0
    assert s._draft is None


async def test_early_stt_quiet_draft_is_gated_without_stt():
    stt = ScriptedSTT(["final"])
    s, js, _ = make_session(FakeLLM(["Hallo."]), stt=stt, llm_warmup=False)
    await s.start()

    await s.handle_draft(1, PCM_SILENCE)
    assert stt.calls == 0
    assert s.drafts_gated == 1
    assert s._draft is not None and s._draft.gated == "too_quiet"

    await s.handle_commit(1)
    await s.handle_audio(PCM_1S)
    await s._turn_task
    assert stt.calls == 1
    assert s.drafts_committed == 1
    assert s.drafts_wasted_stt == 0
    assert next(m for m in js if m["type"] == "metrics")["stt_early"] is False


async def test_early_stt_before_session_is_ignored():
    stt = ScriptedSTT(["final"])
    s, _, _ = make_session(FakeLLM(["Hallo."]), stt=stt, llm_warmup=False)

    await s.handle_draft(1, PCM_1S)
    assert stt.calls == 0
    assert s.drafts_sent == 0


async def test_early_stt_never_interrupts_a_running_reply():
    llm = FakeLLM(["Das ist ein langer Satz, der langsam kommt. "] * 20, delay=0.05)
    stt = ScriptedSTT(["Draft transcript."], delay=0.2)
    s, js, _ = make_session(llm, stt=stt, llm_warmup=False)
    await s.start()

    await s.handle_audio(PCM_1S)
    await asyncio.sleep(0.05)
    turn_task = s._turn_task
    assert s.turn_id == 1
    await s.handle_draft(1, PCM_1S)
    assert s.turn_id == 1
    assert s._turn_task is turn_task
    assert not turn_task.done()

    await turn_task
    assert any(m["type"] == "reply_done" and m["turn"] == 1 for m in js)
    assert not any(m["type"] == "reply_interrupted" for m in js)
    await s.close()


async def test_early_stt_counters_are_logged_on_end(caplog):
    stt = ScriptedSTT(["Draft transcript.", "Final transcript."])
    s, _, _ = make_session(FakeLLM(["Hallo."]), stt=stt, llm_warmup=False)
    await s.start()
    await s.handle_draft(1, PCM_1S)
    await s._draft.task
    await s.handle_audio(PCM_1S)
    await s._turn_task

    with caplog.at_level(logging.INFO, logger="kerstin.session"):
        await s.feedback()

    assert "early stt drafts sent=1 committed=0 wasted_stt=1 gated=0" in caplog.text
    assert "Draft transcript." not in caplog.text
