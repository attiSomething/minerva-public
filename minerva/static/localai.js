// One-click free, private AI: checks this computer, installs Ollama when it's
// missing (Windows), downloads a model sized to the machine, reads a test
// page, then turns the AI features on. Anything with data-localai opens it.
// Used by onboarding.js (setup and Settings) and help.js (the AI-off panel).

const localAi = { check: null, model: "", features: ["scanning", "organizing"], jobId: null, timer: null, onDone: null };

function localAiCardHtml() {
  return `<div class="localai-card">
    <div>
      <strong>Free and private</strong>
      <span class="muted">Let Minerva set up a model that runs on this computer. Nothing you write leaves it.</span>
    </div>
    <button class="btn btn-ghost" type="button" data-localai>Set up free local AI</button>
  </div>`;
}

document.addEventListener("click", (ev) => {
  const a = ev.target.closest && ev.target.closest("[data-localai]");
  if (!a) return;
  ev.preventDefault();
  const modal = a.closest(".modal-backdrop");
  if (modal && modal.id !== "localai") modal.remove();
  openLocalAi(localAiRefreshPage);
});

// After setup, redraw whatever showed the AI settings.
async function localAiRefreshPage() {
  if (document.querySelector(".wizard") && typeof renderOnboarding === "function") {
    try { onboarding.ai = await api("/api/settings/ai"); } catch (e) { return; }
    renderOnboarding();
  } else if (state.view === "settings") {
    renderSettings();
  }
}

function closeLocalAi() {
  clearTimeout(localAi.timer);
  const el = document.getElementById("localai");
  if (el) el.remove();
  document.removeEventListener("keydown", localAiKeys);
}

function localAiKeys(ev) {
  if (ev.key === "Escape" && !localAi.jobId) closeLocalAi();
}

async function openLocalAi(onDone) {
  closeLocalAi();
  localAi.onDone = onDone || null;
  const el = document.createElement("div");
  el.id = "localai";
  el.className = "modal-backdrop";
  el.innerHTML = `
    <div class="modal modal-wide" role="dialog" aria-modal="true" aria-labelledby="la-h">
      <h2 id="la-h">Free and private AI</h2>
      <div id="la-body"><div class="empty-state">Looking at this computer...</div></div>
    </div>`;
  document.body.appendChild(el);
  document.addEventListener("keydown", localAiKeys);
  await refreshLocalAi();
}

async function refreshLocalAi() {
  let c;
  try { c = await api("/api/localai/check"); } catch (e) { closeLocalAi(); toast(e.message, true); return; }
  localAi.check = c;
  if (!c.recommendation.choices.some((m) => m.name === localAi.model)) localAi.model = c.recommendation.model;
  if (c.jobs && c.jobs.length) {
    localAi.jobId = c.jobs[0].id;
    renderLocalAiProgress(c.jobs[0]);
    pollLocalAi();
    return;
  }
  renderLocalAiChoice();
}

function localAiMachineText(c) {
  const bits = [];
  if (c.memory_gb) bits.push(`${c.memory_gb} GB of memory`);
  bits.push(c.gpu ? `${esc(c.gpu.name)} graphics card (${c.gpu.memory_gb} GB)` : "no NVIDIA graphics card, so the model runs on the processor");
  if (c.disk_free_gb != null) bits.push(`${c.disk_free_gb} GB of free disk space`);
  return `This computer has ${bits.join(", ")}.`;
}

