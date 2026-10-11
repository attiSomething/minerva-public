// Minerva frontend - vanilla JS, no build step.

const state = {
  view: "home",
  filters: { search: "", category: "", project: "", to_edit: false, to_record: false, published: "" },
  currentEntryId: null,
  projectsCache: [],
  dupStatusFilter: "unresolved",
  entriesPage: 1,
  entriesPageSize: 25,
};

const appEl = document.getElementById("app");

// -------------------------------------------------------------------------
// fetch helpers
// -------------------------------------------------------------------------

const MINERVA_TOKEN = document.querySelector('meta[name="minerva-token"]').content;

async function api(path, opts) {
  opts = Object.assign({}, opts);
  opts.headers = Object.assign({ "X-Minerva-Token": MINERVA_TOKEN }, opts.headers || {});
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch (e) { /* no body */ }
  if (!res.ok) {
    const msg = (data && data.error) ? data.error : `Request failed (${res.status})`;
    if (data && data.ai_off && typeof showAiOffPanel === "function") showAiOffPanel(data.feature, msg);
    throw new Error(msg);
  }
  return data;
}

function toast(msg, isError) {
  // the AI-off panel already says it, with what to do about it
  if (isError && typeof aiOffPanelOpen === "function" && aiOffPanelOpen()) return;
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  el.classList.toggle("error", !!isError);
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.add("hidden"), 3200);
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

// -------------------------------------------------------------------------
// nav / boot
// -------------------------------------------------------------------------

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => setView(btn.dataset.view));
});

document.getElementById("rescan-btn").addEventListener("click", async () => {
  const el = document.getElementById("sync-status");
  el.textContent = "Rescanning...";
  try {
    const r = await api("/api/sync", { method: "POST" });
    el.textContent = `${r.total_entries} entries indexed`;
    if (state.view === "entries") renderEntries();
    else if (state.view === "home") renderHome();
    else if (state.view === "checks") renderChecks();
    refreshAlertsBadge();
  } catch (e) {
    el.textContent = "Rescan failed";
    toast(e.message, true);
  }
});

// The Entries tab holds several views of the library, switched by a strip at
// the top so the main nav stays short.
const ENTRY_PANES = [["entries", "All entries"], ["people", "People"], ["images", "Images"], ["duplicates", "Duplicates"]];

function entryPanesHtml(active) {
  return `<div class="entry-panes" role="tablist" aria-label="Entries">
    ${ENTRY_PANES.map(([v, label]) => `<button class="entry-pane ${v === active ? "active" : ""}" role="tab" aria-selected="${v === active}" data-pane="${v}">${label}${v === "duplicates" ? ' <span class="pane-count" id="dup-count"></span>' : ""}</button>`).join("")}
    <span class="spacer"></span>
    ${helpLinkHtml(active === "entries" ? "entries" : active)}
    <button class="btn btn-ghost btn-small" data-import-files>Import files...</button>
    <button class="btn btn-gold btn-small" data-new-entry>New entry</button>
  </div>`;
}

function wireEntryPanes() {
  const here = () => ({ category: state.filters.category, project: state.filters.project === "__none__" ? "" : state.filters.project });
  appEl.querySelectorAll("[data-new-entry]").forEach((b) => b.addEventListener("click", () => openNewEntry(here())));
  appEl.querySelectorAll("[data-import-files]").forEach((b) => b.addEventListener("click", () => openFileImport(here())));
  appEl.querySelectorAll("[data-pane]").forEach((b) => b.addEventListener("click", () => {
    if (!b.classList.contains("active")) setView(b.dataset.pane);
  }));
  api("/api/duplicates?status=unresolved").then((pairs) => {
    const el = document.getElementById("dup-count");
    if (el && pairs.length) el.textContent = pairs.length;
  }).catch(() => {});
}

async function setView(view) {
  stopReading();
  if (state.view === "scans" && view !== "scans" && typeof confirmDiscard === "function") {
    if (!confirmDiscard()) return;
    scanState.dirty = false;
  }
  state.view = view;
  state.returnTo = null;
  const tab = ENTRY_PANES.some(([v]) => v === view) ? "entries" : view;
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === tab));
  if (view === "home") await renderHome();
  else if (view === "entries") await renderEntries();
  else if (view === "duplicates") await renderDuplicates();
  else if (view === "images") await renderImages();
  else if (view === "people") await renderPeople();
  else if (view === "projects") await renderProjects();
  else if (view === "submissions") await renderSubmissions();
  else if (view === "views") await renderViews();
  else if (view === "scans") await renderScans();
  else if (view === "settings") await renderSettings();
  else if (view === "docs") await renderDocs();
  else if (view === "checks") await renderChecks();
}

// -------------------------------------------------------------------------
// ALERTS (quiet-failure detection, surfaced instead of hidden)
// -------------------------------------------------------------------------

async function refreshAlertsBadge() {
  const badge = document.getElementById("alerts-badge");
  try {
    const result = await api("/api/entries?needs_review=1&page_size=1");
    if (result.total > 0) {
      badge.textContent = `⚠ ${result.total} need${result.total === 1 ? "s" : ""} review`;
      badge.classList.remove("hidden");
    } else {
      badge.classList.add("hidden");
    }
  } catch (e) {
    badge.classList.add("hidden");
  }
}

document.getElementById("alerts-badge").addEventListener("click", async () => {
  await setView("entries");
  const cb = document.getElementById("f-needs-review");
  if (cb) {
    cb.checked = true;
    await loadAndRenderEntryTable(true);
  }
});

async function loadProjects() {
  state.projectsCache = await api("/api/projects");
  return state.projectsCache;
}

// -------------------------------------------------------------------------
// ENTRIES LIST VIEW
// -------------------------------------------------------------------------

