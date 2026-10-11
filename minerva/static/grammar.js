// Grammar and style: LanguageTool suggestions for the draft in the editor,
// run on this computer. Each suggestion is accepted or skipped on its own.
// The button sits under the editor (app.js); setup and options live in
// Settings.

const gram = { matches: [], text: "", status: null, jobId: null };

HELP_TOPICS.grammar = { kind: "doc", name: GUIDE, anchor: "Grammar and style" };

async function grammarStatus(force) {
  if (!gram.status || force) gram.status = await api("/api/grammar");
  return gram.status;
}

// Verse gets the gentler check: a Poetry category, or short lines.
function looksLikePoem(e, text) {
  if (/poe|verse/i.test(e.top_folder || "")) return true;
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  return lines.length >= 4 && lines.reduce((n, l) => n + l.length, 0) / lines.length < 55;
}

function wireGrammar(e) {
  const btn = document.getElementById("grammar-open");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    let s;
    try { s = await grammarStatus(true); } catch (err) { toast(err.message, true); return; }
    if (!s.ready) { openGrammarSetup(() => runGrammar(e)); return; }
    runGrammar(e);
  });
}

async function runGrammar(e, keepPoem) {
  const editor = document.getElementById("editor");
  const box = document.getElementById("grammar-results");
  if (!editor || !box) return;
  const poemBox = document.getElementById("grammar-poem");
  const poem = keepPoem != null ? keepPoem : poemBox ? poemBox.checked : looksLikePoem(e, editor.value);
  box.innerHTML = `<div class="panel grammar-panel"><p class="muted">Checking${gram.status && gram.status.running ? "" : " (the first check starts LanguageTool, which takes a few seconds)"}...</p></div>`;
  let r;
  try {
    r = await postJson("/api/grammar/check", { text: editor.value, poem });
  } catch (err) {
    box.innerHTML = `<div class="panel grammar-panel"><div class="ai-banner">${esc(err.message)}</div></div>`;
    return;
  }
  gram.status = { ...(gram.status || {}), running: true };
  gram.text = editor.value;
  gram.matches = r.matches.map((m, i) => ({ ...m, id: i, done: false }));
  gram.poem = poem;
  gram.language = r.language;
  renderGrammar(e);
}

function grammarContext(text, m) {
  const start = Math.max(0, text.lastIndexOf("\n", m.offset - 1) + 1, m.offset - 60);
  let end = text.indexOf("\n", m.offset + m.length);
  if (end < 0 || end > m.offset + m.length + 60) end = Math.min(text.length, m.offset + m.length + 60);
  return `${start > 0 && text[start - 1] !== "\n" ? "…" : ""}${esc(text.slice(start, m.offset))}<mark>${esc(text.slice(m.offset, m.offset + m.length)) || "&nbsp;"}</mark>${esc(text.slice(m.offset + m.length, end))}`;
}

