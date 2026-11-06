const test = require("node:test");
const assert = require("node:assert/strict");

const { cardLines, nextButton, autoAction, formatClock } = require("../exam_ui.js");

test("cardLines: null card is null", () => {
  assert.equal(cardLines("prep", null), null);
});

test("cardLines: talk cards use title and points", () => {
  assert.deepEqual(
    cardLines("learner_talk", { title: "Reisen", points: ["Ziel", "Erfahrung"] }),
    { heading: "Reisen", items: ["Ziel", "Erfahrung"] }
  );
  assert.deepEqual(
    cardLines("prep", { title: "Reisen", points: ["Ziel"] }),
    { heading: "Reisen", items: ["Ziel"] }
  );
});

test("cardLines: discussion uses question and aspects", () => {
  assert.deepEqual(
    cardLines("dialog", { question: "Homeoffice?", aspects: ["Team", "Zeit"] }),
    { heading: "Homeoffice?", items: ["Team", "Zeit"] }
  );
});

test("cardLines: planning uses situation and points", () => {
  assert.deepEqual(
    cardLines("dialog", { situation: "Plant ein Fest.", points: ["Ort", "Essen"] }),
    { heading: "Plant ein Fest.", items: ["Ort", "Essen"] }
  );
});

test("cardLines: Kerstin's talk has title only", () => {
  assert.deepEqual(cardLines("kerstin_talk", { title: "Mein Weg" }), {
    heading: "Mein Weg",
    items: [],
  });
});

test("nextButton: prep, learner talk, other parts and last part", () => {
  assert.deepEqual(nextButton({ kind: "done", isLast: true, followupSent: true }), {
    label: "Prüfung beendet",
    enabled: false,
  });
  assert.deepEqual(nextButton({ kind: "prep", isLast: false, followupSent: false }), {
    label: "Ich bin bereit",
    enabled: true,
  });
  assert.deepEqual(
    nextButton({ kind: "learner_talk", isLast: false, followupSent: false }),
    { label: "Fertig", enabled: true }
  );
  assert.deepEqual(
    nextButton({ kind: "learner_talk", isLast: false, followupSent: true }),
    { label: "Weiter", enabled: true }
  );
  assert.deepEqual(
    nextButton({ kind: "learner_talk", isLast: true, followupSent: true }),
    { label: "Prüfung beenden", enabled: true }
  );
  assert.deepEqual(nextButton({ kind: "kerstin_talk", isLast: false }), {
    label: "Weiter",
    enabled: true,
  });
  assert.deepEqual(nextButton({ kind: "dialog", isLast: false }), {
    label: "Weiter",
    enabled: true,
  });
  assert.deepEqual(nextButton({ kind: "dialog", isLast: true }), {
    label: "Prüfung beenden",
    enabled: true,
  });
});

test("autoAction: prep advances at its deadline", () => {
  assert.equal(autoAction("prep", 299, 300, false), null);
  assert.equal(autoAction("prep", 300, 300, false), "advance");
});

test("autoAction: learner talk finishes at seconds+30 only before follow-up", () => {
  assert.equal(autoAction("learner_talk", 149, 120, false), null);
  assert.equal(autoAction("learner_talk", 150, 120, false), "finish_talk");
  assert.equal(autoAction("learner_talk", 150, 120, true), null);
});

test("autoAction: Kerstin talk and dialog never advance", () => {
  assert.equal(autoAction("kerstin_talk", 999, 1, false), null);
  assert.equal(autoAction("dialog", 999, 1, false), null);
});

test("formatClock: zero, negative and normal values", () => {
  assert.equal(formatClock(0), "Zeit um");
  assert.equal(formatClock(-1), "Zeit um");
  assert.equal(formatClock(5), "0:05");
  assert.equal(formatClock(60), "1:00");
  assert.equal(formatClock(65), "1:05");
  assert.equal(formatClock(90), "1:30");
  assert.equal(formatClock(0.2), "0:01");
});