async function renderEntries() {
  if (state.projectsCache.length === 0) await loadProjects();
  await loadCategories();
  [, state.collections] = await Promise.all([loadTags(), api("/api/collections").catch(() => [])]);

  appEl.innerHTML = `
    ${entryPanesHtml("entries")}
    <div class="entries-layout">
      <div class="filters">
        <h3>Filters</h3>
        ${collectionsHtml()}
        <div class="filter-group">
          <label>Category</label>
          <select id="f-category">
            <option value="">All</option>
            ${categoryOptionsHtml(null)}
          </select>
        </div>
        <div class="filter-group">
          <label>Project</label>
          <select id="f-project">
            <option value="">All</option>
            <option value="__none__">No Project</option>
            ${state.projectsCache.map((p) => `<option value="${esc(p.tag)}">${esc(p.name)} [${esc(p.tag)}]</option>`).join("")}
          </select>
        </div>
        ${tagFilterHtml()}
        <div class="filter-group">
          <label>Published</label>
          <select id="f-published">
            <option value="">All</option>
            <option value="1">Published</option>
            <option value="0">Not published</option>
          </select>
        </div>
        <div class="filter-group">
          <div class="filter-check"><input type="checkbox" id="f-to-edit"><label for="f-to-edit">Flagged: To Edit</label></div>
          <div class="filter-check"><input type="checkbox" id="f-to-record"><label for="f-to-record">Flagged: To Record</label></div>
          <div class="filter-check"><input type="checkbox" id="f-needs-review"><label for="f-needs-review">Needs Review (no source header found)</label></div>
        </div>
      </div>
      <div class="entry-table-wrap">
        <div class="search-row">
          <input type="search" id="f-search" placeholder="Search titles...">
          <div class="seg" role="radiogroup" aria-label="What to search">
            <button class="seg-btn" data-search-mode="titles" role="radio">Titles</button>
            <button class="seg-btn" data-search-mode="text" role="radio">Inside drafts</button>
          </div>
        </div>
        <div class="filter-check text-only hidden" id="f-current-row"><input type="checkbox" id="f-current"><label for="f-current">Current drafts only (skip Archive and notes)</label></div>
        <div class="entry-toolbar">
          <div class="entry-count" id="entry-count"></div>
          <div class="page-size-group">
            <label for="f-page-size">Show</label>
            <select id="f-page-size">
              <option value="25">25</option>
              <option value="50">50</option>
              <option value="100">100</option>
              <option value="0">All</option>
            </select>
          </div>
        </div>
        <div id="entry-table-container"><div class="empty-state">Loading...</div></div>
        <div class="pagination-controls" id="pagination-controls"></div>
      </div>
    </div>
  `;

  document.getElementById("f-page-size").value = String(state.entriesPageSize);
  document.getElementById("f-search").value = state.searchQuery || "";

  wireEntryPanes();
  wireCollections();
  ["f-category", "f-project", "f-published", "f-tag"].forEach((id) => {
    document.getElementById(id).addEventListener("change", () => loadAndRenderEntryTable(true));
  });
  ["f-to-edit", "f-to-record", "f-needs-review"].forEach((id) => {
    document.getElementById(id).addEventListener("change", () => loadAndRenderEntryTable(true));
  });
  document.getElementById("f-page-size").addEventListener("change", (e) => {
    state.entriesPageSize = parseInt(e.target.value, 10) || 0;
    loadAndRenderEntryTable(true);
  });
  let searchTimer;
  document.getElementById("f-search").addEventListener("input", (ev) => {
    state.searchQuery = ev.target.value;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadAndRenderEntryTable(true), 250);
  });
  document.getElementById("f-current").addEventListener("change", () => loadAndRenderEntryTable(true));
  appEl.querySelectorAll("[data-search-mode]").forEach((b) => b.addEventListener("click", () => {
    state.searchMode = b.dataset.searchMode;
    applySearchMode();
    loadAndRenderEntryTable(true);
    document.getElementById("f-search").focus();
  }));
  applySearchMode();

  await loadAndRenderEntryTable();
}

function applySearchMode() {
  const text = state.searchMode === "text";
  appEl.querySelectorAll("[data-search-mode]").forEach((b) => {
    const on = b.dataset.searchMode === (text ? "text" : "titles");
    b.classList.toggle("active", on);
    b.setAttribute("aria-checked", on);
  });
  document.getElementById("f-search").placeholder = text ? "Find words or a phrase in your drafts..." : "Search titles...";
  document.getElementById("f-current-row").classList.toggle("hidden", !text);
  // flag and published filters apply to titles only
  appEl.querySelectorAll("#f-published, #f-to-edit, #f-to-record, #f-needs-review").forEach((el) => { el.disabled = text; });
  document.getElementById("f-page-size").parentElement.classList.toggle("hidden", text);
}

async function loadAndRenderEntryTable(resetPage) {
  if (resetPage) state.entriesPage = 1;
  if (state.searchMode === "text") return renderTextSearch();

  const params = new URLSearchParams();
  const search = document.getElementById("f-search").value.trim();
  const category = document.getElementById("f-category").value;
  const project = document.getElementById("f-project").value;
  const published = document.getElementById("f-published").value;
  const toEdit = document.getElementById("f-to-edit").checked;
  const toRecord = document.getElementById("f-to-record").checked;
  const needsReview = document.getElementById("f-needs-review").checked;

  if (search) params.set("search", search);
  if (category) params.set("category", category);
  if (project) params.set("project", project);
  if (published) params.set("published", published);
  if (toEdit) params.set("to_edit", "1");
  if (toRecord) params.set("to_record", "1");
  if (needsReview) params.set("needs_review", "1");
  const tag = document.getElementById("f-tag").value;
  if (tag) params.set("tag", tag);
  params.set("page", state.entriesPage);
  params.set("page_size", state.entriesPageSize);

  const result = await api(`/api/entries?${params.toString()}`);
  const rows = result.rows;
  const container = document.getElementById("entry-table-container");
  const countEl = document.getElementById("entry-count");

  if (result.total === 0) {
    countEl.textContent = "";
    const filtered = [...params.keys()].some((k) => !["page", "page_size"].includes(k));
    container.innerHTML = filtered ? `<div class="empty-state">No entries match these filters.</div>` : emptyLibraryHtml();
    wireEmptyActions(container);
    document.getElementById("pagination-controls").innerHTML = "";
    return;
  }

  if (!state.entriesPageSize || state.entriesPageSize <= 0) {
    countEl.textContent = `${result.total} entr${result.total === 1 ? "y" : "ies"}`;
  } else {
    const start = (result.page - 1) * state.entriesPageSize + 1;
    const end = Math.min(result.page * state.entriesPageSize, result.total);
    countEl.textContent = `Showing ${start}–${end} of ${result.total}`;
  }

  container.innerHTML = `
    <table class="entry-table">
      <thead>
        <tr>
          <th>Title</th>
          <th>Category</th>
          <th>Project</th>
          <th>Draft</th>
          <th>Words</th>
          <th title="Lines with words on them">Lines</th>
          <th>Flags</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map(rowHtml).join("")}
      </tbody>
    </table>
  `;

  container.querySelectorAll("tr[data-id]").forEach((tr) => {
    tr.addEventListener("click", () => openEntry(parseInt(tr.dataset.id, 10)));
  });

  renderPaginationControls(result);
}

function renderPaginationControls(result) {
  const el = document.getElementById("pagination-controls");
  const pageSize = state.entriesPageSize;
  if (!pageSize || pageSize <= 0) {
    el.innerHTML = "";
    return;
  }
  const totalPages = Math.max(1, Math.ceil(result.total / pageSize));
  if (totalPages <= 1) {
    el.innerHTML = "";
    return;
  }
  el.innerHTML = `
    <button class="btn btn-ghost btn-small" id="page-prev" ${result.page <= 1 ? "disabled" : ""}>&larr; Prev</button>
    <span class="page-indicator">Page ${result.page} of ${totalPages}</span>
    <button class="btn btn-ghost btn-small" id="page-next" ${result.page >= totalPages ? "disabled" : ""}>Next &rarr;</button>
  `;
  document.getElementById("page-prev").addEventListener("click", () => {
    state.entriesPage = Math.max(1, state.entriesPage - 1);
    loadAndRenderEntryTable();
  });
  document.getElementById("page-next").addEventListener("click", () => {
    state.entriesPage = state.entriesPage + 1;
    loadAndRenderEntryTable();
  });
}