function renderGrammar(e) {
  const box = document.getElementById("grammar-results");
  if (!box) return;
  const left = gram.matches.filter((m) => !m.done);
  const editor = document.getElementById("editor");
  box.innerHTML = `
    <div class="panel grammar-panel">
      <div class="panel-head-row">
        <h3>Grammar and style</h3>
        <label class="grammar-poem-toggle"><input type="checkbox" id="grammar-poem" ${gram.poem ? "checked" : ""}> Check as a poem</label>
      </div>
      <p class="hint" style="margin-top:0">${left.length ? `${left.length} suggestion${left.length === 1 ? "" : "s"}` : "Nothing more to suggest"}${gram.language ? ` · ${esc(gram.language)}` : ""}. Checked on this computer by LanguageTool. Nothing changes until you pick a fix, and the draft still needs saving.</p>
      ${left.map((m) => `
        <div class="grammar-item grammar-${m.kind}" data-gm="${m.id}">
          <div class="grammar-context" data-gm-show="${m.id}" title="Show it in the editor">${grammarContext(editor.value, m)}</div>
          <div class="grammar-msg">${esc(m.message)}</div>
          <div class="grammar-actions">
            ${m.replacements.map((r, k) => `<button class="btn btn-small" data-gm-fix="${m.id}" data-k="${k}">${esc(r) || "(remove)"}</button>`).join("")}
            <button class="btn btn-small btn-ghost" data-gm-skip="${m.id}">Skip</button>
            ${m.kind === "spelling" ? `<button class="btn btn-small btn-ghost" data-gm-word="${m.id}" title="Never flag this word again">Add to my words</button>`
              : `<button class="btn btn-small btn-ghost" data-gm-rule="${m.id}" title="${esc(m.rule_name || m.rule)}">Stop flagging this</button>`}
          </div>
        </div>`).join("")}
      <div class="save-row">
        <button class="btn btn-small btn-ghost" id="grammar-again">Check again</button>
        <button class="btn btn-small btn-ghost" id="grammar-close">Close</button>
        ${helpLinkHtml("grammar", "About grammar checking")}
      </div>
    </div>`;
  const byId = (id) => gram.matches.find((m) => m.id === Number(id));
  document.getElementById("grammar-close").addEventListener("click", () => { box.innerHTML = ""; });
  document.getElementById("grammar-again").addEventListener("click", () => runGrammar(e));
  document.getElementById("grammar-poem").addEventListener("change", (ev) => runGrammar(e, ev.target.checked));
  box.querySelectorAll("[data-gm-show]").forEach((el) => el.addEventListener("click", () => {
    const m = byId(el.dataset.gmShow);
    editor.focus();
    editor.setSelectionRange(m.offset, m.offset + m.length);
  }));
  box.querySelectorAll("[data-gm-skip]").forEach((b) => b.addEventListener("click", () => { byId(b.dataset.gmSkip).done = true; renderGrammar(e); }));
  box.querySelectorAll("[data-gm-fix]").forEach((b) => b.addEventListener("click", () => {
    const m = byId(b.dataset.gmFix);
    if (editor.value.slice(m.offset, m.offset + m.length) !== m.text) {
      toast("The draft has changed here since the check. Check again.", true);
      return;
    }
    const fix = m.replacements[Number(b.dataset.k)];
    editor.value = editor.value.slice(0, m.offset) + fix + editor.value.slice(m.offset + m.length);
    editor.dispatchEvent(new Event("input"));
    const shift = fix.length - m.length;
    gram.matches.forEach((o) => {
      if (o.id !== m.id && !o.done && o.offset >= m.offset + m.length) o.offset += shift;
      // a suggestion that overlapped this one no longer fits
      else if (o.id !== m.id && !o.done && o.offset + o.length > m.offset && o.offset < m.offset + m.length) o.done = true;
    });
    m.done = true;
    renderGrammar(e);
  }));
  box.querySelectorAll("[data-gm-word]").forEach((b) => b.addEventListener("click", async () => {
    const m = byId(b.dataset.gmWord);
    try { await postJson("/api/grammar/ignore", { word: m.text }); } catch (err) { toast(err.message, true); return; }
    gram.matches.forEach((o) => { if (o.kind === "spelling" && o.text.toLowerCase() === m.text.toLowerCase()) o.done = true; });
    toast(`"${m.text}" won't be flagged again.`);
    renderGrammar(e);
  }));
  box.querySelectorAll("[data-gm-rule]").forEach((b) => b.addEventListener("click", async () => {
    const m = byId(b.dataset.gmRule);
    try { await postJson("/api/grammar/ignore", { rule: m.rule }); } catch (err) { toast(err.message, true); return; }
    gram.matches.forEach((o) => { if (o.rule === m.rule) o.done = true; });
    toast("Won't be flagged again. You can bring it back in Settings.");
    renderGrammar(e);
  }));
}

// ---- setting it up -------------------------------------------------------------

function closeGrammarSetup() {
  const el = document.getElementById("grammar-setup");
  if (el) el.remove();
}

