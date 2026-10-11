// Snippets: cover letters, bios and acknowledgments kept for reuse, with
// placeholders like {venue} filled in. The manager opens from Submissions;
// the submission dialog can add a filled-in snippet to its notes or copy it
// for a submission form. Used by submissions.js.

const snipState = { data: null, current: null, onClose: null };

async function loadSnippets(force) {
  if (!snipState.data || force) snipState.data = await api("/api/snippets");
  return snipState.data;
}

function closeSnippets() {
  const el = document.getElementById("snippets-dialog");
  if (el) el.remove();
  document.removeEventListener("keydown", snippetKeys);
  if (snipState.onClose) { const f = snipState.onClose; snipState.onClose = null; f(); }
}

function snippetKeys(ev) {
  if (ev.key === "Escape") closeSnippets();
}

async function openSnippets(onClose) {
  let d;
  try { d = await loadSnippets(true); } catch (e) { toast(e.message, true); return; }
  closeSnippets();
  snipState.onClose = onClose || null;
  snipState.current = d.snippets.length ? d.snippets[0].id : null;
  const el = document.createElement("div");
  el.id = "snippets-dialog";
  el.className = "modal-backdrop";
  el.innerHTML = `
    <div class="modal modal-wide" role="dialog" aria-modal="true" aria-labelledby="snip-h">
      <h2 id="snip-h">Snippets</h2>
      <p class="hint">Cover letters, bios and acknowledgments you reuse. Placeholders in curly brackets are filled in when you use one; your name and email come from <em>Settings &gt; Manuscript details</em>.</p>
      <div class="snip-layout">
        <div class="snip-list" id="snip-list"></div>
        <div class="snip-edit" id="snip-edit"></div>
      </div>
      <div class="modal-actions"><span style="flex:1"></span><button class="btn btn-gold" id="snip-done">Done</button></div>
    </div>`;
  document.body.appendChild(el);
  document.addEventListener("keydown", snippetKeys);
  document.getElementById("snip-done").addEventListener("click", closeSnippets);
  renderSnippets();
}

function renderSnippets() {
  const d = snipState.data;
  const list = document.getElementById("snip-list");
  if (!list) return;
  list.innerHTML = `
    ${d.snippets.map((s) => `<button class="snip-item ${s.id === snipState.current ? "active" : ""}" data-snip="${esc(s.id)}">
      ${esc(s.name)}<span class="muted">${esc(d.kinds[s.kind] || "")}</span></button>`).join("")}
    <button class="btn btn-ghost btn-small" id="snip-new">New snippet</button>
    ${d.snippets.length ? "" : `<button class="btn btn-ghost btn-small" id="snip-starters">Start from a sample cover letter and bio</button>`}`;
  list.querySelectorAll("[data-snip]").forEach((b) => b.addEventListener("click", () => {
    snipState.current = b.dataset.snip;
    renderSnippets();
  }));
  document.getElementById("snip-new").addEventListener("click", () => { snipState.current = "new"; renderSnippets(); });
  const starters = document.getElementById("snip-starters");
  if (starters) starters.addEventListener("click", async () => {
    try { snipState.data = await postJson("/api/snippets", { starters: true }); } catch (e) { toast(e.message, true); return; }
    snipState.current = snipState.data.snippets[0] && snipState.data.snippets[0].id;
    renderSnippets();
  });
  renderSnippetEditor();
}

