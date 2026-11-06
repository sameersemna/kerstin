// Kerstin browser client.
// - Captures mic with Silero VAD (vad-web); each finished utterance is sent as 16 kHz Int16 PCM.
// - Plays Kerstin's sentence WAVs in order; drops stale audio after barge-in.
// Protocol: docs/PROTOCOL.md

const $ = (id) => document.getElementById(id);
const logEl = $("log"), stateEl = $("state"), metricsEl = $("metrics"), feedbackEl = $("feedback");
const hintListEl = $("hintList"), hintInputEl = $("hintInput"), hintBtn = $("hintBtn");
const mistakeBoxEl = $("mistakeBox"), saveMistakesEl = $("saveMistakes");
const useFocusEl = $("useFocus"), focusTodayEl = $("focusToday");
const mistakeSummaryEl = $("mistakeSummary"), clearMistakesBtn = $("clearMistakes");
const modeEl = $("mode"), scenarioEl = $("scenario"), startBtn = $("startBtn"), endBtn = $("endBtn");
const examPanelEl = $("examPanel"), examTitleEl = $("examTitle"), examNoteEl = $("examNote");
const examPartEl = $("examPart"), examUiTextEl = $("examUiText"), examCardEl = $("examCard");
const examClockEl = $("examClock"), examNextBtnEl = $("examNextBtn"), examDoneMsgEl = $("examDoneMsg");
const scoreBoxEl = $("scoreBox"), scoreNoteEl = $("scoreNote"), scoreSummaryEl = $("scoreSummary");
const scoreTableEl = $("scoreTable"), scoreRowsEl = $("scoreRows"), scoreMessageEl = $("scoreMessage");

let ws = null;
let vadInstance = null;
let audioCtx = null;
let currentTurn = 0;          // latest turn id we accept audio for
let playQueue = [];           // [{turn, buffer}]
let playing = null;           // current AudioBufferSourceNode
let herBubble = null;         // current Kerstin message element
let micGate = null;
let micMode = "speakers";
let feedbackLang = "en";
let pendingDecodes = 0;
let hintEntries = [];
let examSession = null;
let examPart = null;
let followupSent = false;
let examPrepPaused = false;
let examNextLockedUntil = 0;
let examAutoFired = false;
let examTimer = null;
const MAX_HINTS = 5;
const SCORE_NOTE =
  "Einschätzung aus dem Transkript – keine offizielle Bewertung. " +
  "Aussprache und Flüssigkeit werden nicht bewertet; die Spracherkennung " +
  "kann Fehler glätten oder hinzufügen.";
const HINT_ERRORS = {
  too_long: "zu lang (max. 120 Zeichen)",
  thermal: "GPU zu warm – gleich nochmal",
  failed: "hat nicht geklappt",
};
const MIC_MODE_KEY = "kerstin.micMode";
const FEEDBACK_LANG_KEY = "kerstin.feedbackLang";
const SAVE_MISTAKES_KEY = "kerstin.saveMistakes";
const USE_FOCUS_KEY = "kerstin.useFocus";
let clearMistakesArmed = false;
let clearMistakesTimer = null;
try {
  const savedMode = localStorage.getItem(MIC_MODE_KEY);
  if (savedMode === "speakers" || savedMode === "headphones") micMode = savedMode;
  const savedFeedbackLang = localStorage.getItem(FEEDBACK_LANG_KEY);
  if (savedFeedbackLang === "en" || savedFeedbackLang === "de") {
    feedbackLang = savedFeedbackLang;
  }
  saveMistakesEl.checked = localStorage.getItem(SAVE_MISTAKES_KEY) === "1";
  useFocusEl.checked = localStorage.getItem(USE_FOCUS_KEY) === "1";
} catch {}

