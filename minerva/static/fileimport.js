// Import files: bring drafts in from Word, Google Docs (downloaded as
// .docx), OpenDocument, Rich Text, Markdown, web pages, text and PDF files,
// one at a time or a whole folder. Every file is previewed first: its
// title, category, length, anything that couldn't be kept, and whether an
// entry with that title already exists. The files are only read.
// Used by app.js (Entries) and newentry.js.

const IMPORT_EXTS = [".docx", ".odt", ".rtf", ".md", ".markdown", ".txt", ".text", ".html", ".htm", ".pdf", ".enex", ".zip", ".json"];
const fileImportState = { rows: [] };

function closeFileImport() {
  const el = document.getElementById("file-import-dialog");
  if (el) el.remove();
  document.removeEventListener("keydown", fileImportKeys);
}

function fileImportKeys(ev) {
  if (ev.key === "Escape") closeFileImport();
}

async function openFileImport({ category = "", project = "" } = {}) {
  if (state.projectsCache.length === 0) await loadProjects();
  await loadCategories();
  closeFileImport();
  fileImportState.rows = [];
  const cat = category || defaultCategory();
  const el = document.createElement("div");
  el.id = "file-import-dialog";
  el.className = "modal-backdrop";
  el.innerHTML = `
    <div class="modal modal-wide" role="dialog" aria-modal="true" aria-labelledby="fi-h">
      <h2 id="fi-h">Import files</h2>
      <p class="hint">Bring in drafts from Word, Google Docs (File &gt; Download &gt; Microsoft Word), OpenDocument, Rich Text, Markdown, web pages, text files and PDFs, or a whole export from Evernote (.enex), Google Keep (the Takeout .zip) or Notion (the Markdown .zip). See <a href="#" data-help="notesapps">Bringing notes from other apps</a>. Line breaks are kept and formatting is dropped. You'll see every file before anything is created, and the files themselves aren't changed. ${helpLinkHtml("intake", "Bringing in old drafts")}</p>
      <div class="fi-pick">
        <label class="btn btn-ghost">Choose files<input type="file" id="fi-files" multiple accept="${IMPORT_EXTS.join(",")}" hidden></label>
        <label class="btn btn-ghost">Choose a folder<input type="file" id="fi-folder" webkitdirectory hidden></label>
        <span class="muted" id="fi-status"></span>
      </div>
      <div class="ne-grid fi-defaults">
        <div class="field-row"><label for="fi-category">Category for all</label>
          <select id="fi-category" data-category-menu>${categoryOptionsHtml(cat, { withNew: true })}</select></div>
        <div class="field-row"><label for="fi-project">Project</label>
          <select id="fi-project"><option value="">No project</option>
            ${state.projectsCache.map((p) => `<option value="${esc(p.tag)}" ${p.tag === project ? "selected" : ""}>${esc(p.name)}</option>`).join("")}
          </select></div>
      </div>
      <div id="fi-rows"></div>
      <div class="modal-actions">
        <span class="muted" id="fi-summary"></span>
        <span style="flex:1"></span>
        <button class="btn btn-ghost" id="fi-cancel">Cancel</button>
        <button class="btn btn-gold" id="fi-go" disabled>Import</button>
      </div>
    </div>`;
  document.body.appendChild(el);
  document.addEventListener("keydown", fileImportKeys);
  document.getElementById("fi-cancel").addEventListener("click", closeFileImport);
  const catSel = document.getElementById("fi-category");
  wireCategorySelect(catSel, (v) => {
    fileImportState.rows.forEach((r) => { r.category = v; });
    renderFileImportRows();
  });
  const pick = (input) => input.addEventListener("change", () => readImportFiles([...input.files]));
  pick(document.getElementById("fi-files"));
  pick(document.getElementById("fi-folder"));
  document.getElementById("fi-go").addEventListener("click", runFileImport);
}

async function readImportFiles(files) {
  const path = (f) => (f.webkitRelativePath || f.name);
  // an unzipped Google Takeout has each Keep note as .json and .html; read the .json
  const keepJson = new Set(files.filter((f) => /\.json$/i.test(f.name)).map((f) => path(f).replace(/\.json$/i, "")));
  const wanted = files.filter((f) => IMPORT_EXTS.some((x) => f.name.toLowerCase().endsWith(x)) && !f.name.startsWith(".")
    && !(/\.html?$/i.test(f.name) && keepJson.has(path(f).replace(/\.html?$/i, ""))));
  const status = document.getElementById("fi-status");
  if (!wanted.length) {
    status.textContent = files.length ? "None of those are files Minerva can read." : "";
    return;
  }
  const category = document.getElementById("fi-category").value;
  rememberCategory(category);
  const seen = new Set(fileImportState.rows.map((r) => r.key));
  for (let i = 0; i < wanted.length; i += 20) {
    status.textContent = `Reading ${Math.min(i + 20, wanted.length)} of ${wanted.length}...`;
    const form = new FormData();
    wanted.slice(i, i + 20).forEach((f) => form.append("files", f, f.webkitRelativePath || f.name));
    let out;
    try {
      out = await api("/api/import/files/preview", { method: "POST", body: form });
    } catch (e) {
      status.textContent = "";
      toast(e.message, true);
      return;
    }
    out.forEach((item) => {
      const key = item.name;
      if (seen.has(key)) return;
      seen.add(key);
      const nb = item.fields && item.fields.notebook;
      const match = nb && (state.categories || []).find((c) => c.toLowerCase() === String(nb).toLowerCase());
      // a notebook named like a category files the note there instead of tagging it
      if (match && Array.isArray(item.fields.tags)) item.fields.tags = item.fields.tags.filter((t) => t.toLowerCase() !== match.toLowerCase());
      fileImportState.rows.push(Object.assign(item, { key, include: !item.error && !item.existing_id, category: match || category }));
    });
  }
  const skipped = files.length - wanted.length;
  status.textContent = skipped ? `${plural(skipped, "file", "files")} skipped: not a kind Minerva reads.` : "";
  renderFileImportRows();
}

