// Narration: read an entry or a project into an audio file, with this
// computer's voices or ElevenLabs. Opened from the entry Share panel and
// the project Publish panel (sharing.js). The work runs as a background
// job; the result lands in Exports like any other export.

const narr = { short: null, target: null, opts: null, elVoices: null, account: null, jobId: null, timer: null };

HELP_TOPICS.narration = { kind: "howto", name: "11 - Narration and Video.html" };
HELP_TOPICS["narration-cost"] = { kind: "howto", name: "11 - Narration and Video.html", anchor: "ElevenLabs: cost and privacy" };
HELP_TOPICS["media-tool"] = { kind: "howto", name: "11 - Narration and Video.html", anchor: "The free audio and video tool" };

function closeNarration() {
  clearTimeout(narr.timer);
  const el = document.getElementById("narration");
  if (el) el.remove();
  document.removeEventListener("keydown", narrationKeys);
}

function narrationKeys(ev) {
  if (ev.key === "Escape") closeNarration();
}

// target: { kind: "entry" | "project", id, title, which }
async function openNarration(target) {
  closeNarration();
  narr.target = target;
  const el = document.createElement("div");
  el.id = "narration";
  el.className = "modal-backdrop";
  el.innerHTML = `
    <div class="modal modal-wide" role="dialog" aria-modal="true" aria-labelledby="narr-h">
      <h2 id="narr-h">Narrate ${esc(target.title)}</h2>
      <div id="narr-body"><p class="muted">Looking for voices...</p></div>
    </div>`;
  document.body.appendChild(el);
  document.addEventListener("keydown", narrationKeys);
  try { narr.opts = await api("/api/narration/options"); } catch (e) { toast(e.message, true); closeNarration(); return; }
  const running = narr.opts.jobs.find((j) => j.kind === "narration");
  if (running) { narr.jobId = running.id; pollNarration(); return; }
  renderNarration();
}

function narrValue(id, fallback) {
  const el = document.getElementById(id);
  if (!el) return fallback;
  return el.type === "checkbox" ? el.checked : el.value;
}

function narrChoices() {
  const p = narr.opts.prefs;
  const engine = document.querySelector("input[name=narr-engine]:checked");
  return {
    engine: engine ? engine.value : p.engine,
    voice: narrValue("narr-voice", p.voice),
    el_voice: narrValue("narr-el-voice", p.el_voice),
    pace: narrValue("narr-pace", p.pace),
    split: narrValue("narr-split", p.split),
    format: narrValue("narr-format", p.format),
    titles: narrValue("narr-titles", p.titles),
  };
}