function renderLocalAiChoice() {
  const body = document.getElementById("la-body");
  if (!body) return;
  const c = localAi.check;
  const rec = c.recommendation;
  const o = c.ollama;
  const needsManual = !o.installed && !c.can_install;
  const chosen = rec.choices.find((m) => m.name === localAi.model);
  const download = (chosen.downloaded ? 0 : chosen.size_gb) + (o.installed ? 0 : 1);
  const steps = [
    o.installed ? (o.running ? "" : "start Ollama") : "install Ollama, a free program that runs AI models (about a 1 GB download)",
    chosen.downloaded ? "" : `download ${chosen.label} (${chosen.size_gb} GB)`,
    "read a typed test page with it, so you can see it work",
    "turn on the AI features you tick below",
  ].filter(Boolean);
  body.innerHTML = `
    <p class="hint">${localAiMachineText(c)} ${o.running ? `Ollama is running${o.models.length ? ` with ${plural(o.models.length, "model", "models")} downloaded` : ""}.` : o.installed ? "Ollama is installed but not running." : "Ollama isn't installed yet."}</p>
    ${rec.warnings.map((w) => `<p class="hint warn">${esc(w)}</p>`).join("")}
    <div class="localai-models">
      ${rec.choices.map((m) => `
        <label class="localai-model ${m.name === localAi.model ? "selected" : ""} ${m.room ? "" : "disabled"}">
          <input type="radio" name="la-model" value="${esc(m.name)}" ${m.name === localAi.model ? "checked" : ""} ${m.room ? "" : "disabled"}>
          <span>
            <strong>${esc(m.label)}</strong>${m.name === rec.model ? ' <span class="badge badge-final">suggested</span>' : ""}${m.downloaded ? ' <span class="badge badge-dim">downloaded</span>' : ""}
            <span class="muted"> · ${m.size_gb} GB</span><br>
            <span class="muted">${esc(m.about)}</span><br>
            <span class="${m.fits ? "muted" : "warn-text"}">${esc(m.fits ? m.speed : "Too big for this computer's memory: it would crawl, if it runs at all.")}</span>
          </span>
        </label>`).join("")}
    </div>
    <div class="localai-features">
      <span>Use it for:</span>
      ${["scanning", "organizing"].map((f) => `<label><input type="checkbox" value="${f}" ${localAi.features.includes(f) ? "checked" : ""}> ${esc(FEATURE_COPY[f].title)}</label>`).join("")}
    </div>
    ${needsManual
      ? `<p>Minerva installs Ollama for you on Windows. Here, install it from <a href="${esc(c.download_page)}" target="_blank" rel="noopener">ollama.com</a>, open it, then check again.</p>`
      : `<p>Minerva will ${steps.join(", then ")}.${download ? ` That's about <strong>${download.toFixed(1)} GB</strong> to download${o.installed ? "" : ", and Windows may ask you to allow the installer"}.` : ""}</p>`}
    <p class="hint">Local models are good with typed pages and neat print, and often wrong on cursive. ${helpLinkHtml("ai-local", "Running AI on your computer")}</p>
    <div class="modal-actions">
      <span style="flex:1"></span>
      <button class="btn btn-ghost" id="la-cancel">Not now</button>
      ${needsManual
        ? `<button class="btn btn-gold" id="la-recheck">Check again</button>`
        : `<button class="btn btn-gold" id="la-go">${download ? `Download and set up` : "Set up"}</button>`}
    </div>`;
  body.querySelectorAll('input[name="la-model"]').forEach((r) => r.addEventListener("change", () => {
    localAi.model = r.value;
    renderLocalAiChoice();
  }));
  body.querySelectorAll(".localai-features input").forEach((cb) => cb.addEventListener("change", () => {
    localAi.features = [...body.querySelectorAll(".localai-features input:checked")].map((x) => x.value);
    const go = document.getElementById("la-go");
    if (go) go.disabled = !localAi.features.length;
  }));
  document.getElementById("la-cancel").addEventListener("click", closeLocalAi);
  const recheck = document.getElementById("la-recheck");
  if (recheck) recheck.addEventListener("click", () => {
    body.innerHTML = `<div class="empty-state">Looking again...</div>`;
    refreshLocalAi();
  });
  const go = document.getElementById("la-go");
  if (go) {
    go.disabled = !localAi.features.length;
    go.addEventListener("click", startLocalAi);
  }
}

async function startLocalAi() {
  let j;
  try {
    j = await postJson("/api/localai/setup", { model: localAi.model, features: localAi.features });
  } catch (e) {
    toast(e.message, true);
    return;
  }
  localAi.jobId = j.id;
  renderLocalAiProgress(j);
  pollLocalAi();
}