function renderFileImportRows() {
  const box = document.getElementById("fi-rows");
  if (!box) return;
  const rows = fileImportState.rows;
  box.innerHTML = rows.length ? `
    <div class="import-rows"><table class="entry-table import-table">
      <thead><tr><th><input type="checkbox" id="fi-all" aria-label="Import all" ${rows.every((r) => r.include || r.error) ? "checked" : ""}></th>
        <th>Title</th><th>Category</th><th>Words</th><th>Notes</th></tr></thead>
      <tbody>${rows.map((r, i) => r.error ? `
        <tr class="import-problem"><td></td><td><span class="muted">${esc(r.name)}</span></td><td></td><td></td>
          <td><span class="import-state">Can't import</span><div class="hint">${esc(r.error)}</div></td></tr>` : `
        <tr data-fi="${i}" class="${r.include ? "" : "import-skipped"}">
          <td><input type="checkbox" data-fi-include ${r.include ? "checked" : ""} aria-label="Import ${esc(r.title)}"></td>
          <td><input type="text" data-fi-title value="${esc(r.title)}" maxlength="120" aria-label="Title">
            <div class="hint">${esc(r.name)}</div></td>
          <td><select data-fi-cat aria-label="Category">${categoryOptionsHtml(r.category)}</select></td>
          <td>${r.words.toLocaleString()}</td>
          <td>${r.existing_id ? `<div class="fi-warn">An entry with this title already exists, so this file is left unticked. Tick it to import it anyway (it gets a number).</div>` : ""}
            ${r.notes.length ? `<div class="hint">${esc(r.notes.join("; "))}</div>` : ""}
            ${r.fields && Array.isArray(r.fields.tags) && r.fields.tags.length ? `<div class="hint">Tags: ${esc(r.fields.tags.join(", "))}</div>` : ""}
            ${r.fields && r.fields.modified ? `<div class="hint">Dated ${esc(new Date(r.fields.modified * 1000).toLocaleDateString())}</div>` : ""}
            ${!r.words ? `<div class="fi-warn">No text found.</div>` : ""}</td>
        </tr>`).join("")}</tbody></table></div>` : "";
  box.querySelectorAll("tr[data-fi]").forEach((tr) => {
    const r = rows[Number(tr.dataset.fi)];
    tr.querySelector("[data-fi-include]").addEventListener("change", (ev) => { r.include = ev.target.checked; renderFileImportRows(); });
    tr.querySelector("[data-fi-title]").addEventListener("input", (ev) => { r.title = ev.target.value; });
    tr.querySelector("[data-fi-cat]").addEventListener("change", (ev) => { r.category = ev.target.value; });
  });
  const all = document.getElementById("fi-all");
  if (all) all.addEventListener("change", () => { rows.forEach((r) => { if (!r.error) r.include = all.checked; }); renderFileImportRows(); });
  const n = rows.filter((r) => r.include && !r.error).length;
  const bad = rows.filter((r) => r.error).length;
  const go = document.getElementById("fi-go");
  go.disabled = !n;
  go.textContent = n ? `Import ${plural(n, "entry", "entries")}` : "Import";
  document.getElementById("fi-summary").textContent = rows.length
    ? `${plural(rows.length, "file", "files")}${bad ? `, ${bad} can't be imported` : ""}` : "";
}

async function runFileImport() {
  const go = document.getElementById("fi-go");
  const project = document.getElementById("fi-project").value;
  const chosen = fileImportState.rows.filter((r) => r.include && !r.error);
  const byCat = {};
  chosen.forEach((r) => {
    const tags = Array.isArray(r.fields && r.fields.tags) ? r.fields.tags : [];
    (byCat[r.category] = byCat[r.category] || []).push({ title: r.title.trim() || "Untitled", text: r.text, tags,
      modified: r.fields && r.fields.modified });
  });
  go.disabled = true;
  let made = [];
  try {
    for (const [category, items] of Object.entries(byCat)) {
      for (let i = 0; i < items.length; i += 100) {
        made = made.concat(await postJson("/api/entries/new", { items: items.slice(i, i + 100), category, project }));
      }
    }
  } catch (e) {
    go.disabled = false;
    toast(made.length ? `${plural(made.length, "entry", "entries")} created, then: ${e.message}` : e.message, true);
    return;
  }
  closeFileImport();
  toast(`Imported ${plural(made.length, "entry", "entries")}.`);
  if (made.length === 1) {
    state.view = "entries";
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === "entries"));
    await openEntry(made[0].id);
  } else {
    await setView("entries");
  }
}