function renderNarration() {
  const o = narr.opts;
  const p = { ...o.prefs, ...(document.getElementById("narr-form") ? narrChoices() : {}) };
  if (!o.system.available && p.engine === "system" && o.elevenlabs.has_key) p.engine = "elevenlabs";
  o.prefs = p;
  const sysVoices = o.system.voices || [];
  const pickSys = sysVoices.some((v) => v.name === p.voice) ? p.voice : o.system.default;
  const body = document.getElementById("narr-body");
  body.innerHTML = `
    <div id="narr-form">
      <div class="narr-engines">
        <label class="narr-engine ${p.engine === "system" ? "on" : ""}"><input type="radio" name="narr-engine" value="system" ${p.engine === "system" ? "checked" : ""}>
          <strong>This computer's voices</strong><span>Free. The writing stays on this computer.</span></label>
        <label class="narr-engine ${p.engine === "elevenlabs" ? "on" : ""}"><input type="radio" name="narr-engine" value="elevenlabs" ${p.engine === "elevenlabs" ? "checked" : ""}>
          <strong>ElevenLabs</strong><span>More natural voices. Uses your account's credits; the text is sent to ElevenLabs.</span></label>
      </div>
      <div id="narr-voice-row">
        ${p.engine === "system" ? (o.system.available
          ? `<div class="field-row"><label for="narr-voice">Voice</label><select id="narr-voice">${sysVoices.map((v) =>
            `<option value="${esc(v.name)}" ${v.name === pickSys ? "selected" : ""}>${esc(v.name)}${v.language ? ` (${esc(v.language)})` : ""}</option>`).join("")}</select></div>`
          : `<p class="warn-text">This computer's voices aren't available here. They come with Windows 10 and 11.</p>`)
        : elevenLabsRowHtml(p)}
      </div>
      <div class="field-row"><label for="narr-pace">Pace</label>
        <select id="narr-pace">${Object.entries(o.paces).map(([k, v]) => `<option value="${k}" ${k === p.pace ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></div>
      ${narr.target.kind === "project" ? `<div class="field-row"><label for="narr-split">Files</label>
        <select id="narr-split"><option value="one" ${p.split === "one" ? "selected" : ""}>One file, a chapter per piece</option>
          <option value="each" ${p.split === "each" ? "selected" : ""}>One file per piece</option></select></div>` : ""}
      <div class="field-row"><label for="narr-format">Save as</label>
        <select id="narr-format"><option value="mp3" ${p.format === "mp3" ? "selected" : ""}>MP3</option>
          <option value="wav" ${p.format === "wav" ? "selected" : ""}>WAV (larger, no extra tool)</option></select></div>
      <div id="narr-tool"></div>
      <label class="check-row"><input type="checkbox" id="narr-titles" ${p.titles ? "checked" : ""}> Read each title first</label>
      <div class="narr-estimate" id="narr-estimate"></div>
    </div>
    <div class="modal-actions">
      ${helpLinkHtml("narration", "How narration works")}
      <span style="flex:1"></span>
      <button class="btn btn-ghost" id="narr-cancel">Cancel</button>
      <button class="btn btn-gold" id="narr-go">Make audio</button>
    </div>`;
  document.getElementById("narr-cancel").addEventListener("click", closeNarration);
  document.getElementById("narr-go").addEventListener("click", startNarration);
  body.querySelectorAll("input[name=narr-engine]").forEach((r) => r.addEventListener("change", () => {
    renderNarration();
  }));
  ["narr-titles", "narr-format", "narr-el-voice"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("change", () => { renderTool(); updateEstimate(); });
  });
  wireElevenLabsRow();
  renderTool();
  updateEstimate();
  if (p.engine === "elevenlabs" && o.elevenlabs.has_key && !narr.elVoices) loadElVoices();
}

function elevenLabsRowHtml(p) {
  if (!narr.opts.elevenlabs.has_key) {
    return `<div class="field-row"><label for="narr-el-key">ElevenLabs key</label>
        <div class="snip-use-row"><input type="password" id="narr-el-key" placeholder="Paste your API key" autocomplete="off">
        <button class="btn btn-small" type="button" id="narr-el-save">Save key</button></div></div>
      <p class="hint">Make one in your ElevenLabs account under Developers &gt; API keys. Minerva keeps it in Windows Credential Manager. ${helpLinkHtml("narration-cost", "Cost and privacy")}</p>`;
  }
  if (!narr.elVoices) return `<p class="muted">Getting your ElevenLabs voices...</p>`;
  const pick = narr.elVoices.some((v) => v.id === p.el_voice) ? p.el_voice : (narr.elVoices[0] || {}).id;
  return `<div class="field-row"><label for="narr-el-voice">Voice</label>
      <select id="narr-el-voice">${narr.elVoices.map((v) => `<option value="${esc(v.id)}" ${v.id === pick ? "selected" : ""}>${esc(v.name)}${v.labels && v.labels.accent ? ` (${esc(v.labels.accent.replace(/^./, (ch) => ch.toUpperCase()))})` : ""}</option>`).join("")}</select></div>
    <p class="hint"><a href="#" id="narr-el-forget">Forget the ElevenLabs key</a></p>`;
}

function wireElevenLabsRow() {
  const save = document.getElementById("narr-el-save");
  if (save) save.addEventListener("click", async () => {
    save.disabled = true;
    try {
      await postJson("/api/narration/key", { key: document.getElementById("narr-el-key").value });
      narr.opts.elevenlabs.has_key = true;
      toast("Key saved.");
      renderNarration();
    } catch (e) { toast(e.message, true); save.disabled = false; }
  });
  const forget = document.getElementById("narr-el-forget");
  if (forget) forget.addEventListener("click", async (ev) => {
    ev.preventDefault();
    if (!confirm("Forget the ElevenLabs key on this computer?")) return;
    try { await api("/api/narration/key", { method: "DELETE" }); } catch (e) { toast(e.message, true); return; }
    narr.opts.elevenlabs.has_key = false;
    narr.elVoices = null;
    narr.account = null;
    renderNarration();
  });
}

async function loadElVoices() {
  try {
    const r = await api("/api/narration/voices");
    narr.elVoices = r.voices;
    narr.account = r.account;
  } catch (e) {
    narr.elVoices = [];
    toast(e.message, true);
  }
  if (document.getElementById("narr-form")) renderNarration();
}

function renderTool() {
  const box = document.getElementById("narr-tool");
  if (!box) return;
  if (narrValue("narr-format", "mp3") !== "mp3") { box.innerHTML = ""; return; }
  mediaToolBox(box, narr.opts.tools, "MP3s", (tools) => { narr.opts.tools = tools; renderTool(); });
}

// The one-time FFmpeg download, offered wherever it's needed (narration
// MP3s, videos). onReady gets the new tool status.
function mediaToolBox(box, tools, what, onReady) {
  if (tools.ffmpeg) { box.innerHTML = ""; return; }
  box.innerHTML = tools.can_install
    ? `<div class="narr-tool">${what} need the free audio and video tool, a one-time download of about ${tools.download_mb} MB.
        <button class="btn btn-small" type="button" data-tool-get>Set it up</button> ${helpLinkHtml("media-tool", "What is it?")}
        <div class="progress" data-tool-progress hidden><div style="width:0%"></div></div></div>`
    : `<div class="narr-tool">${what} need FFmpeg, which isn't installed here. Install it and reopen this.</div>`;
  const get = box.querySelector("[data-tool-get]");
  if (!get) return;
  get.addEventListener("click", async () => {
    get.disabled = true;
    let j;
    try { j = await postJson("/api/media/tools", {}); } catch (e) { toast(e.message, true); get.disabled = false; return; }
    const poll = async () => {
      try { j = await api(`/api/jobs/${j.id}`); } catch (e) { return; }
      const bar = box.querySelector("[data-tool-progress]");
      if (j.status === "running") {
        if (bar) { bar.hidden = false; bar.firstElementChild.style.width = `${j.total ? Math.round((100 * j.done) / j.total) : 5}%`; }
        setTimeout(poll, 800);
        return;
      }
      if (j.status === "done") { toast("The audio and video tool is ready."); onReady(j.result); }
      else { if (j.status === "failed") toast(j.error, true); get.disabled = false; if (bar) bar.hidden = true; }
    };
    poll();
  });
}

async function updateEstimate() {
  const box = document.getElementById("narr-estimate");
  if (!box) return;
  const c = narrChoices();
  let e;
  try {
    e = await postJson("/api/narration/estimate", { kind: narr.target.kind, id: narr.target.id, which: narr.target.which, engine: c.engine, titles: c.titles });
  } catch (err) { box.innerHTML = `<span class="warn-text">${esc(err.message)}</span>`; return; }
  const length = `About ${e.minutes} minute${e.minutes === 1 ? "" : "s"} of audio from ${e.pieces > 1 ? `${e.pieces} pieces, ` : ""}${e.characters.toLocaleString()} characters.`;
  if (c.engine !== "elevenlabs") { box.innerHTML = `<p>${length}</p>`; return; }
  const acct = narr.account || e.account;
  const left = acct ? ` You have ${acct.left.toLocaleString()} left this month.` : "";
  const short = acct && acct.left < e.credits;
  narr.short = short ? { need: e.credits, left: acct.left } : null;
  box.innerHTML = `<p>${length}</p>
    <p class="${short ? "warn-text" : ""}">Uses about <strong>${e.credits.toLocaleString()} ElevenLabs credits</strong>.${left}${short ? " That isn't enough for all of it." : ""}</p>
    <p class="hint">${helpLinkHtml("narration-cost", "What this costs, and what ElevenLabs keeps")}</p>`;
}

async function startNarration() {
  const c = narrChoices();
  if (c.engine === "system" && !narr.opts.system.available) { toast("Choose ElevenLabs, or use a Windows computer.", true); return; }
  if (c.engine === "elevenlabs" && !narr.opts.elevenlabs.has_key) { toast("Save your ElevenLabs key first.", true); return; }
  if (c.format === "mp3" && !narr.opts.tools.ffmpeg) { toast("Set up the audio and video tool first, or save as WAV.", true); return; }
  if (c.engine === "elevenlabs" && narr.short
    && !confirm(`This needs about ${narr.short.need.toLocaleString()} credits and your account has ${narr.short.left.toLocaleString()} left, so ElevenLabs will probably stop partway. Try anyway?`)) return;
  let j;
  try {
    j = await postJson("/api/narration/start", { ...c, kind: narr.target.kind, id: narr.target.id, which: narr.target.which, title: narr.target.title });
  } catch (e) { toast(e.message, true); return; }
  narr.jobId = j.id;
  renderNarrationProgress(j);
  pollNarration();
}

function renderNarrationProgress(j) {
  const body = document.getElementById("narr-body");
  if (!body) return;
  const pct = j.total ? Math.round((100 * j.done) / j.total) : null;
  body.innerHTML = `
    <p>Narrating ${esc(j.label)}. You can close this and keep writing; it carries on.</p>
    <div class="progress ${pct == null ? "indeterminate" : ""}"><div style="width:${pct == null ? 100 : pct}%"></div></div>
    <p class="muted">${esc(j.message || "Starting...")}</p>
    <div class="modal-actions"><span style="flex:1"></span>
      <button class="btn btn-ghost" id="narr-stop">Stop</button>
      <button class="btn btn-gold" id="narr-hide">Close</button></div>`;
  document.getElementById("narr-hide").addEventListener("click", closeNarration);
  document.getElementById("narr-stop").addEventListener("click", async (ev) => {
    ev.target.disabled = true;
    try { await postJson(`/api/jobs/${narr.jobId}/cancel`); } catch (e) { toast(e.message, true); }
  });
}

async function pollNarration() {
  clearTimeout(narr.timer);
  if (!narr.jobId) return;
  let j;
  try { j = await api(`/api/jobs/${narr.jobId}`); } catch (e) { return; }
  if (j.status === "running") {
    renderNarrationProgress(j);
    narr.timer = setTimeout(pollNarration, 1000);
    return;
  }
  narr.jobId = null;
  const body = document.getElementById("narr-body");
  if (!body) {
    if (j.status === "done") toast(`Narration saved: ${j.result.files.map((f) => f.name).join(", ")}`);
    else if (j.status === "failed") toast(`Narration stopped: ${j.error}`, true);
    return;
  }
  if (j.status !== "done") {
    body.innerHTML = `<p class="${j.status === "failed" ? "warn-text" : ""}">${j.status === "failed" ? esc(j.error) : "Stopped."}</p>
      <div class="modal-actions"><span style="flex:1"></span><button class="btn" id="narr-again">Back</button></div>`;
    document.getElementById("narr-again").addEventListener("click", renderNarration);
    return;
  }
  const mins = (s) => (s < 90 ? `${s} seconds` : `${Math.round(s / 60)} minutes`);
  body.innerHTML = j.result.files.map((f) => exportResultHtml(f) + `<div class="hint">${mins(f.seconds)} long.
    <a href="#" data-narr-video="${esc(f.name)}">Make a video from it</a></div>`).join("") + `
    <div class="modal-actions"><span style="flex:1"></span><button class="btn btn-gold" id="narr-done">Done</button></div>`;
  wireExportResult(body);
  body.querySelectorAll("[data-narr-video]").forEach((a) => a.addEventListener("click", (ev) => {
    ev.preventDefault();
    const t = narr.target;
    closeNarration();
    openVideo({ ...t, narration: a.dataset.narrVideo });
  }));
  document.getElementById("narr-done").addEventListener("click", closeNarration);
}
