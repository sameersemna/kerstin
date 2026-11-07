// Pure early-STT state machine (no DOM/WebSocket), tested with `node --test`.
//
// vad-web calls onFrameProcessed(probs, frame) for every 96 ms frame. We keep
// the last two pre-speech frames, buffer the utterance, and send a draft once
// the learner has been silent for two frames inside the VAD tail. A later
// speech frame invalidates that draft; onSpeechEnd only commits the latest one.
(function (root) {
  "use strict";

  const DEFAULTS = {
    positiveThreshold: 0.6,
    negativeThreshold: 0.45,
    frameMs: 96,
    minSpeechFrames: 4,
    preSpeechPadFrames: 2,
    pauseFrames: 2,
    maxDrafts: 3,
    minDraftMs: 500,
    canDraft: () => true,
    onDraft: () => {},
  };

  function probability(probs) {
    const value = probs && probs.isSpeech;
    return Number.isFinite(value) ? value : 0;
  }

  function concatFrames(frames) {
    const total = frames.reduce((sum, entry) => sum + entry.length, 0);
    const audio = new Float32Array(total);
    let offset = 0;
    for (const entry of frames) {
      audio.set(entry, offset);
      offset += entry.length;
    }
    return audio;
  }

  function createEarlySTT(options = {}) {
    const cfg = { ...DEFAULTS, ...options };
    let nextDraftId = 1;
    let speaking = false;
    let ring = [];
    let frames = [];
    let speechFrames = 0;
    let negativeRun = 0;
    let draftsSent = 0;
    let latest = null;
    let pauseDraftSent = false;

    function reset() {
      speaking = false;
      ring = [];
      frames = [];
      speechFrames = 0;
      negativeRun = 0;
      draftsSent = 0;
      latest = null;
      pauseDraftSent = false;
    }

    function begin() {
      // The frame that triggered SpeechStart was already delivered to
      // onFrameProcessed, so it (and the pad) is in the ring.
      speaking = true;
      frames = ring.slice();
      ring = [];
      speechFrames = frames.filter(
        (entry) => entry.probability >= cfg.positiveThreshold
      ).length;
      negativeRun = 0;
      draftsSent = 0;
      latest = null;
      pauseDraftSent = false;
    }

    function maybeSendDraft() {
      if (pauseDraftSent || draftsSent >= cfg.maxDrafts) return;
      if (speechFrames < cfg.minSpeechFrames) return;
      if (negativeRun < cfg.pauseFrames) return;
      if (frames.length * cfg.frameMs < cfg.minDraftMs) return;
      pauseDraftSent = true;
      if (!cfg.canDraft()) return;

      const draftId = nextDraftId;
      nextDraftId += 1;
      draftsSent += 1;
      latest = { id: draftId, valid: true };
      cfg.onDraft(draftId, concatFrames(frames.map((entry) => entry.frame)));
    }

    function onFrame(probs, frame) {
      if (!frame) return;
      const p = probability(probs);
      if (!speaking) {
        ring.push({ frame, probability: p });
        while (ring.length > cfg.preSpeechPadFrames) ring.shift();
        return;
      }

      frames.push({ frame, probability: p });
      if (p >= cfg.positiveThreshold) {
        speechFrames += 1;
        negativeRun = 0;
        // The learner kept talking: this draft no longer covers the utterance.
        latest = null;
        pauseDraftSent = false;
      } else if (p < cfg.negativeThreshold) {
        negativeRun += 1;
        maybeSendDraft();
      } else {
        // Mid-band frames (between the thresholds) do not end the VAD tail
        // but are part of the final audio; a soft word here would be missing
        // from the draft, so invalidate it and let a later pause re-draft.
        negativeRun = 0;
        latest = null;
        pauseDraftSent = false;
      }
    }

    function end() {
      const commitId =
        speaking && latest && latest.valid && cfg.canDraft() ? latest.id : null;
      reset();
      return commitId;
    }

    function misfire() {
      reset();
    }

    function resetSession() {
      reset();
      nextDraftId = 1;
    }

    return {
      begin,
      onFrame,
      end,
      misfire,
      reset,
      resetSession,
      stats: () => ({
        draftsSent,
        latestDraftId: latest ? latest.id : null,
        speaking,
      }),
    };
  }

  const api = { createEarlySTT };
  root.EarlySTT = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
