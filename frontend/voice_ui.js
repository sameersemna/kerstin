// Pure voice-selector logic (no DOM), tested with node --test.
(function (root) {
  "use strict";

  function voiceOptions(voices, selected) {
    return (voices || []).map((voice) => ({
      value: voice.id,
      label: voice.available === false
        ? `${voice.label} (nicht verfügbar)`
        : voice.label,
      disabled: voice.available === false,
      selected: voice.id === selected,
    }));
  }

  function resolveSelection(voices, stored, defaultId) {
    const list = voices || [];
    if (stored && list.some((voice) => voice.id === stored)) return stored;
    if (list.some((voice) => voice.id === defaultId)) return defaultId;
    return list.length ? list[0].id : "";
  }

  function fallbackText(fallback) {
    return fallback ? "Stimme nicht erreichbar – Piper springt ein" : "";
  }

  const api = { voiceOptions, resolveSelection, fallbackText };
  root.VoiceUI = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