async function openGrammarSetup(onReady) {
  closeGrammarSetup();
  let s;
  try { s = await grammarStatus(true); } catch (err) { toast(err.message, true); return; }
  const el = document.createElement("div");
  el.id = "grammar-setup";
  el.className = "modal-backdrop";
  el.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="gs-h">
      <h2 id="gs-h">Grammar and style checking</h2>
      <div id="gs-body">
        <p>Minerva uses <strong>LanguageTool</strong>, a free, open-source grammar and style checker, running on this computer. It needs no AI and no account, and your writing never leaves the computer.</p>
        ${s.can_install ? `<p>It's a one-time download of about <strong>${s.download_mb} MB</strong>${s.java ? "" : ", including the Java runtime it runs on"}, kept in Minerva's settings folder. It uses about 1 GB of memory while it's checking, and stops when Minerva closes.</p>`
          : `<p>Minerva can't download it on this computer. If you run a LanguageTool server, enter its address in Settings.</p>`}
        <div class="modal-actions">
          <span style="flex:1"></span>
          <button class="btn btn-ghost" id="gs-cancel">Not now</button>
          ${s.can_install ? `<button class="btn btn-gold" id="gs-go">Download and set up</button>` : ""}
        </div>
      </div>
    </div>`;
  document.body.appendChild(el);
  document.getElementById("gs-cancel").addEventListener("click", closeGrammarSetup);
  const go = document.getElementById("gs-go");
  if (go) go.addEventListener("click", async () => {
    let j;
    try { j = await postJson("/api/grammar/setup", {}); } catch (err) { toast(err.message, true); return; }
    gram.jobId = j.id;
    pollGrammarSetup(onReady);
  });
  if (s.jobs && s.jobs.length) { gram.jobId = s.jobs[0].id; pollGrammarSetup(onReady); }
}

async function pollGrammarSetup(onReady) {
  let j;
  try { j = await api(`/api/jobs/${gram.jobId}`); } catch (err) { return; }
  const body = document.getElementById("gs-body");
  if (j.status === "running") {
    if (body) {
      const pct = j.total ? Math.round((100 * j.done) / j.total) : null;
      body.innerHTML = `<p>Setting up LanguageTool. You can close this and keep writing.</p>
        <div class="progress ${pct == null ? "indeterminate" : ""}"><div style="width:${pct == null ? 100 : pct}%"></div></div>
        <p class="muted">${esc(j.message || "Starting...")}</p>
        <div class="modal-actions"><span style="flex:1"></span><button class="btn btn-ghost" id="gs-stop">Stop</button><button class="btn btn-gold" id="gs-hide">Close</button></div>`;
      document.getElementById("gs-hide").addEventListener("click", closeGrammarSetup);
      document.getElementById("gs-stop").addEventListener("click", () => postJson(`/api/jobs/${gram.jobId}/cancel`).catch(() => {}));
    }
    setTimeout(() => pollGrammarSetup(onReady), 1000);
    return;
  }
  gram.jobId = null;
  gram.status = null;
  if (j.status === "done") {
    closeGrammarSetup();
    toast("Grammar checking is ready.");
    if (onReady) onReady();
  } else if (body) {
    body.innerHTML = `<p class="${j.status === "failed" ? "warn-text" : ""}">${j.status === "failed" ? esc(j.error) : "Stopped."}</p>
      <div class="modal-actions"><span style="flex:1"></span><button class="btn" id="gs-close">Close</button></div>`;
    document.getElementById("gs-close").addEventListener("click", closeGrammarSetup);
  } else if (j.status === "failed") toast(`Grammar setup stopped: ${j.error}`, true);
}

// ---- Settings ------------------------------------------------------------------

async function renderGrammarSettings() {
  const box = document.getElementById("grammar-settings");
  if (!box) return;
  let s;
  try { s = await grammarStatus(true); } catch (err) { box.innerHTML = ""; return; }
  const g = s.settings;
  box.innerHTML = `
    <h2>Grammar and style ${helpLinkHtml("grammar", "How it works")}</h2>
    <p class="muted">Suggestions from LanguageTool, a free checker that runs on this computer: no AI, no account, nothing sent anywhere. Use <em>Grammar</em> under the editor.</p>
    <p>${s.own_server ? `Using your LanguageTool server at <code>${esc(s.own_server)}</code>.`
      : s.installed && s.java ? "Set up on this computer." : "Not set up yet."}</p>
    <div class="field-row"><label for="gs-language">Language</label>
      <select id="gs-language">${s.languages.map(([k, v]) => `<option value="${k}" ${k === g.language ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></div>
    <label class="switch-row"><input type="checkbox" id="gs-picky" ${g.picky ? "checked" : ""}> <span>Picky: more style suggestions (wordiness, repetition, formality)</span></label>
    ${g.words.length ? `<p class="hint">Your words: ${g.words.map((w) => esc(w)).join(", ")} <a href="#" id="gs-words-clear">Clear</a></p>` : ""}
    ${g.rules.length ? `<p class="hint">${g.rules.length} kind${g.rules.length === 1 ? "" : "s"} of suggestion turned off. <a href="#" id="gs-rules-clear">Turn them back on</a></p>` : ""}
    <details class="gs-advanced"><summary>Use your own LanguageTool server</summary>
      <div class="field-row"><label for="gs-server">Address</label><input type="text" id="gs-server" value="${esc(g.server)}" placeholder="http://localhost:8081"></div>
      <p class="hint">Leave empty to use the one Minerva sets up. Don't enter a public server for unpublished work: your text would go to it.</p>
    </details>
    <div class="save-row">
      <button class="btn" id="gs-save">Save</button>
      ${!s.installed && s.can_install && !s.own_server ? `<button class="btn btn-ghost" id="gs-install">Set it up (${s.download_mb} MB)</button>` : ""}
      ${s.installed ? `<button class="btn btn-ghost" id="gs-remove" title="Frees the disk space; you can set it up again any time">Remove LanguageTool</button>` : ""}
    </div>`;
  const save = async (extra) => {
    try {
      gram.status = null;
      await postJson("/api/grammar", { language: document.getElementById("gs-language").value, picky: document.getElementById("gs-picky").checked,
        server: document.getElementById("gs-server").value, ...(extra || {}) });
      toast("Saved.");
      renderGrammarSettings();
    } catch (err) { toast(err.message, true); }
  };
  document.getElementById("gs-save").addEventListener("click", () => save());
  const clearWords = document.getElementById("gs-words-clear");
  if (clearWords) clearWords.addEventListener("click", (ev) => { ev.preventDefault(); save({ words: [] }); });
  const clearRules = document.getElementById("gs-rules-clear");
  if (clearRules) clearRules.addEventListener("click", (ev) => { ev.preventDefault(); save({ rules: [] }); });
  const install = document.getElementById("gs-install");
  if (install) install.addEventListener("click", () => openGrammarSetup(renderGrammarSettings));
  const remove = document.getElementById("gs-remove");
  if (remove) remove.addEventListener("click", async () => {
    if (!confirm("Remove LanguageTool from this computer? You can set it up again any time.")) return;
    try { await postJson("/api/grammar/remove", {}); } catch (err) { toast(err.message, true); return; }
    gram.status = null;
    renderGrammarSettings();
  });
}
