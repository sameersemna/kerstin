const test = require("node:test");
const assert = require("node:assert/strict");

const { createMicGate } = require("../mic_gate.js");

function makeGate(options = {}) {
  const calls = { pause: 0, resume: 0 };
  let timers = [];
  const gate = createMicGate({
    mode: "speakers",
    tailMs: 350,
    pauseVad: () => { calls.pause += 1; },
    resumeVad: () => { calls.resume += 1; },
    setTimer: (fn, ms) => {
      const timer = { fn, ms, cleared: false };
      timers.push(timer);
      return timer;
    },
    clearTimer: (timer) => {
      timer.cleared = true;
      const index = timers.indexOf(timer);
      if (index !== -1) timers.splice(index, 1);
    },
    ...options,
  });

  function fire(timer) {
    if (!timer || timer.cleared) return;
    timer.cleared = true;
    const index = timers.indexOf(timer);
    if (index !== -1) timers.splice(index, 1);
    timer.fn();
  }

  return { gate, calls, timers, fire };
}

test("speakers: pauses on start and resumes only after reply-done, idle and tail", () => {
  const { gate, calls, timers, fire } = makeGate();

  gate.playbackStarted(1);
  assert.equal(calls.pause, 1);
  assert.equal(gate.isListening(), false);

  gate.replyFinished(1);
  assert.equal(calls.resume, 0);
  assert.equal(timers.length, 0);

  gate.playbackIdle();
  assert.equal(calls.resume, 0);
  assert.equal(timers.length, 1);
  assert.equal(timers[0].ms, 350);

  fire(timers[0]);
  assert.equal(calls.resume, 1);
  assert.equal(gate.isListening(), true);
});

test("speakers: new playback during the tail cancels the resume", () => {
  const { gate, calls, timers, fire } = makeGate();

  gate.playbackStarted(1);
  gate.replyFinished(1);
  gate.playbackIdle();
  const tail = timers[0];

  gate.playbackStarted(1);
  assert.equal(tail.cleared, true);
  assert.equal(timers.length, 0);
  fire(tail);
  assert.equal(calls.resume, 0);

  gate.playbackIdle();
  assert.equal(timers.length, 1);
  fire(timers[0]);
  assert.equal(calls.resume, 1);
});

test("speakers: userInterrupt resumes immediately without the tail", () => {
  const { gate, calls, timers } = makeGate();

  gate.playbackStarted(1);
  gate.replyFinished(1);
  gate.playbackIdle();
  assert.equal(timers.length, 1);

  gate.userInterrupt();
  assert.equal(calls.resume, 1);
  assert.equal(gate.isListening(), true);
  assert.equal(timers.length, 0);
});

test("headphones: never pauses and has no tail timer", () => {
  const { gate, calls, timers } = makeGate({ mode: "headphones" });

  gate.playbackStarted(1);
  gate.replyFinished(1);
  gate.playbackIdle();
  gate.userInterrupt();

  assert.equal(calls.pause, 0);
  assert.equal(calls.resume, 0);
  assert.equal(timers.length, 0);
  assert.equal(gate.isListening(), true);
});

test("switching to headphones while paused resumes immediately", () => {
  const { gate, calls, timers } = makeGate();

  gate.playbackStarted(1);
  assert.equal(calls.pause, 1);
  assert.equal(gate.isListening(), false);

  gate.setMode("headphones");
  assert.equal(calls.resume, 1);
  assert.equal(gate.isListening(), true);
  assert.equal(timers.length, 0);
});

test("speakers: pauseVad is called only once per reply", () => {
  const { gate, calls, timers, fire } = makeGate();

  gate.playbackStarted(1);
  gate.playbackStarted(1);
  gate.playbackStarted(1);
  assert.equal(calls.pause, 1);

  gate.replyFinished(1);
  gate.playbackIdle();
  fire(timers[0]);
  assert.equal(calls.resume, 1);

  gate.playbackStarted(2);
  assert.equal(calls.pause, 2);
});

test("replyFinished before playbackStarted still resumes after idle and tail", () => {
  const { gate, calls, timers, fire } = makeGate();

  gate.replyFinished(1);
  assert.equal(calls.pause, 0);
  assert.equal(timers.length, 0);

  gate.playbackStarted(1);
  assert.equal(calls.pause, 1);
  gate.playbackIdle();
  assert.equal(timers.length, 1);
  fire(timers[0]);
  assert.equal(calls.resume, 1);
  assert.equal(gate.isListening(), true);
});

test("same turn starting during the tail cancels and reschedules", () => {
  const { gate, calls, timers, fire } = makeGate();

  gate.playbackStarted(1);
  gate.playbackIdle();
  assert.equal(timers.length, 0);

  gate.replyFinished(1);
  const tail = timers[0];
  assert.equal(tail.ms, 350);

  gate.playbackStarted(1);
  assert.equal(tail.cleared, true);
  assert.equal(calls.resume, 0);

  gate.playbackIdle();
  assert.equal(timers.length, 1);
  fire(timers[0]);
  assert.equal(calls.resume, 1);
  assert.equal(gate.isListening(), true);
});

test("never stuck: finished plus idle resumes after the tail in any order", () => {
  const sequences = [
    (gate) => {
      gate.replyFinished(1);
      gate.playbackStarted(1);
      gate.playbackIdle();
    },
    (gate) => {
      gate.playbackStarted(1);
      gate.replyFinished(1);
      gate.playbackIdle();
    },
    (gate) => {
      gate.playbackStarted(1);
      gate.playbackIdle();
      gate.replyFinished(1);
    },
    (gate) => {
      gate.playbackStarted(1);
      gate.playbackIdle();
      gate.replyFinished();
    },
  ];

  for (const sequence of sequences) {
    const { gate, calls, timers, fire } = makeGate();
    sequence(gate);
    assert.equal(gate.isListening(), false);
    assert.equal(timers.length, 1);
    fire(timers[0]);
    assert.equal(calls.resume, 1);
    assert.equal(gate.isListening(), true);
  }
});
