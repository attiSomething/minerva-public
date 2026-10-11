// Read aloud: speaks a draft with the computer's own voices, a line at a
// time, selecting each line in the editor as it's read. A blank line (a
// stanza break) gets a short pause. It starts at the cursor, or reads just
// the selection when there is one. Nothing leaves the computer when a voice
// installed on it is chosen (the default).
// Used by app.js (the entry page) and focus.js (focus mode).

const readState = { lines: [], i: 0, playing: false, textarea: null, bar: null, timer: null, gen: 0 };
const READ_RATES = [["0.75", "Slower"], ["0.9", "A little slower"], ["1", "Normal"], ["1.15", "A little faster"], ["1.3", "Faster"]];
const STANZA_PAUSE_MS = 450;

function readAloudAvailable() {
  return typeof window.speechSynthesis !== "undefined" && typeof window.SpeechSynthesisUtterance !== "undefined";
}

function readPref(key, fallback) {
  try { return localStorage.getItem(`minerva-read-${key}`) || fallback; } catch (e) { return fallback; }
}

function setReadPref(key, value) {
  try { localStorage.setItem(`minerva-read-${key}`, value); } catch (e) { /* private window */ }
}

// Voices on this computer first; online ones are marked.
function readVoices() {
  const all = window.speechSynthesis.getVoices();
  return all.slice().sort((a, b) => (b.localService - a.localService) || (b.default - a.default) || a.name.localeCompare(b.name));
}

function voiceOptionsHtml() {
  const saved = readPref("voice", "");
  const voices = readVoices();
  if (!voices.length) return `<option value="">System voice</option>`;
  const pick = voices.some((v) => v.name === saved) ? saved : (voices.find((v) => v.localService) || voices[0]).name;
  return voices.map((v) => `<option value="${esc(v.name)}" ${v.name === pick ? "selected" : ""}>${esc(v.name)}${v.localService ? "" : " (online)"}</option>`).join("");
}

// The lines to read, with where each sits in the text, skipping a
// transcription header ("Source: ..." lines closed by a ==== line).
function readableLines(text, from, to) {
  const out = [];
  let pos = 0;
  const all = text.split("\n");
  let skipUntil = -1;
  for (let k = 0; k < Math.min(all.length, 14); k++) {
    if (all[k].trim() && /^=+$/.test(all[k].trim())) {
      if (all.slice(0, k).some((l) => /^\s*(Source|Category|Date|Location|Time)\s*:/i.test(l))) skipUntil = k;
      break;
    }
  }
  all.forEach((line, k) => {
    const start = pos;
    const end = pos + line.length;
    pos = end + 1;
    if (k <= skipUntil || end < from || start > to) return;
    out.push({ text: line.trim(), start, end });
  });
  return out;
}

function readBarHtml(id) {
  return `<div class="read-bar" id="${id}" role="region" aria-label="Read aloud">
    <button class="btn btn-small" data-read-play>Pause</button>
    <button class="btn btn-small btn-ghost" data-read-stop>Stop</button>
    <label>Speed <select data-read-rate>${READ_RATES.map(([v, l]) => `<option value="${v}" ${v === readPref("rate", "1") ? "selected" : ""}>${l}</option>`).join("")}</select></label>
    <label>Voice <select data-read-voice>${voiceOptionsHtml()}</select></label>
    <span class="read-progress muted" data-read-progress></span>
  </div>`;
}

// Start reading the given textarea. The bar goes after `anchor`.
function startReading(textarea, anchor, barId) {
  if (!readAloudAvailable()) { toast("This computer has no voices for reading aloud.", true); return; }
  stopReading();
  const text = textarea.value;
  const selStart = textarea.selectionStart || 0;
  const selEnd = textarea.selectionEnd || 0;
  const hasSel = selEnd > selStart;
  let lines = readableLines(text, hasSel ? selStart : 0, hasSel ? selEnd : text.length);
  if (!hasSel && selStart > 0 && selStart < text.length) {
    // start at the line the cursor is on
    const at = lines.findIndex((l) => l.end >= selStart);
    if (at > 0) lines = lines.slice(at);
  }
  if (!lines.some((l) => l.text)) { toast("There's nothing here to read."); return; }
  readState.lines = lines;
  readState.i = 0;
  readState.textarea = textarea;
  // Typing stops the reader. The line being read is selected, so the
  // selection collapses first: a keystroke must never replace that line.
  textarea.addEventListener("keydown", stopOnTyping);
  textarea.addEventListener("input", stopReading, { once: true });
  anchor.insertAdjacentHTML("afterend", readBarHtml(barId));
  const bar = document.getElementById(barId);
  readState.bar = bar;
  bar.querySelector("[data-read-play]").addEventListener("click", () => (readState.playing ? pauseReading() : resumeReading()));
  bar.querySelector("[data-read-stop]").addEventListener("click", stopReading);
  bar.querySelector("[data-read-rate]").addEventListener("change", (ev) => { setReadPref("rate", ev.target.value); restartLine(); });
  bar.querySelector("[data-read-voice]").addEventListener("change", (ev) => { setReadPref("voice", ev.target.value); restartLine(); });
  // voices can arrive after the page loads
  window.speechSynthesis.onvoiceschanged = () => {
    const sel = bar.querySelector("[data-read-voice]");
    if (sel) sel.innerHTML = voiceOptionsHtml();
  };
  resumeReading();
}