function renderLocalAiProgress(j) {
  const body = document.getElementById("la-body");
  if (!body) return;
  const pct = j.total ? Math.round((100 * j.done) / j.total) : null;
  body.innerHTML = `
    <p>Setting up ${esc(j.label)}. You can close this and keep writing; it carries on in the background.</p>
    <div class="progress ${pct == null ? "indeterminate" : ""}"><div style="width:${pct == null ? 100 : pct}%"></div></div>
    <p class="muted" id="la-msg">${esc(j.message || "Starting...")}</p>
    <div class="modal-actions">
      <span style="flex:1"></span>
      <button class="btn btn-ghost" id="la-stop">Stop</button>
      <button class="btn btn-gold" id="la-hide">Close</button>
    </div>`;
  document.getElementById("la-hide").addEventListener("click", closeLocalAi);
  document.getElementById("la-stop").addEventListener("click", async (ev) => {
    ev.target.disabled = true;
    try { await postJson(`/api/jobs/${localAi.jobId}/cancel`); } catch (e) { toast(e.message, true); }
  });
}

async function pollLocalAi() {
  clearTimeout(localAi.timer);
  if (!localAi.jobId) return;
  let j;
  try { j = await api(`/api/jobs/${localAi.jobId}`); } catch (e) { return; }
  if (j.status === "running") {
    renderLocalAiProgress(j);
    localAi.timer = setTimeout(pollLocalAi, 1000);
    return;
  }
  localAi.jobId = null;
  if (!document.getElementById("localai")) {
    if (j.status === "done" && j.result.ok) toast(`Local AI is ready: ${j.result.model} is turned on.`);
    else if (j.status === "failed") toast(`Local AI setup stopped: ${j.error}`, true);
    if (localAi.onDone) localAi.onDone();
    return;
  }
  renderLocalAiResult(j);
}

function renderLocalAiResult(j) {
  const body = document.getElementById("la-body");
  const r = j.result || {};
  if (j.status === "done" && r.ok) {
    body.innerHTML = `
      <p><strong>It works.</strong> ${esc(r.model)} read the test page in ${r.seconds} seconds (the first page is the slowest while the model loads). ${r.features.map((f) => esc(FEATURE_COPY[f].title)).join(" and ")} ${r.features.length > 1 ? "are" : "is"} now turned on with it.</p>
      <pre class="localai-test">${esc(r.text)}</pre>
      <p class="hint">You can switch to an AI service any time in Settings. ${helpLinkHtml("ai-local", "Running AI on your computer")}</p>
      <div class="modal-actions"><span style="flex:1"></span><button class="btn btn-gold" id="la-done">Done</button></div>`;
  } else if (j.status === "done") {
    body.innerHTML = `
      <p><strong>The model is downloaded, but it misread the test page.</strong> Here is what it read:</p>
      <pre class="localai-test">${esc(r.text || "(nothing)")}</pre>
      <p>A bigger model usually does better, if this computer has room for it. You can also use this one anyway, and proofread closely.</p>
      <div class="modal-actions">
        <span style="flex:1"></span>
        <button class="btn btn-ghost" id="la-back">Pick another model</button>
        <button class="btn btn-gold" id="la-anyway">Use it anyway</button>
      </div>`;
    document.getElementById("la-back").addEventListener("click", () => refreshLocalAi());
    document.getElementById("la-anyway").addEventListener("click", async () => {
      try {
        await postJson("/api/localai/use", { model: r.model, features: localAi.features });
      } catch (e) { toast(e.message, true); return; }
      closeLocalAi();
      toast(`${r.model} is turned on.`);
      if (localAi.onDone) localAi.onDone();
    });
    return;
  } else {
    body.innerHTML = `
      <p><strong>${j.status === "stopped" ? "Stopped." : "Setup didn't finish."}</strong> ${esc(j.status === "stopped" ? "" : j.error || "")}</p>
      <p class="hint">${helpLinkHtml("ai-local", "Running AI on your computer")} has the steps to do it by hand.</p>
      <div class="modal-actions">
        <span style="flex:1"></span>
        <button class="btn btn-ghost" id="la-done">Close</button>
        <button class="btn btn-gold" id="la-again">Try again</button>
      </div>`;
    document.getElementById("la-again").addEventListener("click", () => refreshLocalAi());
  }
  document.getElementById("la-done").addEventListener("click", () => {
    closeLocalAi();
    if (localAi.onDone) localAi.onDone();
  });
}