// ---------- UI helpers ----------
function setState(text, cls = "idle") {
  stateEl.textContent = text;
  stateEl.className = "state " + cls;
}
function isSpeaking() {
  return Boolean(playing || playQueue.length);
}
function setInterruptEnabled(enabled) {
  $("interruptBtn").disabled = !enabled;
}
function updateSpeakingState() {
  const hint = micGate && !micGate.isListening();
  setState(
    hint ? "Kerstin spricht … (Leertaste = unterbrechen)" : "Kerstin spricht …",
    "speaking"
  );
}
function addMsg(who, text) {
  const el = document.createElement("div");
  el.className = "msg " + (who === "me" ? "me" : "her");
  el.innerHTML = `<span class="who">${who === "me" ? "Du" : "Kerstin"}</span><span class="t"></span>`;
  el.querySelector(".t").textContent = text;
  logEl.appendChild(el);
  el.scrollIntoView({ behavior: "smooth", block: "end" });
  return el;
}
function appendHer(text) {
  if (!herBubble) herBubble = addMsg("her", text);
  else herBubble.querySelector(".t").textContent += " " + text;
}

// ---------- exam panel ----------
function stopExamTimer() {
  if (examTimer !== null) {
    clearInterval(examTimer);
    examTimer = null;
  }
}

function resetExam() {
  stopExamTimer();
  examSession = null;
  examPart = null;
  followupSent = false;
  examPrepPaused = false;
  examNextLockedUntil = 0;
  examAutoFired = false;
  examPanelEl.hidden = true;
  examTitleEl.textContent = "";
  examNoteEl.textContent = "";
  examPartEl.textContent = "";
  examUiTextEl.textContent = "";
  examUiTextEl.hidden = true;
  examCardEl.replaceChildren();
  examCardEl.hidden = true;
  examClockEl.textContent = "";
  examClockEl.hidden = true;
  examNextBtnEl.textContent = "";
  examNextBtnEl.disabled = true;
  examDoneMsgEl.hidden = true;
}

function showExamSession(meta) {
  examSession = meta;
  examPanelEl.hidden = false;
  examTitleEl.textContent = meta.title || "";
  examNoteEl.textContent = meta.note || "";
  examPartEl.textContent = "";
  examUiTextEl.textContent = "";
  examUiTextEl.hidden = true;
  examCardEl.replaceChildren();
  examCardEl.hidden = true;
  examClockEl.textContent = "";
  examClockEl.hidden = true;
  examNextBtnEl.textContent = "";
  examNextBtnEl.disabled = true;
  examDoneMsgEl.hidden = true;
}

function renderExamCard(kind, card) {
  examCardEl.replaceChildren();
  if (!window.ExamUI) {
    examCardEl.hidden = true;
    return;
  }
  const lines = window.ExamUI.cardLines(kind, card);
  if (!lines) {
    examCardEl.hidden = true;
    return;
  }
  if (lines.heading) {
    const heading = document.createElement("h3");
    heading.textContent = lines.heading;
    examCardEl.appendChild(heading);
  }
  if (lines.items.length) {
    const list = document.createElement("ul");
    for (const item of lines.items) {
      const entry = document.createElement("li");
      entry.textContent = item;
      list.appendChild(entry);
    }
    examCardEl.appendChild(list);
  }
  examCardEl.hidden = false;
}

function renderExamNext() {
  if (!examPart) {
    examNextBtnEl.textContent = "";
    examNextBtnEl.disabled = true;
    return;
  }
  const total =
    examSession && Array.isArray(examSession.parts) ? examSession.parts.length : 0;
  const isLast = total > 0 && Number.isInteger(examPart.index) && examPart.index >= total - 1;
  const button = window.ExamUI.nextButton({
    kind: examPart.kind,
    isLast,
    followupSent,
  });
  examNextBtnEl.textContent = button.label;
  examNextBtnEl.disabled = !button.enabled || performance.now() < examNextLockedUntil;
}

function pressExamNext() {
  if (!examPart || examPart.kind === "done") return;
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  const now = performance.now();
  if (now < examNextLockedUntil) return;
  examNextLockedUntil = now + 1000;
  if (examPart.kind === "learner_talk") followupSent = true;
  stopPlayback();
  renderExamNext();
  ws.send(JSON.stringify({ type: "exam_next" }));
  setTimeout(renderExamNext, 1000);
}

function startExamClock(seconds) {
  stopExamTimer();
  const duration = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
  const started = performance.now();
  const tick = () => {
    if (!examPart || examPart.kind === "done") return;
    const elapsed = (performance.now() - started) / 1000;
    examClockEl.textContent = window.ExamUI.formatClock(duration - elapsed);
    const action = window.ExamUI.autoAction(
      examPart.kind,
      elapsed,
      duration,
      followupSent
    );
    if (action && !examAutoFired) {
      examAutoFired = true;
      pressExamNext();
    }
  };
  examClockEl.hidden = false;
  tick();
  examTimer = setInterval(tick, 1000);
}

