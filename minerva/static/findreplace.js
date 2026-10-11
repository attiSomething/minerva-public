// Find and replace. In the editor: Ctrl+F (or the Find button) opens a bar
// above the draft with next/previous, a match count, and replace one or
// all; replacements go through the browser's own undo (Ctrl+Z). Across the
// library: "Replace in drafts..." on an Inside-drafts search previews every
// matching line before and after, and saves each ticked entry as a new
// version with the old draft archived.
// Used by app.js (the entry page) and search.js.

const findState = { matches: [], i: -1 };

function findRegex(q, matchCase, wholeWord) {
  if (!q) return null;
  let p = q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  if (wholeWord) p = `(?<![\\p{L}\\p{N}_])${p}(?![\\p{L}\\p{N}_])`;
  return new RegExp(p, `gu${matchCase ? "" : "i"}`);
}

function findBarHtml() {
  return `<div class="find-bar" id="find-bar" role="search" hidden>
    <input type="text" id="find-q" placeholder="Find" aria-label="Find" autocomplete="off">
    <span class="muted find-count" id="find-count"></span>
    <button class="btn btn-small btn-ghost" id="find-prev" title="Previous (Shift+Enter)" aria-label="Previous match">&uarr;</button>
    <button class="btn btn-small btn-ghost" id="find-next" title="Next (Enter)" aria-label="Next match">&darr;</button>
    <input type="text" id="find-r" placeholder="Replace with" aria-label="Replace with" autocomplete="off">
    <button class="btn btn-small btn-ghost" id="find-one">Replace</button>
    <button class="btn btn-small btn-ghost" id="find-all">Replace all</button>
    <label class="filter-check"><input type="checkbox" id="find-case"> Match case</label>
    <label class="filter-check"><input type="checkbox" id="find-word"> Whole words</label>
    <button class="btn btn-small btn-ghost" id="find-close" aria-label="Close find">&times;</button>
  </div>`;
}

function wireFindBar(editor) {
  const bar = document.getElementById("find-bar");
  if (!bar || !editor) return;
  const q = document.getElementById("find-q");
  const r = document.getElementById("find-r");
  const count = document.getElementById("find-count");
  const opts = () => [document.getElementById("find-case").checked, document.getElementById("find-word").checked];

  const scan = () => {
    const rx = findRegex(q.value, ...opts());
    findState.matches = rx ? [...editor.value.matchAll(rx)].map((m) => [m.index, m.index + m[0].length]) : [];
    if (findState.i >= findState.matches.length) findState.i = findState.matches.length - 1;
    count.textContent = q.value ? (findState.matches.length ? `${findState.i + 1 > 0 ? findState.i + 1 : 0} of ${findState.matches.length}` : "No matches") : "";
  };
  const show = (i, keepFocus) => {
    if (!findState.matches.length) { scan(); return; }
    findState.i = (i + findState.matches.length) % findState.matches.length;
    const [a, b] = findState.matches[findState.i];
    editor.focus({ preventScroll: true });
    editor.setSelectionRange(a, b);
    if (typeof scrollToSelection === "function") scrollToSelection(editor, a);
    if (keepFocus) keepFocus.focus();
    count.textContent = `${findState.i + 1} of ${findState.matches.length}`;
  };
  const fromCursor = (focusEl = q) => {
    scan();
    const at = editor.selectionStart || 0;
    const i = findState.matches.findIndex(([a]) => a >= at);
    show(i < 0 ? 0 : i, focusEl);
  };
  const replaceRange = (a, b, text) => {
    editor.focus({ preventScroll: true });
    editor.setSelectionRange(a, b);
    // insertText keeps the change on the browser's undo stack
    if (!document.execCommand || !document.execCommand("insertText", false, text)) {
      editor.setRangeText(text, a, b, "end");
      editor.dispatchEvent(new Event("input", { bubbles: true }));
    }
  };

  q.addEventListener("input", () => fromCursor());
  ["find-case", "find-word"].forEach((id) => document.getElementById(id).addEventListener("change", () => fromCursor()));
  q.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); show(findState.i + (ev.shiftKey ? -1 : 1), q); }
  });
  r.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); document.getElementById("find-one").click(); } });
  document.getElementById("find-next").addEventListener("click", () => show(findState.i + 1, q));
  document.getElementById("find-prev").addEventListener("click", () => show(findState.i - 1, q));
  document.getElementById("find-one").addEventListener("click", () => {
    scan();
    if (!findState.matches.length) return;
    const cur = findState.matches[findState.i] || null;
    const selected = cur && editor.selectionStart === cur[0] && editor.selectionEnd === cur[1];
    if (!selected) { fromCursor(r); return; }
    replaceRange(cur[0], cur[1], r.value);
    const next = cur[0] + r.value.length;
    scan();
    const i = findState.matches.findIndex(([a]) => a >= next);
    if (findState.matches.length) show(i < 0 ? 0 : i, r); else count.textContent = "No matches";
  });
  document.getElementById("find-all").addEventListener("click", () => {
    const rx = findRegex(q.value, ...opts());
    if (!rx) return;
    const n = (editor.value.match(rx) || []).length;
    if (!n) { count.textContent = "No matches"; return; }
    replaceRange(0, editor.value.length, editor.value.replace(rx, () => r.value));
    editor.setSelectionRange(0, 0);
    scan();
    toast(`Replaced ${plural(n, "match", "matches")}. Ctrl+Z undoes it; nothing is saved until you save.`);
  });
  const close = () => { bar.hidden = true; editor.focus(); };
  document.getElementById("find-close").addEventListener("click", close);
  bar.addEventListener("keydown", (ev) => { if (ev.key === "Escape") { ev.stopPropagation(); close(); } });
  const open = (withReplace) => {
    bar.hidden = false;
    const sel = editor.value.slice(editor.selectionStart, editor.selectionEnd);
    if (sel && !sel.includes("\n") && sel.length < 100) q.value = sel;
    const target = withReplace && q.value ? r : q;
    fromCursor(target);
    target.focus();
    target.select();
  };
  editor.addEventListener("keydown", (ev) => {
    if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && (ev.key === "f" || ev.key === "h")) {
      ev.preventDefault();
      open(ev.key === "h");
    }
  });
  const btn = document.getElementById("find-open");
  if (btn) btn.addEventListener("click", () => open(false));
}