function rowHtml(r) {
  const flags = [];
  if (r.to_edit) flags.push(`<span class="flag-dot to_edit"></span>`);
  if (r.published) flags.push(`<span class="flag-dot published"></span>`);
  if (r.to_record) flags.push(`<span class="flag-dot to_record"></span>`);
  if (r.draft_tag === "J" && r.has_journal_header === 0) {
    flags.push(`<span class="flag-dot needs_review" title="Tagged [J] but no Source header found"></span>`);
  }
  return `
    <tr data-id="${r.id}">
      <td>${esc(r.title)}${r.tags && r.tags.length ? ` <span class="row-tags">${tagChipsHtml(r.tags, { small: true })}</span>` : ""}</td>
      <td>${esc(r.top_folder)}</td>
      <td>${r.project_tag ? `<span class="badge badge-project">${esc(r.project_tag)}</span>` : ""}</td>
      <td><span class="badge badge-tag-${r.draft_tag}">${esc(r.draft_tag || "?")}</span>${r.has_final ? ' <span class="badge badge-final" title="Has a final draft">Final</span>' : ""}</td>
      <td>${r.word_count}</td>
      <td>${r.line_count || ""}</td>
      <td>${flags.join("")}</td>
    </tr>
  `;
}

// -------------------------------------------------------------------------
// EDIT VIEW
// -------------------------------------------------------------------------

function editCountsText(words, lines, stanzas) {
  return `${plural(words || 0, "word", "words")} · ${plural(lines || 0, "line", "lines")} · ${plural(stanzas || 0, "stanza", "stanzas")}`;
}

// Notes save themselves a moment after typing stops, and again on the way
// out of the entry if a save is still pending.
const notesSaver = { timer: null, pending: null };

function flushNotes() {
  clearTimeout(notesSaver.timer);
  const p = notesSaver.pending;
  notesSaver.pending = null;
  if (!p) return Promise.resolve();
  const status = document.getElementById("notes-status");
  return postJson(`/api/entries/${p.id}/notes`, { body: p.body })
    .then(() => { if (status && state.currentEntryId === p.id) status.textContent = "Saved"; })
    .catch((err) => {
      if (status) status.textContent = "Not saved";
      toast(`Notes weren't saved: ${err.message}`, true);
    });
}

window.addEventListener("pagehide", () => {
  const p = notesSaver.pending;
  if (p) fetch(`/api/entries/${p.id}/notes`, { method: "POST", keepalive: true, body: JSON.stringify({ body: p.body }),
    headers: { "Content-Type": "application/json", "X-Minerva-Token": MINERVA_TOKEN } });
});

function wireNotes(id) {
  const box = document.getElementById("notes-input");
  const status = document.getElementById("notes-status");
  const fit = () => { box.style.height = "auto"; box.style.height = `${Math.min(Math.max(box.scrollHeight, 90), 420)}px`; };
  fit();
  box.addEventListener("input", () => {
    fit();
    notesSaver.pending = { id, body: box.value };
    status.textContent = "Saving...";
    clearTimeout(notesSaver.timer);
    notesSaver.timer = setTimeout(flushNotes, 700);
  });
  box.addEventListener("blur", flushNotes);
}

async function openEntry(id) {
  state.currentEntryId = id;
  await renderEdit();
}