function setExamPart(msg) {
  examPart = msg;
  followupSent = false;
  examAutoFired = false;
  const total =
    examSession && Array.isArray(examSession.parts) ? examSession.parts.length : 0;
  examPartEl.textContent = `Teil ${msg.index + 1} von ${total} – ${msg.title || ""}`;
  examUiTextEl.textContent = msg.ui_text || "";
  examUiTextEl.hidden = !msg.ui_text;
  renderExamCard(msg.kind, msg.card);
  examDoneMsgEl.hidden = true;
  examPanelEl.hidden = false;
  startExamClock(msg.seconds);
  renderExamNext();
  if (msg.kind === "prep") {
    if (vadInstance) vadInstance.pause();
    examPrepPaused = true;
    setState("Vorbereitung – Mikrofon aus", "idle");
  } else {
    if (examPrepPaused) {
      examPrepPaused = false;
      if (vadInstance && (!micGate || micGate.isListening())) vadInstance.start();
    }
    if (msg.kind === "kerstin_talk") setState("Kerstin spricht …", "speaking");
    else setState("du bist dran …", "listening");
  }
}

function setExamDone() {
  stopExamTimer();
  examPart = { kind: "done" };
  followupSent = true;
  examDoneMsgEl.hidden = false;
  examClockEl.hidden = true;
  examNextBtnEl.textContent = "Prüfung beendet";
  examNextBtnEl.disabled = true;
  if (vadInstance) vadInstance.pause();
  examPrepPaused = false;
  setState("Prüfung beendet", "idle");
  endBtn.disabled = false;
}

function isExamPrep() {
  return Boolean(examPart && examPart.kind === "prep");
}

function examBlocksSpeech() {
  return (
    Boolean(examSession) &&
    (!examPart || examPart.kind === "prep" || examPart.kind === "done")
  );
}

function updateModeControls() {
  const examMode = Boolean(modeEl.value);
  scenarioEl.disabled = examMode;
  useFocusEl.disabled = examMode;
  startBtn.textContent = examMode ? "Prüfung starten" : "Gespräch starten";
}

async function loadExams() {
  try {
    const response = await fetch("/api/exams");
    if (!response.ok) throw new Error("exam list failed");
    const list = await response.json();
    if (!Array.isArray(list)) throw new Error("invalid exam list");
    while (modeEl.options.length > 1) modeEl.remove(1);
    for (const item of list) {
      if (!item || typeof item.key !== "string") continue;
      const option = document.createElement("option");
      option.value = item.key;
      option.textContent = item.title || item.key;
      modeEl.appendChild(option);
    }
    updateModeControls();
  } catch (error) {
    console.warn("exam presets unavailable", error);
  }
}

// ---------- score box ----------
function resetScore() {
  scoreBoxEl.hidden = true;
  scoreNoteEl.textContent = SCORE_NOTE;
  scoreSummaryEl.textContent = "";
  scoreSummaryEl.hidden = true;
  scoreRowsEl.replaceChildren();
  scoreTableEl.hidden = true;
  scoreMessageEl.textContent = "";
  scoreMessageEl.hidden = true;
}

function showScorePending() {
  scoreBoxEl.hidden = false;
  scoreNoteEl.textContent = SCORE_NOTE;
  scoreSummaryEl.hidden = true;
  scoreTableEl.hidden = true;
  scoreRowsEl.replaceChildren();
  scoreMessageEl.textContent = "Einschätzung wird erstellt …";
  scoreMessageEl.hidden = false;
}

function showScoreError(text) {
  scoreBoxEl.hidden = false;
  scoreNoteEl.textContent = SCORE_NOTE;
  scoreSummaryEl.hidden = true;
  scoreTableEl.hidden = true;
  scoreRowsEl.replaceChildren();
  scoreMessageEl.textContent = text || "Einschätzung konnte nicht erstellt werden";
  scoreMessageEl.hidden = false;
}