// ---- across the library -------------------------------------------------------

function closeLibraryReplace() {
  const el = document.getElementById("replace-dialog");
  if (el) el.remove();
}

function openLibraryReplace({ find = "", category = "", project = "", tag = "" } = {}) {
  closeLibraryReplace();
  const scope = [category && `category ${category}`, project && project !== "__none__" && `project ${project}`,
    project === "__none__" && "entries with no project", tag && `tag ${tag}`].filter(Boolean);
  const el = document.createElement("div");
  el.id = "replace-dialog";
  el.className = "modal-backdrop";
  el.innerHTML = `
    <div class="modal modal-wide" role="dialog" aria-modal="true" aria-labelledby="rp-h">
      <h2 id="rp-h">Replace in drafts</h2>
      <p class="hint">Changes the current draft of every entry you tick${scope.length ? `, within ${esc(scope.join(", "))}` : ""}. Each changed entry is saved as a new version, and its old draft goes to the entry's Archive, so nothing is lost.</p>
      <div class="rp-form">
        <div class="field-row"><label for="rp-find">Find</label><input type="text" id="rp-find" value="${esc(find)}" autocomplete="off"></div>
        <div class="field-row"><label for="rp-repl">Replace with</label><input type="text" id="rp-repl" autocomplete="off"></div>
      </div>
      <label class="filter-check"><input type="checkbox" id="rp-case"> Match case</label>
      <label class="filter-check"><input type="checkbox" id="rp-word"> Whole words</label>
      <button class="btn btn-small" id="rp-preview">Preview</button>
      <div id="rp-results"></div>
      <div class="modal-actions">
        <span class="muted" id="rp-summary"></span>
        <span style="flex:1"></span>
        <button class="btn btn-ghost" id="rp-cancel">Cancel</button>
        <button class="btn btn-gold" id="rp-apply" disabled>Replace</button>
      </div>
    </div>`;
  document.body.appendChild(el);
  el.addEventListener("keydown", (ev) => { if (ev.key === "Escape") closeLibraryReplace(); });
  document.getElementById("rp-cancel").addEventListener("click", closeLibraryReplace);
  const body = () => ({
    find: document.getElementById("rp-find").value, replace: document.getElementById("rp-repl").value,
    match_case: document.getElementById("rp-case").checked, whole_word: document.getElementById("rp-word").checked,
    category, project, tag,
  });
  let last = null;
  const preview = async () => {
    const b = body();
    let r;
    try { r = await postJson("/api/replace/preview", b); } catch (e) { toast(e.message, true); return; }
    last = { b, r, ticked: new Set(r.entries.map((x) => x.id)) };
    renderReplacePreview(last);
  };
  document.getElementById("rp-preview").addEventListener("click", preview);
  ["rp-find", "rp-repl"].forEach((id) => document.getElementById(id).addEventListener("keydown", (ev) => { if (ev.key === "Enter") preview(); }));
  ["rp-find", "rp-repl", "rp-case", "rp-word"].forEach((id) => document.getElementById(id).addEventListener("input", () => {
    // what's shown no longer matches what would be applied
    document.getElementById("rp-apply").disabled = true;
    document.getElementById("rp-summary").textContent = "Preview again to see the changes.";
  }));
  document.getElementById("rp-apply").addEventListener("click", async () => {
    if (!last) return;
    const ids = [...last.ticked];
    if (!confirm(`Replace in ${plural(ids.length, "entry", "entries")}? Each is saved as a new version with its old draft archived.`)) return;
    try {
      const r = await postJson("/api/replace/apply", Object.assign({}, last.b, { ids }));
      closeLibraryReplace();
      toast(`Replaced ${plural(r.replaced, "match", "matches")} in ${plural(r.entries.length, "entry", "entries")}.`);
      if (typeof renderTextSearch === "function" && state.searchMode === "text") renderTextSearch();
    } catch (e) { toast(e.message, true); }
  });
  document.getElementById(find ? "rp-repl" : "rp-find").focus();
  if (find) preview();
}