async function renderEdit() {
  stopReading();
  if (state.projectsCache.length === 0) await loadProjects();
  await loadCategories();
  const [e] = await Promise.all([api(`/api/entries/${state.currentEntryId}`), loadTags()]);

  appEl.innerHTML = `
    <button class="back-link" id="back-btn">&larr; Back to ${state.returnTo ? ({ project: "project", home: "home", submissions: "submissions", checks: "library check", people: "people", views: "views" }[state.returnTo.view] || "entries") : "entries"}</button>
    <div class="edit-header">
      <div class="edit-title">
        <h2>${esc(e.title)}</h2>
        <span class="badge badge-tag-${e.draft_tag}">${esc(e.draft_tag || "?")}</span>
      </div>
      <div class="edit-meta">${esc(e.top_folder)}${e.project_tag ? " &middot; " + esc(e.project_tag) : ""} &middot; <span id="edit-counts">${editCountsText(e.word_count, e.line_count, e.stanza_count)}</span> &middot; ${helpLinkHtml("edit")}</div>
    </div>
    <div class="edit-layout">
      <div class="edit-main">
        ${findBarHtml()}
        <textarea id="editor" spellcheck="true">${esc(e.content)}</textarea>
        <div class="save-row">
          <button class="btn" id="save-overwrite">Save (Overwrite draft)</button>
          <button class="btn btn-ghost" id="save-archive">Save (Archive current draft)</button>
          <button class="btn btn-ghost focus-btn" id="focus-open" title="Full-screen writing, without distractions (Esc to leave)">Focus</button>
          <button class="btn btn-ghost" id="find-open" title="Find and replace in this draft (Ctrl+F, or Ctrl+H to replace)">Find</button>
          <button class="btn btn-ghost" id="grammar-open" title="Grammar and style suggestions from LanguageTool, on this computer">Grammar</button>
          ${readAloudAvailable() ? `<button class="btn btn-ghost" id="read-aloud" title="Hear the draft read by your computer's voice, from the cursor or just the selection">Read aloud</button>` : ""}
        </div>
        <div id="grammar-results"></div>
      </div>
      <div class="edit-side">
        <div class="panel">
          <h3>Title</h3>
          <div class="field-row">
            <input type="text" id="title-input" value="${esc(e.title)}">
          </div>
          <button class="btn btn-small" id="rename-btn">Rename</button>
          <div class="dup-note" style="margin-top:8px">Renames the entry's folder and file(s) on disk.</div>
        </div>

        <div class="panel notes-panel">
          <div class="panel-head-row"><h3><label for="notes-input">Notes</label></h3><span class="hint" id="notes-status"></span></div>
          <textarea id="notes-input" spellcheck="true" placeholder="Thoughts on revising, research, reminders. Kept beside the draft, never inside it.">${esc(e.notes.body)}</textarea>
        </div>

        ${tagsPanelHtml(e)}

        <div class="panel ask-panel">
          <h3>Ask Minerva <span class="optional">AI</span></h3>
          <div class="ask-buttons">
            <button class="btn btn-small btn-ghost" id="ask-suggest">Suggest title, category and project</button>
            <button class="btn btn-small btn-ghost" id="ask-proofread">Proofread this draft</button>
          </div>
          <div id="ask-result"></div>
        </div>

        <div class="panel">
          <h3>Flags</h3>
          <div class="checkbox-row">
            <input type="checkbox" id="flag-to-edit" ${e.to_edit ? "checked" : ""}>
            <label for="flag-to-edit">To Edit</label>
          </div>
          <div class="checkbox-row">
            <input type="checkbox" id="flag-to-record" ${e.to_record ? "checked" : ""}>
            <label for="flag-to-record">To Record</label>
          </div>
          <div class="checkbox-row">
            <input type="checkbox" id="flag-published" ${e.published ? "checked" : ""}>
            <label for="flag-published">Published</label>
          </div>
          <div class="field-row" id="published-where-row" style="${e.published ? "" : "display:none"}">
            <label>Published where</label>
            <input type="text" id="published-where" value="${esc(e.published_where || "")}" placeholder="e.g. a magazine, a site...">
          </div>
        </div>

        ${sharePanelHtml(e)}

        ${subPanelHtml()}

        <div class="panel">
          <h3>Project</h3>
          <div class="field-row">
            <select id="project-select">
              <option value="">No Project</option>
              ${state.projectsCache.map((p) => `<option value="${esc(p.tag)}" ${e.project_tag === p.tag ? "selected" : ""}>${esc(p.name)} [${esc(p.tag)}]</option>`).join("")}
              <option value="${NEW_PROJECT}">New project…</option>
            </select>
          </div>
        </div>

        <div class="panel">
          <h3>Category</h3>
          <div class="field-row">
            <select id="category-select" data-category-menu>
              ${categoryOptionsHtml(e.top_folder, { withNew: true })}
            </select>
          </div>
        </div>

        <div class="panel">
          <div class="panel-head-row">
            <h3>Old Drafts (Archive)</h3>
            ${e.archive.some((a) => a.is_text) ? `<button class="btn btn-ghost btn-small" id="compare-drafts">Compare drafts</button>` : ""}
          </div>
          <ul class="archive-list" id="archive-list">
            ${e.archive.length === 0 ? '<li class="archive-name">Nothing archived yet.</li>' :
              e.archive.map((a) => `
                <li>
                  <span class="archive-name" title="${esc(a.name)}">${esc(a.name)}</span>
                  <span class="archive-actions">
                    ${a.is_text ? `<button class="btn btn-ghost btn-small" data-view-archive="${esc(a.name)}">View</button>
                    <button class="btn btn-ghost btn-small" data-restore-archive="${esc(a.name)}">Restore</button>
                    <button class="btn btn-ghost btn-small" data-final-archive="${esc(a.name)}" title="Make this older draft the final draft">Final</button>` : '<span class="badge">binary</span>'}
                  </span>
                </li>
              `).join("")}
          </ul>
        </div>

        ${e.journal_scan && e.journal_scan.journal ? `
          <div class="panel">
            <h3>Scanned Pages</h3>
            <div class="edit-meta">${esc(e.journal_scan.journal)}${e.journal_scan.entry_num ? " &middot; Entry " + e.journal_scan.entry_num : ""}</div>
            ${e.journal_scan.available ? `
              ${(e.journal_scan.pages || []).length ? `<div class="hint">${e.journal_scan.pages.map((p) => `${esc(p.filename)}, page ${p.page}`).join("<br>")}</div>` : ""}
              ${e.journal_scan.link_note ? `<div class="hint warn-text">${esc(e.journal_scan.link_note)}</div>` : ""}
              <div class="field-row scan-links" style="margin-top:10px">
                ${(e.journal_scan.pages || []).length ? `<button class="btn btn-small" id="view-scan-pages">View ${e.journal_scan.pages.length === 1 ? "page" : `all ${e.journal_scan.pages.length} pages`}</button>` : ""}
                <a class="btn btn-small btn-ghost" href="/api/entries/${e.id}/scan/pdf" target="_blank" rel="noopener">Open ${esc(e.journal_scan.pdf_name)}</a>
                <button class="btn btn-small btn-ghost" id="fix-scan-pages">Change pages</button>
              </div>
              ${e.journal_scan.excerpt ? `<div class="dup-compare-text" style="margin-top:8px;max-height:220px">${esc(e.journal_scan.excerpt)}</div>` : ""}
            ` : `
              <div class="dup-unlinked" style="margin-top:8px">${esc(e.journal_scan.reason || "Scan not available for this entry.")}</div>
            `}
          </div>
        ` : ""}

        <div class="panel">
          <h3>Merge Another Entry In</h3>
          <div class="dup-note" style="margin-top:0;margin-bottom:8px">
            Folds another entry's whole folder into this one's Archive (e.g. a raw transcribed entry as this entry's original draft). Nothing is deleted.
          </div>
          <div class="field-row">
            <input type="text" id="merge-search" placeholder="Search entries to merge in...">
          </div>
          <div id="merge-search-results"></div>
        </div>
      </div>
    </div>
    <div id="archive-preview"></div>
  `;

  document.getElementById("back-btn").addEventListener("click", () => {
    const back = state.returnTo;
    state.returnTo = null;
    if (back && back.view === "project") {
      state.view = "projects";
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === "projects"));
      openProject(back.id);
    } else if (back && ["home", "submissions", "checks", "people", "views"].includes(back.view)) setView(back.view);
    else setView("entries");
  });
  document.getElementById("ask-suggest").addEventListener("click", (ev) => askSuggest(ev.target, e));
  document.getElementById("ask-proofread").addEventListener("click", (ev) => askProofread(ev.target));
  wireGrammar(e);

  document.getElementById("rename-btn").addEventListener("click", () => renameEntry(e.title));
  document.getElementById("title-input").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") renameEntry(e.title);
  });

  let mergeSearchTimer;
  document.getElementById("merge-search").addEventListener("input", (ev) => {
    clearTimeout(mergeSearchTimer);
    const q = ev.target.value.trim();
    mergeSearchTimer = setTimeout(() => searchMergeCandidates(q), 250);
  });

  document.getElementById("save-overwrite").addEventListener("click", () => saveEntry("overwrite"));
  document.getElementById("save-archive").addEventListener("click", () => saveEntry("archive"));
  document.getElementById("focus-open").addEventListener("click", openFocus);
  markFirstRun("edit");
  wireFindBar(document.getElementById("editor"));
  wireNotes(e.id);
  const readBtn = document.getElementById("read-aloud");
  if (readBtn) readBtn.addEventListener("click", () => {
    if (readState.bar) { stopReading(); return; }
    startReading(document.getElementById("editor"), document.querySelector(".edit-main .save-row"), "read-bar");
  });
  wireTagsPanel(e.id, e.tags);

  document.getElementById("flag-to-edit").addEventListener("change", (ev) =>
    updateFlags({ to_edit: ev.target.checked }));
  document.getElementById("flag-to-record").addEventListener("change", (ev) =>
    updateFlags({ to_record: ev.target.checked }));
  document.getElementById("flag-published").addEventListener("change", (ev) => {
    document.getElementById("published-where-row").style.display = ev.target.checked ? "" : "none";
    updateFlags({ published: ev.target.checked });
  });
  document.getElementById("published-where").addEventListener("change", (ev) =>
    updateFlags({ published_where: ev.target.value }));

  document.getElementById("project-select").addEventListener("change", async (ev) => {
    let tag = ev.target.value;
    if (tag === NEW_PROJECT) {
      tag = await newProjectPrompt();
      if (!tag) { ev.target.value = e.project_tag || ""; return; }
    }
    try {
      await api(`/api/entries/${state.currentEntryId}/project`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tag: tag || null }),
      });
      toast("Project updated.");
      await renderEdit();
    } catch (err) {
      toast(err.message, true);
    }
  });

  wireCategorySelect(document.getElementById("category-select"), async (category) => {
    try {
      await api(`/api/entries/${state.currentEntryId}/category`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category }),
      });
      toast("Category updated.");
      await renderEdit();
    } catch (err) {
      toast(err.message, true);
    }
  });

  document.querySelectorAll("[data-view-archive]").forEach((btn) => {
    btn.addEventListener("click", () => viewArchiveFile(btn.dataset.viewArchive));
  });
  const compareBtn = document.getElementById("compare-drafts");
  if (compareBtn) compareBtn.addEventListener("click", () => openCompare(e));
  state.currentEntry = e;
  document.querySelectorAll("[data-final-archive]").forEach((btn) => {
    btn.addEventListener("click", () => markArchiveFinal(e.id, btn.dataset.finalArchive));
  });
  wireSharePanel(e);
  renderSubPanel({ kind: "entry", id: e.id, title: e.title });
  const viewPages = document.getElementById("view-scan-pages");
  if (viewPages) viewPages.addEventListener("click", () =>
    openPageViewer(e.journal_scan.journal, e.journal_scan.pages.map((p) => [p.scan, p.page]),
      e.journal_scan.pages.map((p) => `${p.filename}, page ${p.page}`)));
  const fixPages = document.getElementById("fix-scan-pages");
  if (fixPages) fixPages.addEventListener("click", () => openScanEntry(e.journal_scan.journal, e.journal_scan.entry_num));
  document.querySelectorAll("[data-restore-archive]").forEach((btn) => {
    btn.addEventListener("click", () => restoreArchiveFile(btn.dataset.restoreArchive));
  });
}