function stopOnTyping(ev) {
  const t = ev.currentTarget;
  t.removeEventListener("keydown", stopOnTyping);
  if (readState.textarea !== t || !readState.bar) return;
  if (["Shift", "Control", "Alt", "Meta"].includes(ev.key)) { t.addEventListener("keydown", stopOnTyping); return; }
  const end = t.selectionEnd;
  t.setSelectionRange(end, end);
  stopReading();
}

function restartLine() {
  if (!readState.playing) return;
  pauseReading();
  resumeReading();
}

function resumeReading() {
  readState.playing = true;
  const btn = readState.bar && readState.bar.querySelector("[data-read-play]");
  if (btn) btn.textContent = "Pause";
  speakNext();
}

function pauseReading() {
  readState.playing = false;
  readState.gen += 1;  // the line being spoken finishes silently and doesn't advance
  clearTimeout(readState.timer);
  window.speechSynthesis.cancel();
  const btn = readState.bar && readState.bar.querySelector("[data-read-play]");
  if (btn) btn.textContent = "Resume";
}

function stopReading() {
  readState.playing = false;
  readState.gen += 1;
  clearTimeout(readState.timer);
  if (readAloudAvailable()) window.speechSynthesis.cancel();
  if (readState.bar) readState.bar.remove();
  readState.bar = null;
  readState.lines = [];
}

function speakNext() {
  if (!readState.playing) return;
  const { lines, textarea } = readState;
  if (readState.i >= lines.length || !document.body.contains(textarea)) { stopReading(); return; }
  const line = lines[readState.i];
  const progress = readState.bar.querySelector("[data-read-progress]");
  const total = lines.filter((l) => l.text).length;
  const done = lines.slice(0, readState.i + 1).filter((l) => l.text).length;
  if (progress) progress.textContent = `Line ${done} of ${total}`;
  const gen = readState.gen;
  if (!line.text) {
    readState.i += 1;
    readState.timer = setTimeout(() => { if (gen === readState.gen) speakNext(); }, STANZA_PAUSE_MS);
    return;
  }
  textarea.focus({ preventScroll: true });
  textarea.setSelectionRange(line.start, line.end);
  scrollToSelection(textarea, line.start);
  const u = new SpeechSynthesisUtterance(line.text);
  u.rate = Number(readPref("rate", "1")) || 1;
  const picked = readState.bar.querySelector("[data-read-voice]");
  const voice = readVoices().find((v) => v.name === (picked ? picked.value : readPref("voice", "")));
  if (voice) u.voice = voice;
  u.onend = () => {
    if (gen !== readState.gen) return;
    readState.i += 1;
    speakNext();
  };
  u.onerror = (ev) => {
    if (gen !== readState.gen || ev.error === "interrupted" || ev.error === "canceled") return;
    toast("Reading aloud stopped: the voice didn't work. Try another voice.", true);
    stopReading();
  };
  window.speechSynthesis.speak(u);
}

// Keep the line being read in view without moving the page around it.
function scrollToSelection(textarea, pos) {
  const lineNo = textarea.value.slice(0, pos).split("\n").length - 1;
  const lh = parseFloat(getComputedStyle(textarea).lineHeight) || 20;
  const y = lineNo * lh;
  if (y < textarea.scrollTop || y > textarea.scrollTop + textarea.clientHeight - lh * 2) {
    textarea.scrollTop = Math.max(0, y - textarea.clientHeight / 3);
  }
}