function renderExamScore(message) {
  scoreBoxEl.hidden = false;
  scoreNoteEl.textContent = message.note || SCORE_NOTE;
  scoreSummaryEl.textContent = message.overall_label
    ? `Gesamt: ${message.overall_label}`
    : "";
  scoreSummaryEl.hidden = !message.overall_label;
  const rows = [];
  for (const criterion of message.criteria || []) {
    const row = document.createElement("tr");
    const name = document.createElement("th");
    name.scope = "row";
    name.textContent = criterion.label || criterion.key || "";
    row.appendChild(name);
    const band = document.createElement("td");
    band.textContent = criterion.band_label || "";
    row.appendChild(band);
    const reason = document.createElement("td");
    reason.textContent = criterion.reason || "";
    row.appendChild(reason);
    const evidence = document.createElement("td");
    if (criterion.evidence) evidence.textContent = `„${criterion.evidence}“`;
    row.appendChild(evidence);
    rows.push(row);
    if (criterion.key === "grammatik") {
      const errorRow = document.createElement("tr");
      const errorCell = document.createElement("td");
      errorCell.colSpan = 4;
      errorCell.className = "score-grammar-count";
      const count = Array.isArray(message.grammar_errors)
        ? message.grammar_errors.length
        : 0;
      errorCell.textContent = `Erkannte Grammatikfehler: ${count}`;
      errorRow.appendChild(errorCell);
      rows.push(errorRow);
    }
  }
  scoreRowsEl.replaceChildren(...rows);
  scoreTableEl.hidden = rows.length === 0;
  scoreMessageEl.textContent = "";
  scoreMessageEl.hidden = true;
}

// ---------- hint panel ----------
function setHintEnabled(enabled) {
  hintInputEl.disabled = !enabled;
  hintBtn.disabled = !enabled;
}
function renderHints() {
  const nodes = [];
  for (const entry of hintEntries) {
    const item = document.createElement("div");
    item.className = "hint-item";

    const query = document.createElement("div");
    query.className = "hint-query";
    const term = document.createElement("strong");
    term.textContent = entry.query;
    query.appendChild(term);
    if (entry.pending) query.appendChild(document.createTextNode(" … frage nach"));
    item.appendChild(query);

    if (entry.error) {
      const error = document.createElement("div");
      error.className = "hint-error";
      error.textContent = HINT_ERRORS[entry.error] || "hat nicht geklappt";
      item.appendChild(error);
    } else if (entry.markdown !== undefined) {
      const answer = document.createElement("div");
      answer.className = "hint-answer";
      try {
        answer.replaceChildren(renderMarkdown(entry.markdown));
      } catch {
        answer.textContent = entry.markdown;
      }
      item.appendChild(answer);
    }
    nodes.push(item);
  }
  hintListEl.replaceChildren(...nodes);
}
function submitHint() {
  const query = hintInputEl.value.trim();
  if (!query || !ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ type: "hint", query }));
  hintEntries.unshift({ query, pending: true });
  hintEntries = hintEntries.slice(0, MAX_HINTS);
  renderHints();
  hintInputEl.value = "";
  hintInputEl.focus();
}
function resolveHint(msg) {
  const index = hintEntries.findIndex((entry) => entry.pending && entry.query === msg.query);
  if (index === -1) {
    hintEntries.unshift({
      query: msg.query,
      markdown: msg.markdown,
      error: msg.error,
    });
    hintEntries = hintEntries.slice(0, MAX_HINTS);
  } else {
    const entry = hintEntries[index];
    entry.pending = false;
    if (msg.error) entry.error = msg.error;
    else entry.markdown = msg.markdown ?? "";
  }
  renderHints();
}

// ---------- mistake summary ----------
function resetClearMistakesPrompt() {
  clearMistakesArmed = false;
  if (clearMistakesTimer) clearTimeout(clearMistakesTimer);
  clearMistakesTimer = null;
  clearMistakesBtn.textContent = "Alle löschen";
}

function renderMistakes(data) {
  mistakeBoxEl.hidden = !data.enabled;
  if (!data.enabled) return;
  const items = data.categories.map((category) => {
    const item = document.createElement("li");
    item.textContent = `${category.label} · ${category.count}`;
    return item;
  });
  if (!items.length) {
    const empty = document.createElement("li");
    empty.className = "mistake-empty";
    empty.textContent = "Noch keine Einträge.";
    items.push(empty);
  }
  mistakeSummaryEl.replaceChildren(...items);
}

