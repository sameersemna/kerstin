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
    let activeReply = false;
    let replyDone = false;
    let timer = null;

    function cancelTimer() {
      if (timer !== null) {
        clearTimer(timer);
        timer = null;
      }
    }

    function finishResume() {
      replyDone = false;
      activeReply = false;
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
      if (currentMode !== "speakers" || !paused || !activeReply || !replyDone || !idle) return;
      if (timer !== null) return;
      timer = setTimer(() => {
        timer = null;
        finishResume();
      }, tailMs);
    }

    function playbackStarted() {
      if (timer !== null) cancelTimer();
      if (!activeReply || idle) {
        replyDone = false;
        activeReply = true;
      }
      playing = true;
      idle = false;
      pauseForPlayback();
    }

    function replyFinished() {
      if (currentMode === "headphones" || !activeReply) return;
      replyDone = true;
      maybeResume();
    }

    function playbackIdle() {
      playing = false;
      idle = true;
      if (currentMode === "headphones") {
        activeReply = false;
        replyDone = false;
        return;
      }
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
        replyDone = false;
        activeReply = false;
        if (paused) {
          paused = false;
          resumeVad();
        }
        return;
      }

      if (playing) {
        activeReply = true;
        replyDone = false;
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
