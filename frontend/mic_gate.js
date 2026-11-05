// Mic gate for speaker vs. headphone mode.
// Speaker mode pauses VAD while Kerstin speaks; headphone mode leaves it running.
(function (root) {
  "use strict";

  function createMicGate({
    mode = "speakers",
    tailMs = 350,
    pauseVad = () => {},
    resumeVad = () => {},
    setTimer = (fn, ms) => setTimeout(fn, ms),
    clearTimer = (id) => clearTimeout(id),
  } = {}) {
    let currentMode = mode === "headphones" ? "headphones" : "speakers";
    let paused = false;
    let playing = false;
    let idle = true;
    let playedTurn = -1;
    let doneTurn = -1;
    let timer = null;

    function cancelTimer() {
      if (timer !== null) {
        clearTimer(timer);
        timer = null;
      }
    }

    function finishResume() {
      if (!paused) return;
      paused = false;
      resumeVad();
    }

    function pauseForPlayback() {
      if (currentMode !== "speakers" || paused) return;
      paused = true;
      pauseVad();
    }

    function maybeResume() {
      if (currentMode !== "speakers" || !paused || !idle || timer !== null) return;
      if (doneTurn < playedTurn) return;
      timer = setTimer(() => {
        timer = null;
        finishResume();
      }, tailMs);
    }

    function playbackStarted(turn) {
      if (timer !== null) cancelTimer();
      const turnId = Number.isFinite(turn) ? turn : 0;
      playedTurn = Math.max(playedTurn, turnId);
      playing = true;
      idle = false;
      pauseForPlayback();
    }

    function replyFinished(turn) {
      doneTurn = Math.max(doneTurn, turn == null ? playedTurn : turn);
      maybeResume();
    }

    function playbackIdle() {
      playing = false;
      idle = true;
      maybeResume();
    }

    function userInterrupt() {
      cancelTimer();
      playing = false;
      idle = true;
      finishResume();
    }

    function setMode(nextMode) {
      nextMode = nextMode === "headphones" ? "headphones" : "speakers";
      if (nextMode === currentMode) return;
      currentMode = nextMode;

      if (currentMode === "headphones") {
        cancelTimer();
        if (paused) {
          paused = false;
          resumeVad();
        }
        return;
      }

      if (playing) {
        idle = false;
        pauseForPlayback();
      }
    }

    return {
      playbackStarted,
      replyFinished,
      playbackIdle,
      userInterrupt,
      setMode,
      isListening: () => !paused,
      getMode: () => currentMode,
    };
  }

  root.createMicGate = createMicGate;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = { createMicGate };
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