async function loadMistakes() {
  try {
    const response = await fetch("/api/mistakes");
    if (!response.ok) throw new Error("summary failed");
    renderMistakes(await response.json());
  } catch {
    mistakeBoxEl.hidden = true;
  }
}

async function clearMistakes() {
  try {
    const response = await fetch("/api/mistakes", { method: "DELETE" });
    if (response.ok) await loadMistakes();
  } catch {}
}

clearMistakesBtn.onclick = () => {
  if (!clearMistakesArmed) {
    clearMistakesArmed = true;
    clearMistakesBtn.textContent = "Wirklich löschen?";
    clearMistakesTimer = setTimeout(resetClearMistakesPrompt, 5000);
    return;
  }
  resetClearMistakesPrompt();
  clearMistakes();
};
saveMistakesEl.onchange = () => {
  try { localStorage.setItem(SAVE_MISTAKES_KEY, saveMistakesEl.checked ? "1" : "0"); } catch {}
};
useFocusEl.onchange = () => {
  try { localStorage.setItem(USE_FOCUS_KEY, useFocusEl.checked ? "1" : "0"); } catch {}
};

// ---------- audio playback ----------
function maybePlaybackIdle() {
  if (playing || playQueue.length || pendingDecodes > 0) return;
  setInterruptEnabled(false);
  if (micGate) micGate.playbackIdle();
  if (vadInstance && (!micGate || micGate.isListening())) {
    setState("hört zu …", "listening");
  }
}
async function enqueueAudio(arrayBuf) {
  const view = new DataView(arrayBuf);
  const turn = view.getUint32(0, false);
  if (turn < currentTurn) { // stale (interrupted) audio
    maybePlaybackIdle();
    return;
  }
  pendingDecodes += 1;
  try {
    const wav = arrayBuf.slice(4);
    const buffer = await audioCtx.decodeAudioData(wav);
    if (turn < currentTurn) return;
    playQueue.push({ turn, buffer });
    if (!playing) playNext();
  } finally {
    pendingDecodes -= 1;
    maybePlaybackIdle();
  }
}
function playNext() {
  const item = playQueue.shift();
  if (!item) {
    playing = null;
    setInterruptEnabled(false);
    maybePlaybackIdle();
    return;
  }
  if (item.turn < currentTurn) return playNext();
  const src = audioCtx.createBufferSource();
  src.buffer = item.buffer;
  src.connect(audioCtx.destination);
  src.onended = () => { if (playing === src) playNext(); };
  playing = src;
  if (micGate) micGate.playbackStarted(item.turn);
  setInterruptEnabled(true);
  updateSpeakingState();
  src.start();
}
function stopPlayback() {
  playQueue = [];
  if (playing) { try { playing.stop(); } catch {} playing = null; }
  setInterruptEnabled(false);
  maybePlaybackIdle();
}

