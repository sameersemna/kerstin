const test = require("node:test");
const assert = require("node:assert/strict");

const { voiceOptions, resolveSelection, fallbackText } = require("../voice_ui.js");

const voices = [
  { id: "kokoro-kerstin", label: "Kerstin (Kokoro)", available: true },
  { id: "kokoro-thorsten", label: "Thorsten (Kokoro)", available: false },
  { id: "piper-thorsten", label: "Thorsten (Piper)", available: true },
];

test("voiceOptions marks unavailable entries and selection", () => {
  assert.deepEqual(voiceOptions(voices, "piper-thorsten"), [
    { value: "kokoro-kerstin", label: "Kerstin (Kokoro)", disabled: false, selected: false },
    {
      value: "kokoro-thorsten",
      label: "Thorsten (Kokoro) (nicht verfügbar)",
      disabled: true,
      selected: false,
    },
    { value: "piper-thorsten", label: "Thorsten (Piper)", disabled: false, selected: true },
  ]);
});

test("resolveSelection prefers stored then default then first", () => {
  assert.equal(resolveSelection(voices, "piper-thorsten", "kokoro-kerstin"), "piper-thorsten");
  assert.equal(resolveSelection(voices, "gone", "kokoro-kerstin"), "kokoro-kerstin");
  assert.equal(resolveSelection(voices, "gone", "gone"), "kokoro-kerstin");
  assert.equal(resolveSelection([], "x", "y"), "");
});

test("fallbackText is the UI line only while fallback is active", () => {
  assert.equal(fallbackText(true), "Stimme nicht erreichbar – Piper springt ein");
  assert.equal(fallbackText(false), "");
});
