"""Session pipeline tests with fake STT / LLM / TTS (no GPU, no network)."""

import asyncio
import struct

from kerstin.config import BACKEND_DIR
from kerstin.prompts import PromptStore
from kerstin.session import Deps, Session


class FakeSTT:
    def __init__(self, text="Ich wohne seit einem Jahr in Berlin."):
        self.text = text

    async def transcribe(self, pcm16):
        return self.text


class FakeLLM:
    def __init__(self, pieces, delay=0.0, warmup_delay=0.0):
        self.pieces = pieces
        self.delay = delay
        self.warmup_delay = warmup_delay
        self.last_messages = None
        self.warmup_calls = []

    async def stream_chat(self, messages):
        self.last_messages = messages
        for p in self.pieces:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield p

    async def chat(self, messages, max_tokens=None):
        return "### Was gut war\n- Gute Aussprache"

    async def warmup(self, messages):
        self.warmup_calls.append(messages)
        if self.warmup_delay:
            await asyncio.sleep(self.warmup_delay)


class FakeTTS:
    async def synthesize(self, text):
        return b"RIFF" + text.encode()


def make_session(llm, stt=None, llm_warmup=True):
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
    )
    return Session(deps=deps, send_json=sj, send_bytes=sb, scenario_key="freies_gespraech"), sent_json, sent_bytes


PCM_1S = b"\x00\x00" * 16000


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


async def test_barge_in_cancels_turn():
    llm = FakeLLM(["Das ist ein langer Satz, der langsam kommt. "] * 20, delay=0.05)
    s, js, _ = make_session(llm)
    await s.start()
    await s.handle_audio(PCM_1S)
    await asyncio.sleep(0.15)
    await s.interrupt()
    assert any(m["type"] == "reply_interrupted" for m in js)


async def test_short_utterance_ignored():
    s, js, _ = make_session(FakeLLM(["Hallo."]))
    await s.start()
    await s.handle_audio(b"\x00\x00" * 1000)  # 0.06 s
    await s._turn_task
    assert not any(m["type"] == "transcript" for m in js)


async def test_feedback():
    s, js, _ = make_session(FakeLLM(["Gut. Und du?"]))
    await s.start()
    await s.handle_audio(PCM_1S)
    await s._turn_task
    await s.feedback()
    fb = [m for m in js if m["type"] == "feedback"]
    assert fb and "Was gut war" in fb[0]["markdown"]