// ---------- PCM conversion ----------
function floatTo16BitPCM(float32) {
  const out = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i++) {
    const s = Math.max(-1, Math.min(1, float32[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out.buffer;
}

// ---------- websocket ----------
function connect() {
  return new Promise((resolve, reject) => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.binaryType = "arraybuffer";
    ws.onopen = () => resolve();
    ws.onerror = (e) => reject(e);
    ws.onclose = () => {
      setState("Verbindung getrennt", "idle");
      setHintEnabled(false);
    };
    ws.onmessage = (ev) => {
      if (ev.data instanceof ArrayBuffer) { enqueueAudio(ev.data); return; }
      handle(JSON.parse(ev.data));
    };
  });
}

function syncTurn(msg) {
  if (Number.isFinite(msg.turn) && msg.turn > currentTurn) currentTurn = msg.turn;
}

function handle(msg) {
  switch (msg.type) {
    case "session":
      logEl.innerHTML = "";
      herBubble = null;
      currentTurn = 0;
      setInterruptEnabled(false);
      if (micGate) micGate.userInterrupt();
      hintEntries = [];
      renderHints();
      setHintEnabled(true);
      resetExam();
      resetScore();
      modeEl.value = msg.exam && msg.exam.preset ? msg.exam.preset : "";
      updateModeControls();
      if (msg.exam) showExamSession(msg.exam);
      if (Array.isArray(msg.focus) && msg.focus.length) {
        focusTodayEl.textContent = "Heute im Fokus: " + msg.focus.join(", ");
        focusTodayEl.hidden = false;
      } else {
        focusTodayEl.textContent = "";
        focusTodayEl.hidden = true;
      }
      break;
    case "hint":
      resolveHint(msg);
      break;
    case "status":
      syncTurn(msg);
      if (msg.state === "transcribing") setState("verstehe …", "idle");
      else if (msg.state === "thinking") setState("denkt nach …", "idle");
      else if (msg.state === "feedback_running") setState("Feedback wird erstellt …", "idle");
      else if (msg.state === "score_running") {
        setState("Einschätzung wird erstellt …", "idle");
        showScorePending();
      }
      break;
    case "transcript":
      syncTurn(msg);
      addMsg("me", msg.text);
      herBubble = null;
      break;
    case "collected":
      syncTurn(msg);
      if (micGate) micGate.replyFinished(msg.turn);
      setState("Kerstin hört zu …", "listening");
      break;
    case "stt_empty":
      syncTurn(msg);
      if (msg.reason === "prep") {
        setState("Vorbereitung – Mikrofon aus", "idle");
        break;
      }
      if (micGate && !micGate.isListening()) micGate.replyFinished(msg.turn);
      if (!micGate || micGate.isListening()) {
        setState("nicht verstanden – bitte wiederholen", "listening");
      }
      break;
    case "thermal":
      if (micGate) micGate.replyFinished(msg.turn);
      setState(
        `GPU zu warm (${msg.temp_c} °C) – kurze Pause, bitte gleich nochmal versuchen`,
        "speaking"
      );
      if (msg.turn === undefined) $("startBtn").disabled = false;
      break;
    case "reply_text":
      syncTurn(msg);
      if (msg.turn >= currentTurn) appendHer(msg.text);
      break;
    case "exam_part":
      if (msg.kind === "done") setExamDone();
      else setExamPart(msg);
      break;
    case "reply_done":
      if (micGate) micGate.replyFinished(msg.turn);
      herBubble = null;
      break;
    case "reply_interrupted":
      if (micGate) micGate.replyFinished(msg.turn);
      if (herBubble) herBubble.classList.add("interrupted");
      herBubble = null;
      break;
    case "metrics":
      metricsEl.textContent =
        `Turn ${msg.turn}\nAudio: ${msg.audio_s}s\nPegel: ${msg.audio_dbfs.toFixed(1)} dBFS\nSTT: ${msg.stt_ms} ms\n` +
        `LLM 1. Token: ${msg.llm_first_token_ms} ms\nErste Audio: ${msg.first_audio_ms} ms\n` +
        `Gesamt: ${msg.total_ms} ms (${msg.sentences} Sätze)`;
      break;
    case "exam_score":
      if (msg.error) {
        showScoreError(msg.error);
        setState("Einschätzung nicht möglich", "idle");
      } else {
        renderExamScore(msg);
        setState("fertig", "idle");
      }
      break;
    case "feedback":
      feedbackEl.hidden = false;
      try {
        feedbackEl.replaceChildren(renderMarkdown(msg.markdown));
      } catch {
        feedbackEl.textContent = msg.markdown;
      }
      setState("fertig", "idle");
      break;
    case "mistakes_saved":
      loadMistakes();
      break;
    case "error":
      if (micGate) micGate.replyFinished(msg.turn);
      setState("Fehler: " + msg.message, "speaking");
      console.error(msg);
      break;
  }
}

// ---------- start / stop ----------
async function start() {
  if (!window.vad) {
    setState("Fehlende Dateien – bitte ‚make vendor‘ ausführen", "idle");
    startBtn.disabled = false;
    return;
  }
  startBtn.disabled = true;
  setHintEnabled(false);
  audioCtx = audioCtx || new AudioContext();
  await audioCtx.resume();
  feedbackEl.hidden = true;
  resetExam();
  resetScore();
  if (!ws || ws.readyState !== WebSocket.OPEN) await connect();

  vadInstance = await window.vad.MicVAD.new({
    baseAssetPath: "vendor/vad-web/",
    onnxWASMBasePath: "vendor/onnxruntime-web/",
    positiveSpeechThreshold: 0.6,
    negativeSpeechThreshold: 0.45,
    redemptionFrames: 8,     // ~0.5-0.8 s of silence ends the utterance (tune in docs/LATENCY.md)
    minSpeechFrames: 4,
    onSpeechStart: () => {
      if (examBlocksSpeech()) return;
      if (micGate && !micGate.isListening()) return;
      // barge-in: learner starts talking while Kerstin speaks
      if (micGate && micGate.getMode() === "headphones" && isSpeaking()) {
        stopPlayback();
        ws.send(JSON.stringify({ type: "interrupt" }));
      }
      setState("du sprichst …", "listening");
    },
    onSpeechEnd: (audio) => {
      if (examBlocksSpeech()) return;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      currentTurn += 1; // anything older is now stale
      ws.send(floatTo16BitPCM(audio));
    },
  });
  micGate = createMicGate({
    mode: micMode,
    pauseVad: () => { if (vadInstance) vadInstance.pause(); },
    resumeVad: () => {
      if (!vadInstance) return;
      if (isExamPrep()) {
        setState("Vorbereitung – Mikrofon aus", "idle");
        return;
      }
      vadInstance.start();
      setState("hört zu …", "listening");
    },
  });
  vadInstance.start();
  const payload = {
    type: "start",
    scenario: scenarioEl.value,
    use_focus: useFocusEl.checked,
  };
  if (modeEl.value) payload.exam = modeEl.value;
  ws.send(JSON.stringify(payload));
  endBtn.disabled = false;
  setState("hört zu …", "listening");
}

function end() {
  stopExamTimer();
  if (examPart && examPart.kind !== "done") examNextBtnEl.disabled = true;
  examPrepPaused = false;
  if (vadInstance) { vadInstance.pause(); vadInstance = null; }
  stopPlayback();
  if (micGate) micGate.userInterrupt();
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type: "end",
      feedback_lang: feedbackLang,
      save_mistakes: saveMistakesEl.checked,
    }));
  }
  endBtn.disabled = true;
  startBtn.disabled = false;
  setHintEnabled(false);
}