function renderReplacePreview(last) {
  const { r, ticked } = last;
  const box = document.getElementById("rp-results");
  const apply = document.getElementById("rp-apply");
  if (!r.entries.length) {
    box.innerHTML = `<div class="empty-state">No current drafts contain that.</div>`;
    apply.disabled = true;
    document.getElementById("rp-summary").textContent = "";
    return;
  }
  box.innerHTML = `<div class="import-rows rp-list">${r.entries.map((e) => `
    <div class="rp-entry ${ticked.has(e.id) ? "" : "import-skipped"}">
      <label class="rp-head"><input type="checkbox" data-rp="${e.id}" ${ticked.has(e.id) ? "checked" : ""}>
        <strong>${esc(e.title)}</strong> <span class="muted">${esc(e.category)} · ${plural(e.matches, "match", "matches")}</span></label>
      ${e.lines.map((l) => `<div class="rp-line"><span class="line-no">${l.line}</span>
        <div><div class="rp-before">${l.before.map((p) => p.hit ? `<del>${esc(p.text)}</del>` : esc(p.text)).join("")}</div>
        <div class="rp-after">${esc(l.after)}</div></div></div>`).join("")}
      ${e.matches > e.lines.reduce((s, l) => s + l.before.filter((p) => p.hit).length, 0) ? `<div class="hint">and more in this entry</div>` : ""}
    </div>`).join("")}</div>`;
  box.querySelectorAll("[data-rp]").forEach((c) => c.addEventListener("change", () => {
    const id = Number(c.dataset.rp);
    if (c.checked) ticked.add(id); else ticked.delete(id);
    renderReplacePreview(last);
  }));
  const n = r.entries.filter((e) => ticked.has(e.id));
  const matches = n.reduce((s, e) => s + e.matches, 0);
  apply.disabled = !n.length;
  apply.textContent = n.length ? `Replace in ${plural(n.length, "entry", "entries")}` : "Replace";
  document.getElementById("rp-summary").textContent = `${plural(matches, "match", "matches")} in ${plural(n.length, "entry", "entries")} ticked${r.truncated ? " (showing the first 1,000 entries)" : ""}`;
}
