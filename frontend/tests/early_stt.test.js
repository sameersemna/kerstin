const test = require("node:test");
const assert = require("node:assert/strict");

const { createEarlySTT } = require("../early_stt.js");

const FRAME = new Float32Array(1536);

function probs(value) {
  return { isSpeech: value };
}

function make(overrides = {}) {
  const drafts = [];
  const state = createEarlySTT({
    onDraft: (id, audio) => drafts.push({ id, audio }),
    ...overrides,
  });
  return { state, drafts };
}

function start(state, speechFrames = 4) {
  state.onFrame(probs(0.1), FRAME); // pre-speech pad
  state.onFrame(probs(0.9), FRAME); // frame that triggers SpeechStart
  state.begin();
  for (let i = 1; i < speechFrames; i++) state.onFrame(probs(0.9), FRAME);
}

test("one sentence: a draft is sent and committed at speech end", () => {
  const { state, drafts } = make();
  start(state);

  state.onFrame(probs(0.1), FRAME);
  state.onFrame(probs(0.1), FRAME);
  assert.equal(drafts.length, 1);
  assert.equal(drafts[0].id, 1);
  assert.equal(drafts[0].audio.length, 7 * 1536); // 1 pad + 4 speech + 2 pause

  assert.equal(state.end(), drafts[0].id);
});

test("pause 300 ms then keep talking: draft is invalidated, no commit", () => {
  const { state, drafts } = make();
  start(state);

  for (let i = 0; i < 3; i++) state.onFrame(probs(0.1), FRAME); // ~300 ms pause
  assert.equal(drafts.length, 1);

  state.onFrame(probs(0.9), FRAME);
  state.onFrame(probs(0.9), FRAME);
  assert.equal(state.end(), null);
  assert.equal(drafts.length, 1);
});

test("at most three drafts per utterance", () => {
  const { state, drafts } = make();
  start(state);

  for (let i = 0; i < 4; i++) {
    state.onFrame(probs(0.1), FRAME);
    state.onFrame(probs(0.1), FRAME);
    state.onFrame(probs(0.9), FRAME);
  }

  assert.equal(drafts.length, 3);
  assert.deepEqual(drafts.map((draft) => draft.id), [1, 2, 3]);
});

test("waits for minSpeechFrames before drafting", () => {
  const { state, drafts } = make();
  state.begin();
  for (let i = 0; i < 3; i++) state.onFrame(probs(0.9), FRAME);
  state.onFrame(probs(0.1), FRAME);
  state.onFrame(probs(0.1), FRAME);
  assert.equal(drafts.length, 0);

  state.onFrame(probs(0.9), FRAME);
  state.onFrame(probs(0.1), FRAME);
  state.onFrame(probs(0.1), FRAME);
  assert.equal(drafts.length, 1);
});

test("waits until the draft is at least 0.5 s long", () => {
  const { state, drafts } = make({ preSpeechPadFrames: 0, minSpeechFrames: 2 });
  state.begin();
  state.onFrame(probs(0.9), FRAME);
  state.onFrame(probs(0.9), FRAME);

  state.onFrame(probs(0.1), FRAME); // 288 ms
  state.onFrame(probs(0.1), FRAME); // 384 ms
  state.onFrame(probs(0.1), FRAME); // 480 ms
  assert.equal(drafts.length, 0);

  state.onFrame(probs(0.1), FRAME); // 576 ms
  assert.equal(drafts.length, 1);
});

test("a new valid draft replaces the previous one for commit", () => {
  const { state, drafts } = make();
  start(state);

  state.onFrame(probs(0.1), FRAME);
  state.onFrame(probs(0.1), FRAME);
  state.onFrame(probs(0.9), FRAME);
  state.onFrame(probs(0.1), FRAME);
  state.onFrame(probs(0.1), FRAME);

  assert.equal(drafts.length, 2);
  assert.equal(state.end(), drafts[1].id);
});

test("canDraft=false sends no draft and never commits", () => {
  const { state, drafts } = make({ canDraft: () => false });
  start(state);
  state.onFrame(probs(0.1), FRAME);
  state.onFrame(probs(0.1), FRAME);

  assert.equal(drafts.length, 0);
  assert.equal(state.end(), null);
});

test("misfire resets the utterance state", () => {
  const { state, drafts } = make();
  start(state);
  state.onFrame(probs(0.1), FRAME);
  state.onFrame(probs(0.1), FRAME);
  assert.equal(drafts.length, 1);

  state.misfire();
  assert.equal(state.end(), null);

  start(state);
  state.onFrame(probs(0.1), FRAME);
  state.onFrame(probs(0.1), FRAME);
  assert.equal(drafts.length, 2);
  assert.equal(drafts[1].id, 2);
});

test("a soft mid-band frame after the draft invalidates it, a later pause re-drafts", () => {
  const { state, drafts } = make();
  start(state);

  state.onFrame(probs(0.1), FRAME);
  state.onFrame(probs(0.1), FRAME);
  assert.equal(drafts.length, 1);

  // 0.45 <= p < 0.6: vad-web keeps this frame in the utterance without
  // resetting its tail, so the draft would miss a soft word.
  state.onFrame(probs(0.5), FRAME);
  assert.equal(state.stats().latestDraftId, null);

  state.onFrame(probs(0.1), FRAME);
  state.onFrame(probs(0.1), FRAME);
  assert.equal(drafts.length, 2);
  assert.equal(drafts[1].audio.length, 10 * 1536);
  assert.equal(state.end(), drafts[1].id);
});
