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

// ---------- UI helpers ----------
function setState(text, cls = "idle") {
  stateEl.textContent = text;
  stateEl.className = "state " + cls;
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
async function enqueueAudio(arrayBuf) {
  const view = new DataView(arrayBuf);
  const turn = view.getUint32(0, false);
  if (turn < currentTurn) return; // stale (interrupted) audio
  const wav = arrayBuf.slice(4);
  const buffer = await audioCtx.decodeAudioData(wav);
  playQueue.push({ turn, buffer });
  if (!playing) playNext();
}
function playNext() {
  const item = playQueue.shift();
  if (!item) { playing = null; if (vadInstance) setState("hört zu …", "listening"); return; }
  if (item.turn < currentTurn) return playNext();
  const src = audioCtx.createBufferSource();
  src.buffer = item.buffer;
  src.connect(audioCtx.destination);
  src.onended = () => { if (playing === src) playNext(); };
  playing = src;
  setState("Kerstin spricht …", "speaking");
  src.start();
}
function stopPlayback() {
  playQueue = [];
  if (playing) { try { playing.stop(); } catch {} playing = null; }
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
    case "session": logEl.innerHTML = ""; herBubble = null; currentTurn = 0; break;
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
    case "stt_empty": setState("nicht verstanden – bitte wiederholen", "listening"); break;
    case "reply_text":
      if (msg.turn >= currentTurn) { currentTurn = msg.turn; appendHer(msg.text); }
      break;
    case "reply_done": herBubble = null; break;
    case "reply_interrupted":
      if (herBubble) herBubble.classList.add("interrupted");
      herBubble = null;
      break;
    case "metrics":
      metricsEl.textContent =
        `Turn ${msg.turn}\nAudio: ${msg.audio_s}s\nSTT: ${msg.stt_ms} ms\n` +
        `LLM 1. Token: ${msg.llm_first_token_ms} ms\nErste Audio: ${msg.first_audio_ms} ms\n` +
        `Gesamt: ${msg.total_ms} ms (${msg.sentences} Sätze)`;
      break;
    case "feedback":
      feedbackEl.hidden = false;
      feedbackEl.textContent = msg.markdown; // TODO(ROADMAP): render markdown
      setState("fertig", "idle");
      break;
    case "error": setState("Fehler: " + msg.message, "speaking"); console.error(msg); break;
  }
}

// ---------- start / stop ----------
async function start() {
  $("startBtn").disabled = true;
  audioCtx = audioCtx || new AudioContext();
  await audioCtx.resume();
  feedbackEl.hidden = true;
  if (!ws || ws.readyState !== WebSocket.OPEN) await connect();

  ws.send(JSON.stringify({ type: "start", scenario: $("scenario").value }));

  vadInstance = await vad.MicVAD.new({
    baseAssetPath: "https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.22/dist/",
    onnxWASMBasePath: "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.14.0/dist/",
    positiveSpeechThreshold: 0.6,
    negativeSpeechThreshold: 0.45,
    redemptionFrames: 8,     // ~0.5-0.8 s of silence ends the utterance (tune in docs/LATENCY.md)
    minSpeechFrames: 4,
    onSpeechStart: () => {
      // barge-in: learner starts talking while Kerstin speaks
      if (playing || playQueue.length) {
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
  vadInstance.start();
  $("endBtn").disabled = false;
  setState("hört zu …", "listening");
}

function end() {
  if (vadInstance) { vadInstance.pause(); vadInstance = null; }
  stopPlayback();
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "end" }));
  $("endBtn").disabled = true;
  $("startBtn").disabled = false;
}

async function loadScenarios() {
  const r = await fetch("/api/scenarios");
  const list = await r.json();
  $("scenario").innerHTML = list.map((s) => `<option value="${s.key}">${s.title}</option>`).join("");
}

$("startBtn").onclick = () => start().catch((e) => { console.error(e); setState("Start fehlgeschlagen: " + e, "speaking"); $("startBtn").disabled = false; });
$("endBtn").onclick = end;
loadScenarios();
