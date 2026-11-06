// Pure exam-UI logic (no DOM) so it can be tested with `node --test`.
(function (root) {
  "use strict";

  function cardLines(kind, card) {
    if (!card) return null;
    if (kind === "kerstin_talk") {
      return { heading: card.title || "", items: [] };
    }
    if (card.question) {
      return { heading: card.question, items: Array.isArray(card.aspects) ? card.aspects : [] };
    }
    if (card.situation) {
      return { heading: card.situation, items: Array.isArray(card.points) ? card.points : [] };
    }
    return { heading: card.title || "", items: Array.isArray(card.points) ? card.points : [] };
  }

  function nextButton(state) {
    const kind = state && state.kind;
    if (kind === "done") return { label: "Prüfung beendet", enabled: false };
    if (kind === "prep") return { label: "Ich bin bereit", enabled: true };
    if (kind === "learner_talk" && !state.followupSent) {
      return { label: "Fertig", enabled: true };
    }
    if (state && state.isLast) return { label: "Prüfung beenden", enabled: true };
    return { label: "Weiter", enabled: true };
  }

  function autoAction(kind, elapsedS, seconds, followupSent) {
    if (kind === "prep" && elapsedS >= seconds) return "advance";
    if (kind === "learner_talk" && !followupSent && elapsedS >= seconds + 30) {
      return "finish_talk";
    }
    return null;
  }

  function formatClock(remainingS) {
    if (!Number.isFinite(remainingS) || remainingS <= 0) return "Zeit um";
    const total = Math.ceil(remainingS);
    const minutes = Math.floor(total / 60);
    const seconds = total % 60;
    return `${minutes}:${String(seconds).padStart(2, "0")}`;
  }

  const api = { cardLines, nextButton, autoAction, formatClock };
  root.ExamUI = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