// -------------------------------------------------------------------------
// Ask Minerva (AI-assisted organizing and editing; suggestions only)
// -------------------------------------------------------------------------

async function askBusy(btn, label, fn) {
  const before = btn.textContent;
  btn.disabled = true;
  btn.textContent = label;
  try { await fn(); }
  catch (err) {
    const out = document.getElementById("ask-result");
    if (out) out.innerHTML = `<div class="ai-banner">${esc(err.message)}${/Settings/.test(err.message) ? ' <button class="btn btn-small btn-ghost" data-goto-settings>Open Settings</button>' : ""}</div>`;
    document.querySelectorAll("#ask-result [data-goto-settings]").forEach((b) => b.addEventListener("click", () => setView("settings")));
  }
  btn.disabled = false;
  btn.textContent = before;
}

async function askSuggest(btn, e) {
  await askBusy(btn, "Thinking...", async () => {
    const s = await api(`/api/entries/${e.id}/ai/suggest`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    const proj = s.project ? state.projectsCache.find((p) => p.tag === s.project) : null;
    const rows = [];
    if (s.title && s.title !== e.title) rows.push(["Title", esc(s.title), "title"]);
    if (s.category && s.category !== e.top_folder) rows.push(["Category", esc(s.category), "category"]);
    if (s.project && s.project !== e.project_tag) rows.push(["Project", esc(proj ? `${proj.name} [${proj.tag}]` : s.project), "project"]);
    const out = document.getElementById("ask-result");
    out.innerHTML = rows.length ? `
      <div class="suggest-box">
        ${rows.map(([k, v, field]) => `<div class="suggest-row"><span><b>${k}:</b> ${v}</span><button class="btn btn-small" data-apply="${field}">Use</button></div>`).join("")}
        ${s.reason ? `<div class="hint">${esc(s.reason)}</div>` : ""}
      </div>` : `<div class="hint">Minerva would keep this entry as it is.${s.reason ? " " + esc(s.reason) : ""}</div>`;
    out.querySelectorAll("[data-apply]").forEach((b) => b.addEventListener("click", async () => {
      const field = b.dataset.apply;
      if (field === "title") {
        document.getElementById("title-input").value = s.title;
        await renameEntry(e.title);
      } else if (field === "category") {
        const sel = document.getElementById("category-select");
        sel.value = s.category;
        sel.dispatchEvent(new Event("change"));
      } else if (field === "project") {
        const sel = document.getElementById("project-select");
        sel.value = s.project;
        sel.dispatchEvent(new Event("change"));
      }
    }));
  });
}

async function askProofread(btn) {
  const editor = document.getElementById("editor");
  await askBusy(btn, "Proofreading...", async () => {
    const r = await api(`/api/entries/${state.currentEntryId}/ai/proofread`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: editor.value }),
    });
    const changed = r.changes.some(([op]) => op !== "eq");
    const preview = document.getElementById("archive-preview");
    if (!changed) {
      document.getElementById("ask-result").innerHTML = `<div class="hint">No corrections suggested.</div>`;
      return;
    }
    document.getElementById("ask-result").innerHTML = `<div class="hint">Suggested corrections are shown below the editor.</div>`;
    preview.innerHTML = `
      <div class="panel proof-diff-panel">
        <h3>Suggested corrections</h3>
        <div class="hint" style="margin-top:0">Removed words are struck through and additions are highlighted. Nothing changes until you apply them and save.</div>
        <div class="diff-view">${r.changes.map(([op, t]) => op === "eq" ? esc(t) : `<${op}>${esc(t)}</${op}>`).join("")}</div>
        <div class="save-row">
          <button class="btn" id="apply-proof">Put these corrections in the editor</button>
          <button class="btn btn-ghost" id="dismiss-proof">Dismiss</button>
        </div>
      </div>`;
    preview.scrollIntoView({ behavior: "smooth", block: "start" });
    document.getElementById("apply-proof").addEventListener("click", () => {
      editor.value = r.text;
      preview.innerHTML = "";
      editor.scrollIntoView({ behavior: "smooth", block: "center" });
      toast("Corrections are in the editor. Read them over, then save.");
    });
    document.getElementById("dismiss-proof").addEventListener("click", () => { preview.innerHTML = ""; });
  });
}

async function saveEntry(mode) {
  const content = document.getElementById("editor").value;
  try {
    await api(`/api/entries/${state.currentEntryId}/save`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content, mode }),
    });
    toast(mode === "archive" ? "Saved. Previous draft moved to Archive." : "Saved.");
    await renderEdit();
  } catch (err) {
    toast(err.message, true);
  }
}

async function renameEntry(currentTitle) {
  const newTitle = document.getElementById("title-input").value.trim();
  if (!newTitle || newTitle === currentTitle) return;
  if (!confirm(`Rename "${currentTitle}" to "${newTitle}"? This renames the entry's folder and file(s) on disk.`)) return;
  try {
    const result = await api(`/api/entries/${state.currentEntryId}/rename`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: newTitle }),
    });
    toast("Renamed.");
    await renderEdit();
    if (result.warnings && result.warnings.length) {
      showWarningBanner("Renamed, but with warnings", result.warnings);
    }
  } catch (err) {
    toast(err.message, true);
  }
}

function showWarningBanner(heading, messages) {
  const el = document.createElement("div");
  el.className = "panel warning-banner";
  el.innerHTML = `
    <h3>&#9888; ${esc(heading)}</h3>
    <ul>${messages.map((m) => `<li>${esc(m)}</li>`).join("")}</ul>
    <button class="btn btn-ghost btn-small" id="dismiss-warning-banner">Dismiss</button>
  `;
  appEl.prepend(el);
  document.getElementById("dismiss-warning-banner").addEventListener("click", () => el.remove());
}

async function searchMergeCandidates(q) {
  const el = document.getElementById("merge-search-results");
  if (!el) return;
  if (!q) {
    el.innerHTML = "";
    return;
  }
  const result = await api(`/api/entries?search=${encodeURIComponent(q)}&page_size=8`);
  const candidates = result.rows.filter((r) => r.id !== state.currentEntryId);
  if (candidates.length === 0) {
    el.innerHTML = `<div class="dup-note" style="margin-top:8px">No matches.</div>`;
    return;
  }
  el.innerHTML = candidates.map((r) => `
    <div class="merge-candidate">
      <span>${esc(r.title)} <span class="badge">${esc(r.top_folder)}</span>${r.project_tag ? ` <span class="badge badge-project">${esc(r.project_tag)}</span>` : ""}</span>
      <button class="btn btn-ghost btn-small" data-merge-id="${r.id}" data-merge-title="${esc(r.title)}">Merge in</button>
    </div>
  `).join("");
  el.querySelectorAll("[data-merge-id]").forEach((btn) => {
    btn.addEventListener("click", () => mergeEntryIn(btn.dataset.mergeId, btn.dataset.mergeTitle));
  });
}