function interruptSpeaking() {
  if (!isSpeaking()) return;
  stopPlayback();
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "interrupt" }));
  }
  if (micGate) micGate.userInterrupt();
  if (vadInstance) setState("hört zu …", "listening");
}

async function loadScenarios() {
  const r = await fetch("/api/scenarios");
  const list = await r.json();
  $("scenario").innerHTML = list.map((s) => `<option value="${s.key}">${s.title}</option>`).join("");
}

startBtn.onclick = () => start().catch((e) => { console.error(e); setState("Start fehlgeschlagen: " + e, "speaking"); startBtn.disabled = false; });
endBtn.onclick = end;
$("interruptBtn").onclick = interruptSpeaking;
examNextBtnEl.onclick = pressExamNext;
modeEl.onchange = updateModeControls;
$("hintBtn").onclick = submitHint;
$("hintInput").addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  e.preventDefault();
  submitHint();
});
$("feedbackLang").value = feedbackLang;
$("feedbackLang").onchange = (e) => {
  feedbackLang = e.target.value === "de" ? "de" : "en";
  try { localStorage.setItem(FEEDBACK_LANG_KEY, feedbackLang); } catch {}
};
$("micMode").value = micMode;
$("micMode").onchange = (e) => {
  micMode = e.target.value === "headphones" ? "headphones" : "speakers";
  try { localStorage.setItem(MIC_MODE_KEY, micMode); } catch {}
  if (!micGate) return;
  const wasPaused = !micGate.isListening();
  micGate.setMode(micMode);
  if (isSpeaking()) updateSpeakingState();
  else if (wasPaused && vadInstance) setState("hört zu …", "listening");
};
document.addEventListener("keydown", (e) => {
  if (e.code !== "Space" || e.repeat) return;
  const target = e.target;
  const tag = target && target.tagName;
  if (target && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT", "BUTTON"].includes(tag))) return;
  if (!isSpeaking()) return;
  e.preventDefault();
  interruptSpeaking();
});
resetScore();
loadScenarios();
loadMistakes();
loadExams();
