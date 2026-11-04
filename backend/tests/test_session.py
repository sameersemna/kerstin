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
    def __init__(self, pieces, delay=0.0):
        self.pieces = pieces
        self.delay = delay
        self.last_messages = None

    async def stream_chat(self, messages):
        self.last_messages = messages
        for p in self.pieces:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield p

    async def chat(self, messages, max_tokens=None):
        return "### Was gut war\n- Gute Aussprache"


class FakeTTS:
    async def synthesize(self, text):
        return b"RIFF" + text.encode()


def make_session(llm, stt=None):
    sent_json, sent_bytes = [], []

    async def sj(o):
        sent_json.append(o)

    async def sb(b):
        sent_bytes.append(b)

    deps = Deps(stt=stt or FakeSTT(), llm=llm, tts=FakeTTS(), prompts=PromptStore(BACKEND_DIR / "prompts"))
    return Session(deps=deps, send_json=sj, send_bytes=sb, scenario_key="freies_gespraech"), sent_json, sent_bytes


PCM_1S = b"\x00\x00" * 16000


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