async function mergeEntryIn(otherId, otherTitle) {
  if (!confirm(`Merge "${otherTitle}" into this entry? Its whole folder (including its own Archive) will be moved into this entry's Archive. Nothing is deleted.`)) return;
  try {
    await api(`/api/entries/${state.currentEntryId}/merge_from`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ other_id: parseInt(otherId, 10) }),
    });
    toast("Merged.");
    await renderEdit();
  } catch (err) {
    toast(err.message, true);
  }
}

async function updateFlags(fields) {
  try {
    await api(`/api/entries/${state.currentEntryId}/flags`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields),
    });
  } catch (err) {
    toast(err.message, true);
  }
}

async function viewArchiveFile(name) {
  try {
    const data = await api(`/api/entries/${state.currentEntryId}/archive/${encodeURIComponent(name)}`);
    const el = document.getElementById("archive-preview");
    el.innerHTML = `
      <div class="panel" style="margin-top:16px">
        <div class="panel-head-row">
          <h3>Viewing: ${esc(name)}</h3>
          <button class="btn btn-ghost btn-small" id="compare-this">Compare with current draft</button>
        </div>
        <div class="dup-compare-text">${esc(data.content)}</div>
      </div>
    `;
    document.getElementById("compare-this").addEventListener("click", () => openCompare(state.currentEntry, name, ""));
    el.scrollIntoView({ behavior: "smooth" });
  } catch (err) {
    toast(err.message, true);
  }
}

async function restoreArchiveFile(name) {
  if (!confirm(`Restore "${name}" as the current draft? The current draft will be archived first, nothing is deleted.`)) return;
  try {
    await api(`/api/entries/${state.currentEntryId}/archive/${encodeURIComponent(name)}/restore`, { method: "POST" });
    toast("Restored as current draft.");
    await renderEdit();
  } catch (err) {
    toast(err.message, true);
  }
}

// -------------------------------------------------------------------------
// DUPLICATES VIEW
// -------------------------------------------------------------------------

async function renderDuplicates() {
  appEl.innerHTML = `
    ${entryPanesHtml("duplicates")}
    <div class="dup-tabs">
      ${["unresolved", "confirmed", "not_duplicate", "merged", ""].map((s) => `
        <button class="btn btn-ghost dup-tab-btn ${state.dupStatusFilter === s ? "active" : ""}" data-status="${s}">
          ${s === "" ? "All" : s.replace("_", " ")}
        </button>
      `).join("")}
    </div>
    <div id="dup-list"><div class="empty-state">Loading...</div></div>
  `;

  wireEntryPanes();
  document.querySelectorAll(".dup-tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.dupStatusFilter = btn.dataset.status;
      renderDuplicates();
    });
  });

  const pairs = await api(`/api/duplicates${state.dupStatusFilter ? "?status=" + state.dupStatusFilter : ""}`);
  const listEl = document.getElementById("dup-list");

  if (pairs.length === 0) {
    listEl.innerHTML = `<div class="empty-state">No duplicate pairs in this view.</div>`;
    return;
  }

  listEl.innerHTML = pairs.map(dupPairHtml).join("");

  listEl.querySelectorAll(".dup-pair-header").forEach((header) => {
    header.addEventListener("click", () => {
      const card = header.closest(".dup-pair");
      const wasOpen = card.classList.contains("open");
      card.classList.toggle("open", !wasOpen);
      if (!wasOpen) loadDupCompare(card);
    });
  });

  listEl.querySelectorAll("[data-dup-action]").forEach((btn) => {
    btn.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      const card = btn.closest(".dup-pair");
      const id = parseInt(card.dataset.id, 10);
      const action = btn.dataset.dupAction;
      try {
        if (action === "confirmed" || action === "not_duplicate" || action === "unresolved") {
          await api(`/api/duplicates/${id}/status`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status: action }),
          });
        } else if (action === "merge_a" || action === "merge_b") {
          const keep = action === "merge_a" ? "a" : "b";
          if (!confirm("Merge these? The losing entry's whole folder (including its own Archive) will be moved, unmodified, into the kept entry's Archive folder. Nothing is deleted.")) return;
          await api(`/api/duplicates/${id}/merge`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ keep }),
          });
        }
        toast("Updated.");
        await renderDuplicates();
      } catch (err) {
        toast(err.message, true);
      }
    });
  });
}

function dupPairHtml(p) {
  const scoreText = p.title_score != null
    ? `title match ${(p.title_score * 100).toFixed(0)}% &middot; content match ${(p.content_score * 100).toFixed(0)}%`
    : "hand-confirmed";
  const titleA = p.entry_a ? p.entry_a.title : p.title_a;
  const titleB = p.entry_b ? p.entry_b.title : p.title_b;
  return `
    <div class="dup-pair" data-id="${p.id}">
      <div class="dup-pair-header">
        <div>
          <div class="dup-pair-titles">${esc(titleA)}<span class="vs">&harr;</span>${esc(titleB)}</div>
          <div class="dup-pair-scores">${scoreText}${p.folder_hint ? " &middot; " + esc(p.folder_hint) : ""}</div>
        </div>
        <div class="badge dup-pair-status">${esc(p.status.replace("_", " "))}</div>
      </div>
      <div class="dup-pair-body" data-loaded="0"></div>
    </div>
  `;
}

async function loadDupCompare(card) {
  const body = card.querySelector(".dup-pair-body");
  if (body.dataset.loaded === "1") return;
  const id = card.dataset.id;
  const pairs = await api(`/api/duplicates?status=`);
  const p = pairs.find((x) => String(x.id) === String(id));
  if (!p) return;

  const [contentA, contentB] = await Promise.all([
    p.entry_a ? api(`/api/entries/${p.entry_a.id}`) : null,
    p.entry_b ? api(`/api/entries/${p.entry_b.id}`) : null,
  ]);

  const titleA = p.entry_a ? p.entry_a.title : p.title_a;
  const titleB = p.entry_b ? p.entry_b.title : p.title_b;

  body.innerHTML = `
    <div class="dup-compare">
      <div class="dup-compare-col">
        <h4>${esc(titleA)}</h4>
        ${contentA ? `<div class="dup-compare-text">${esc(contentA.content)}</div>` : `<div class="dup-unlinked">Not linked to a current entry (title may have changed since this pair was found).</div>`}
      </div>
      <div class="dup-compare-col">
        <h4>${esc(titleB)}</h4>
        ${contentB ? `<div class="dup-compare-text">${esc(contentB.content)}</div>` : `<div class="dup-unlinked">Not linked to a current entry (title may have changed since this pair was found).</div>`}
      </div>
    </div>
    <div class="dup-actions">
      ${p.status !== "not_duplicate" ? `<button class="btn btn-ghost btn-small" data-dup-action="not_duplicate">Not a Duplicate</button>` : ""}
      ${p.status === "unresolved" ? `<button class="btn btn-ghost btn-small" data-dup-action="confirmed">Confirm Duplicate</button>` : ""}
      ${p.status !== "unresolved" && p.status !== "merged" ? `<button class="btn btn-ghost btn-small" data-dup-action="unresolved">Reset to Unresolved</button>` : ""}
      ${contentA && contentB && p.status !== "merged" ? `
        <button class="btn btn-small" data-dup-action="merge_a">Merge &rarr; keep "${esc(titleA)}"</button>
        <button class="btn btn-small" data-dup-action="merge_b">Merge &rarr; keep "${esc(titleB)}"</button>
      ` : ""}
    </div>
    ${p.note ? `<div class="dup-note">${esc(p.note)}</div>` : ""}
  `;

  body.querySelectorAll("[data-dup-action]").forEach((btn) => {
    btn.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      const action = btn.dataset.dupAction;
      try {
        if (action === "merge_a" || action === "merge_b") {
          const keep = action === "merge_a" ? "a" : "b";
          if (!confirm("Merge these? The losing entry's whole folder (including its own Archive) will be moved, unmodified, into the kept entry's Archive folder. Nothing is deleted.")) return;
          await api(`/api/duplicates/${id}/merge`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ keep }),
          });
        } else {
          await api(`/api/duplicates/${id}/status`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status: action }),
          });
        }
        toast("Updated.");
        await renderDuplicates();
      } catch (err) {
        toast(err.message, true);
      }
    });
  });

  body.dataset.loaded = "1";
}

