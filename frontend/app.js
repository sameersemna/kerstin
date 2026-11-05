// Kerstin browser client.
// - Captures mic with Silero VAD (vad-web); each finished utterance is sent as 16 kHz Int16 PCM.
// - Plays Kerstin's sentence WAVs in order; drops stale audio after barge-in.
// Protocol: docs/PROTOCOL.md

const $ = (id) => document.getElementById(id);
const logEl = $("log"), stateEl = $("state"), metricsEl = $("metrics"), feedbackEl = $("feedback");

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
const MIC_MODE_KEY = "kerstin.micMode";
const FEEDBACK_LANG_KEY = "kerstin.feedbackLang";
try {
  const savedMode = localStorage.getItem(MIC_MODE_KEY);
  if (savedMode === "speakers" || savedMode === "headphones") micMode = savedMode;
  const savedFeedbackLang = localStorage.getItem(FEEDBACK_LANG_KEY);
  if (savedFeedbackLang === "en" || savedFeedbackLang === "de") {
    feedbackLang = savedFeedbackLang;
  }
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
    ws.onclose = () => { setState("Verbindung getrennt", "idle"); };
    ws.onmessage = (ev) => {
      if (ev.data instanceof ArrayBuffer) { enqueueAudio(ev.data); return; }
      handle(JSON.parse(ev.data));
    };
  });
}

function handle(msg) {
  switch (msg.type) {
    case "session":
      logEl.innerHTML = "";
      herBubble = null;
      currentTurn = 0;
      setInterruptEnabled(false);
      if (micGate) micGate.userInterrupt();
      break;
    case "status":
      if (msg.state === "transcribing") setState("verstehe …", "idle");
      else if (msg.state === "thinking") setState("denkt nach …", "idle");
      else if (msg.state === "feedback_running") setState("Feedback wird erstellt …", "idle");
      break;
    case "transcript":
      currentTurn = msg.turn;
      addMsg("me", msg.text);
      herBubble = null;
      break;
    case "stt_empty":
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
      if (msg.turn >= currentTurn) { currentTurn = msg.turn; appendHer(msg.text); }
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
    case "feedback":
      feedbackEl.hidden = false;
      try {
        feedbackEl.replaceChildren(renderMarkdown(msg.markdown));
      } catch {
        feedbackEl.textContent = msg.markdown;
      }
      setState("fertig", "idle");
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
  $("startBtn").disabled = true;
  audioCtx = audioCtx || new AudioContext();
  await audioCtx.resume();
  feedbackEl.hidden = true;
  if (!ws || ws.readyState !== WebSocket.OPEN) await connect();

  vadInstance = await vad.MicVAD.new({
    baseAssetPath: "https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.22/dist/",
    onnxWASMBasePath: "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.14.0/dist/",
    positiveSpeechThreshold: 0.6,
    negativeSpeechThreshold: 0.45,
    redemptionFrames: 8,     // ~0.5-0.8 s of silence ends the utterance (tune in docs/LATENCY.md)
    minSpeechFrames: 4,
    onSpeechStart: () => {
      if (micGate && !micGate.isListening()) return;
      // barge-in: learner starts talking while Kerstin speaks
      if (micGate && micGate.getMode() === "headphones" && isSpeaking()) {
        stopPlayback();
        ws.send(JSON.stringify({ type: "interrupt" }));
      }
      setState("du sprichst …", "listening");
    },
    onSpeechEnd: (audio) => {
      currentTurn += 1; // anything older is now stale
      ws.send(floatTo16BitPCM(audio));
    },
  });
  micGate = createMicGate({
    mode: micMode,
    pauseVad: () => { if (vadInstance) vadInstance.pause(); },
    resumeVad: () => {
      if (!vadInstance) return;
      vadInstance.start();
      setState("hört zu …", "listening");
    },
  });
  vadInstance.start();
  ws.send(JSON.stringify({ type: "start", scenario: $("scenario").value }));
  $("endBtn").disabled = false;
  setState("hört zu …", "listening");
}

function end() {
  if (vadInstance) { vadInstance.pause(); vadInstance = null; }
  stopPlayback();
  if (micGate) micGate.userInterrupt();
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "end", feedback_lang: feedbackLang }));
  }
  $("endBtn").disabled = true;
  $("startBtn").disabled = false;
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

$("startBtn").onclick = () => start().catch((e) => { console.error(e); setState("Start fehlgeschlagen: " + e, "speaking"); $("startBtn").disabled = false; });
$("endBtn").onclick = end;
$("interruptBtn").onclick = interruptSpeaking;
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
loadScenarios();
