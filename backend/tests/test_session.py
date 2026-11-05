"""Session pipeline tests with fake STT / LLM / TTS (no GPU, no network)."""

import asyncio
import logging
import math
import struct
from array import array

from kerstin.audio import pcm16_rms_dbfs
from kerstin.config import BACKEND_DIR
from kerstin.prompts import PromptStore
from kerstin.session import Deps, Session
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
    ):
        self.pieces = pieces
        self.delay = delay
        self.warmup_delay = warmup_delay
        self.chat_delay = chat_delay
        self.chat_text = chat_text
        self.chat_error = chat_error
        self.last_messages = None
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

    async def stream_chat(self, messages):
        self.last_messages = messages
        for p in self.pieces:
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


class CountingSTT:
    def __init__(self, text=""):
        self.text = text
        self.calls = 0

    async def transcribe(self, pcm16):
        self.calls += 1
        return self.text


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
    thermal=None,
    feedback_lang="en",
    ollama_model="gemma4:26b",
    feedback_model=None,
    feedback_temperature=0.3,
    ollama_max_loaded=2,
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
        thermal=thermal,
        feedback_lang=feedback_lang,
        ollama_model=ollama_model,
        feedback_model=feedback_model,
        feedback_temperature=feedback_temperature,
        ollama_max_loaded=ollama_max_loaded,
    )
    return Session(deps=deps, send_json=sj, send_bytes=sb, scenario_key="freies_gespraech"), sent_json, sent_bytes


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