// -------------------------------------------------------------------------
// PROJECTS VIEW
// -------------------------------------------------------------------------

// A bare YYYY-MM-DD is read as UTC midnight by Date; pin it to local time.
function dayDate(iso) { return shortDate(`${iso.slice(0, 10)}T00:00`); }

function shortDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function plural(n, one, many) { return `${n.toLocaleString()} ${n === 1 ? one : many}`; }

function projectStatsHtml(p) {
  const cats = Object.entries(p.categories || {});
  return `
    <div class="count">${plural(p.entry_count, "entry", "entries")} · ${plural(p.word_count, "word", "words")}${p.published_count ? ` · ${p.published_count} published` : ""}</div>
    ${cats.length ? `<div class="cat-mix">${cats.map(([c, n]) => `<span class="cat-chip">${esc(c)} ${n}</span>`).join("")}</div>` : ""}
    <div class="count">${p.last_edited ? `Last edited ${esc(shortDate(p.last_edited))}` : "No entries yet"}</div>`;
}

async function deleteProject(p, after) {
  const msg = `Delete the project "${p.name}"?\n\n` +
    (p.entry_count ? `Its ${plural(p.entry_count, "entry stays", "entries stay")} in your library, just without the [${p.tag}] tag. ` : "") +
    `The ${p.folder_path} folder is left as it is.`;
  if (!confirm(msg)) return;
  try {
    const r = await api(`/api/projects/${p.id}/delete`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    toast(`Deleted "${p.name}".` + (r.untagged ? ` ${plural(r.untagged, "entry was", "entries were")} untagged.` : ""));
    state.projectsCache = [];
    await after();
  } catch (err) { toast(err.message, true); }
}

async function renderProjects() {
  state.projectId = null;
  const projects = await loadProjects();
  appEl.innerHTML = `
    <div class="screen-help">${helpLinkHtml("projects", "How to put a chapbook together")}</div>
    <div class="project-grid">
      ${projects.map((p) => `
        <div class="project-card" data-project="${p.id}" tabindex="0" role="button">
          <div class="project-card-head">
            <h4>${esc(p.name)}</h4>
            <button class="icon-btn" data-delete-project="${p.id}" title="Delete project (keeps its entries)">&times;</button>
          </div>
          <div class="tag">[${esc(p.tag)}]</div>
          ${p.description ? `<div class="project-desc">${esc(p.description)}</div>` : ""}
          ${projectStatsHtml(p)}
        </div>
      `).join("") || `<div class="empty-state">No projects yet. Create one below, then add entries to it.</div>`}
    </div>
    <div class="panel" style="max-width:620px">
      <h3>New Project</h3>
      <div class="new-project-form">
        <div class="field-row">
          <label>Name</label>
          <input type="text" id="new-project-name" placeholder="e.g. Some New Thing">
        </div>
        <div class="field-row">
          <label>Tag</label>
          <input type="text" id="new-project-tag" placeholder="e.g. SNT" style="width:90px">
        </div>
        <button class="btn" id="new-project-btn">Create</button>
      </div>
      <div class="hint">The tag is added to the folder name of every entry in the project, like "Title - [SNT]".</div>
    </div>
  `;

  appEl.querySelectorAll("[data-project]").forEach((card) => {
    const open = () => openProject(Number(card.dataset.project));
    card.addEventListener("click", open);
    card.addEventListener("keydown", (ev) => { if (ev.key === "Enter") open(); });
  });
  appEl.querySelectorAll("[data-delete-project]").forEach((b) => b.addEventListener("click", (ev) => {
    ev.stopPropagation();
    deleteProject(projects.find((p) => p.id === Number(b.dataset.deleteProject)), renderProjects);
  }));
  const nameBox = document.getElementById("new-project-name");
  const tagBox = document.getElementById("new-project-tag");
  let tagTouched = false;
  tagBox.addEventListener("input", () => { tagTouched = !!tagBox.value; });
  nameBox.addEventListener("input", () => {
    if (!tagTouched) tagBox.value = nameBox.value.trim() ? suggestProjectTag(nameBox.value, projects.map((p) => p.tag)) : "";
  });
  document.getElementById("new-project-btn").addEventListener("click", async () => {
    const name = document.getElementById("new-project-name").value.trim();
    const tag = document.getElementById("new-project-tag").value.trim();
    if (!name || !tag) { toast("Name and tag are both required.", true); return; }
    try {
      await api("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, tag }),
      });
      toast(`Project "${name}" created.`);
      state.projectsCache = [];
      await renderProjects();
    } catch (err) {
      toast(err.message, true);
    }
  });
}

const NEW_PROJECT = "__new_project__";

// A short tag from a project's name ("Harbor Poems" -> "HP"), made unique.
function suggestProjectTag(name, taken) {
  const words = name.toUpperCase().replace(/[^A-Z0-9 ]+/g, " ").split(/\s+/).filter(Boolean);
  let tag = words.length > 1 ? words.map((w) => w[0]).join("").slice(0, 4) : (words[0] || "P").slice(0, 3);
  const used = new Set(taken.map((t) => t.toUpperCase()));
  const base = tag;
  for (let n = 2; used.has(tag); n++) tag = `${base}${n}`;
  return tag;
}