function renderSnippetEditor() {
  const d = snipState.data;
  const box = document.getElementById("snip-edit");
  const s = snipState.current === "new" ? { id: "", name: "", kind: "cover", body: "" }
    : d.snippets.find((x) => x.id === snipState.current);
  if (!s) {
    box.innerHTML = `<div class="empty-state">No snippets yet. Make one for the cover letter you send most, and a short bio.</div>`;
    return;
  }
  box.innerHTML = `
    <div class="field-row"><label for="snip-name">Name</label><input type="text" id="snip-name" value="${esc(s.name)}" maxlength="80" placeholder="e.g. Cover letter, poetry"></div>
    <div class="field-row"><label for="snip-kind">Kind</label>
      <select id="snip-kind">${Object.entries(d.kinds).map(([k, v]) => `<option value="${k}" ${k === s.kind ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></div>
    <textarea id="snip-body" rows="11">${esc(s.body)}</textarea>
    <div class="snip-placeholders">Insert: ${Object.entries(d.placeholders).map(([k, v]) =>
      `<button class="tag-chip" type="button" data-ph="${k}" title="${esc(v)}">{${k}}</button>`).join("")}</div>
    <div class="snip-actions">
      ${s.id ? `<button class="btn btn-ghost btn-small sub-delete" id="snip-delete">Delete</button>` : ""}
      <span style="flex:1"></span>
      <button class="btn" id="snip-save">${s.id ? "Save" : "Add snippet"}</button>
    </div>`;
  const body = document.getElementById("snip-body");
  box.querySelectorAll("[data-ph]").forEach((b) => b.addEventListener("click", () => {
    const tag = `{${b.dataset.ph}}`;
    const at = body.selectionStart ?? body.value.length;
    body.value = body.value.slice(0, at) + tag + body.value.slice(body.selectionEnd ?? at);
    body.focus();
    body.selectionStart = body.selectionEnd = at + tag.length;
  }));
  document.getElementById("snip-save").addEventListener("click", async () => {
    try {
      snipState.data = await postJson("/api/snippets", {
        id: s.id, name: document.getElementById("snip-name").value, kind: document.getElementById("snip-kind").value, body: body.value,
      });
    } catch (e) { toast(e.message, true); return; }
    if (!s.id) snipState.current = snipState.data.snippets[snipState.data.snippets.length - 1].id;
    toast("Saved.");
    renderSnippets();
  });
  const del = document.getElementById("snip-delete");
  if (del) del.addEventListener("click", async () => {
    if (!confirm(`Delete the snippet "${s.name}"?`)) return;
    try { snipState.data = await api(`/api/snippets/${encodeURIComponent(s.id)}`, { method: "DELETE" }); } catch (e) { toast(e.message, true); return; }
    snipState.current = snipState.data.snippets[0] ? snipState.data.snippets[0].id : null;
    renderSnippets();
  });
  if (!s.id) document.getElementById("snip-name").focus();
}

// ---- in the submission dialog ------------------------------------------------

function snippetRowHtml(list) {
  return `<div class="field-row wide snip-use">
    <label for="sub-snippet">Snippet</label>
    <div class="snip-use-row">
      <select id="sub-snippet">${list.length ? list.map((s) => `<option value="${esc(s.id)}">${esc(s.name)}</option>`).join("") : `<option value="">No snippets yet</option>`}</select>
      <button class="btn btn-ghost btn-small" type="button" id="sub-snippet-copy" ${list.length ? "" : "disabled"} title="Filled in with this venue and piece, for pasting into a submission form">Copy</button>
      <button class="btn btn-ghost btn-small" type="button" id="sub-snippet-notes" ${list.length ? "" : "disabled"}>Add to notes</button>
      <a href="#" id="sub-snippet-manage">${list.length ? "Edit snippets" : "Make one"}</a>
    </div>
  </div>`;
}

function wireSnippetRow(getContext, reopen) {
  const sel = document.getElementById("sub-snippet");
  if (!sel) return;
  const filled = async () => {
    const ctx = getContext();
    const r = await postJson(`/api/snippets/${encodeURIComponent(sel.value)}/fill`, ctx);
    return r.text;
  };
  document.getElementById("sub-snippet-copy").addEventListener("click", async () => {
    try {
      const text = await filled();
      await navigator.clipboard.writeText(text);
      toast(/\{\w+\}/.test(text) ? "Copied. Some placeholders had nothing to fill them; check the brackets." : "Copied, filled in.");
    } catch (e) { toast(e.message || "Couldn't copy.", true); }
  });
  document.getElementById("sub-snippet-notes").addEventListener("click", async () => {
    try {
      const text = await filled();
      const notes = document.getElementById("sub-notes");
      notes.value = notes.value.trim() ? `${notes.value.trim()}\n\n${text}` : text;
      notes.rows = Math.min(14, Math.max(notes.rows, text.split("\n").length + 2));
    } catch (e) { toast(e.message, true); }
  });
  document.getElementById("sub-snippet-manage").addEventListener("click", (ev) => {
    ev.preventDefault();
    openSnippets(reopen);
  });
}