// From an entry's Project menu: name a new project; its tag is made up
// from the name. Returns the tag, or null if cancelled.
async function newProjectPrompt() {
  const name = (prompt("Name the new project (a chapbook, a collection, a series...).") || "").trim();
  if (!name) return null;
  if (!state.projectsCache.length) await loadProjects();
  const tag = suggestProjectTag(name, state.projectsCache.map((p) => p.tag));
  try {
    await api("/api/projects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, tag }) });
  } catch (err) { toast(err.message, true); return null; }
  state.projectsCache = [];
  await loadProjects();
  toast(`Made the project "${name}" (tag ${tag}).`);
  return tag;
}

function openProject(id) {
  state.projectId = id;
  renderProject();
}

function projectPost(path, body) {
  return api(`/api/projects/${state.projectId}${path}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}),
  });
}

async function renderProject() {
  let p;
  try { p = await api(`/api/projects/${state.projectId}`); }
  catch (err) { toast(err.message, true); return renderProjects(); }
  appEl.innerHTML = `
    <div class="screen-help-row"><button class="back-link" id="back-projects">&larr; All projects</button>${helpLinkHtml("projects")}</div>
    <div class="project-page">
      <div class="project-main">
        <div class="project-head">
          <input type="text" id="proj-name" class="proj-name" value="${esc(p.name)}" aria-label="Project name">
          <span class="badge badge-project">[${esc(p.tag)}]</span>
        </div>
        <textarea id="proj-desc" class="proj-desc" placeholder="What is this project? (optional)">${esc(p.description || "")}</textarea>
        <div class="save-row" id="proj-save-row" style="display:none">
          <button class="btn btn-small" id="proj-save">Save</button>
          <button class="btn btn-small btn-ghost" id="proj-cancel">Cancel</button>
        </div>
        <div class="project-stats">${projectStatsHtml(p)}</div>
        ${projectTargetHtml(p)}

        <div id="outline" class="outline"></div>
      </div>

      <aside class="project-side">
        <div class="panel">
          <h3>Add Entries</h3>
          <input type="text" id="proj-search" placeholder="Search titles...">
          <div id="proj-results" class="proj-results"></div>
        </div>
        ${subPanelHtml()}
        <div class="panel" id="project-share"></div>
        <div class="panel">
          <h3>Delete Project</h3>
          <div class="hint" style="margin-top:0">Deleting removes the project only. Its entries stay in your library without the [${esc(p.tag)}] tag, and the ${esc(p.folder_path)} folder is left as it is.</div>
          <button class="btn btn-danger btn-small" id="proj-delete" style="margin-top:8px">Delete project</button>
        </div>
      </aside>
    </div>`;

  document.getElementById("back-projects").addEventListener("click", () => renderProjects());
  const nameEl = document.getElementById("proj-name");
  const descEl = document.getElementById("proj-desc");
  const saveRow = document.getElementById("proj-save-row");
  const changed = () => { saveRow.style.display = nameEl.value !== p.name || descEl.value !== (p.description || "") ? "" : "none"; };
  nameEl.addEventListener("input", changed);
  descEl.addEventListener("input", changed);
  document.getElementById("proj-cancel").addEventListener("click", () => renderProject());
  document.getElementById("proj-save").addEventListener("click", async () => {
    try {
      await projectPost("", { name: nameEl.value, description: descEl.value });
      state.projectsCache = [];
      toast("Project saved.");
      renderProject();
    } catch (err) { toast(err.message, true); }
  });
  document.getElementById("proj-delete").addEventListener("click", () => deleteProject(p, renderProjects));
  wireProjectTarget(renderProject);

  appEl.querySelectorAll("[data-open]").forEach((a) => a.addEventListener("click", (ev) => {
    ev.preventDefault();
    state.returnTo = { view: "project", id: p.id };
    state.view = "entries";
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === "entries"));
    openEntry(Number(a.dataset.open));
  }));
  const search = document.getElementById("proj-search");
  const results = document.getElementById("proj-results");
  let timer = null;
  const find = async () => {
    const q = search.value.trim();
    if (!q) { results.innerHTML = `<div class="hint">Type part of a title to find entries.</div>`; return; }
    const r = await api(`/api/entries?search=${encodeURIComponent(q)}&page_size=15`);
    const rows = r.rows.filter((e) => e.project_tag !== p.tag);
    results.innerHTML = rows.length ? rows.map((e) => `
      <div class="proj-result">
        <span><b>${esc(e.title)}</b> <span class="muted">${esc(e.top_folder)}${e.project_tag ? ` · in [${esc(e.project_tag)}]` : ""}</span></span>
        <button class="btn btn-small" data-add="${e.id}" ${e.project_tag ? 'title="Moves it out of its current project"' : ""}>Add</button>
      </div>`).join("") : `<div class="hint">No other entries match.</div>`;
    results.querySelectorAll("[data-add]").forEach((btn) => btn.addEventListener("click", async () => {
      try {
        const res = await projectPost("/entries", { add: [Number(btn.dataset.add)] });
        if (res.problems.length) toast(res.problems.join(" "), true);
        state.projectsCache = [];
        await renderProject();
        document.getElementById("proj-search").value = q;
        document.getElementById("proj-search").dispatchEvent(new Event("input"));
      } catch (err) { toast(err.message, true); }
    }));
  };
  search.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(find, 200); });
  find();
  renderProjectShare(p);
  renderSubPanel({ kind: "project", id: p.id, title: p.name });
  renderOutline(p);
}

// -------------------------------------------------------------------------
// DOCS VIEW
// -------------------------------------------------------------------------

async function renderDocs() {
  appEl.innerHTML = `<div class="empty-state">Loading...</div>`;
  const [howtos, docs] = await Promise.all([api("/api/howtos").catch(() => []), api("/api/docs")]);
  const items = howtos.map((h) => ({ kind: "howto", name: h.name, title: h.title }))
    .concat(docs.map((d) => ({ kind: "doc", name: d.name, title: d.title.replace(/^\d+\s*-\s*/, "") })));

  if (items.length === 0) {
    appEl.innerHTML = `<div class="empty-state">No help pages found in Minerva's docs/ folder.</div>`;
    return;
  }

  const navBtn = (d) => `<button class="btn btn-ghost docs-nav-btn" data-doc-kind="${d.kind}" data-doc="${esc(d.name)}">${esc(d.title)}</button>`;
  appEl.innerHTML = `
    <div class="docs-layout">
      <div class="docs-nav">
        ${howtos.length ? `<div class="docs-nav-head">How-tos</div>` : ""}
        ${items.filter((d) => d.kind === "howto").map(navBtn).join("")}
        <div class="docs-nav-head">Reference</div>
        ${items.filter((d) => d.kind === "doc").map(navBtn).join("")}
      </div>
      <div class="panel docs-content" id="docs-content">Loading...</div>
    </div>
  `;

  document.querySelectorAll(".docs-nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => loadDoc(btn.dataset.docKind, btn.dataset.doc));
  });

  const want = state.openDoc;
  state.openDoc = null;
  const first = (want && items.find((d) => d.kind === want.kind && d.name === want.name)) || items[0];
  await loadDoc(first.kind, first.name, want && first.name === want.name ? want.anchor : "");
}

async function loadDoc(kind, name, anchor) {
  document.querySelectorAll(".docs-nav-btn").forEach((b) =>
    b.classList.toggle("active", b.dataset.doc === name && b.dataset.docKind === kind));
  const el = document.getElementById("docs-content");
  el.textContent = "Loading...";
  el.classList.toggle("docs-text", kind === "doc");
  try {
    if (kind === "howto") {
      // how-tos are pages bundled with Minerva itself, not library content
      el.innerHTML = (await api(`/api/howtos/${encodeURIComponent(name)}`)).html;
    } else {
      el.textContent = (await api(`/api/docs/${encodeURIComponent(name)}`)).content;
    }
    el.scrollTop = 0;
    window.scrollTo(0, 0);
    scrollHelpTo(el, kind, anchor);
  } catch (err) {
    el.textContent = `Could not load ${name}: ${err.message}`;
  }
}

// Boot happens in onboarding.js: it shows first-run setup when no library
// is open yet, and otherwise calls startMinerva().

async function startMinerva() {
  document.getElementById("topbar").classList.remove("hidden");
  await setView("home");
  refreshAlertsBadge();
}
