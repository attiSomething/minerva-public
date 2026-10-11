// Submissions: where pieces were sent and how it went. Records belong to one
// entry or one project; the Submissions tab lists and filters all of them.

const subState = { options: null, mode: "submissions", filters: { open: false }, sort: { key: "submitted_on", dir: -1 } };

function postJson(path, body) {
  return api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
}

async function subOptions(refresh) {
  if (!subState.options || refresh) subState.options = await api("/api/submissions/options");
  return subState.options;
}

function statusBadge(s) {
  return `<span class="sub-status sub-${s.status.toLowerCase()}">${esc(s.status)}</span>`
    + (s.overdue ? ` <span class="sub-status sub-overdue" title="Past the expected response date">Overdue</span>` : "");
}

function money(amount, currency) {
  if (!amount) return "Free";
  return `${esc(currency || "$")}${Number(amount).toFixed(2).replace(/\.00$/, "")}`;
}

function feesText(fees) {
  const parts = Object.entries(fees || {}).map(([c, v]) => money(v, c));
  return parts.length ? parts.join(" + ") : "None";
}

// ---- the add/edit dialog ----------------------------------------------------

function closeSubDialog() {
  const el = document.getElementById("sub-dialog");
  if (el) el.remove();
  document.removeEventListener("keydown", subDialogKeys);
}

function subDialogKeys(ev) {
  if (ev.key === "Escape" && !document.getElementById("snippets-dialog")) closeSubDialog();
}

async function openSubDialog({ piece, sub, onDone }) {
  const opts = await subOptions();
  const snips = await loadSnippets().catch(() => ({ snippets: [] }));
  const s = sub || { status: "Submitted", currency: "$", submitted_on: new Date().toISOString().slice(0, 10) };
  closeSubDialog();
  const el = document.createElement("div");
  el.id = "sub-dialog";
  el.className = "modal-backdrop";
  subDialogState.piece = sub ? null : piece || null;
  subDialogState.venue = null;
  const pieceLabel = sub ? `${sub.title}${sub.missing ? " (no longer in the library)" : ""}` : piece ? piece.title : "";
  el.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="sub-dialog-title">
      <h2 id="sub-dialog-title">${sub ? "Edit submission" : "Add a submission"}</h2>
      ${pieceLabel ? `<div class="sub-piece">${esc(pieceLabel)}</div>` : `
        <div class="field-row"><label for="sub-piece-search">Entry or project</label>
          <input type="text" id="sub-piece-search" placeholder="Search titles..." autocomplete="off">
          <div id="sub-piece-results" class="proj-results"></div>
        </div>`}
      <div class="sub-form">
        <div class="field-row wide"><label for="sub-venue">Where</label>
          <input type="text" id="sub-venue" list="sub-venues" value="${esc(s.venue || "")}" placeholder="Magazine, press, contest...">
          <datalist id="sub-venues">${opts.venues.map((v) => `<option value="${esc(v)}">`).join("")}</datalist>
          <div class="hint" id="sub-venue-hint" style="margin:4px 0 0"></div></div>
        <div class="field-row"><label for="sub-status">Status</label>
          <select id="sub-status">${opts.statuses.map((x) => `<option ${x === s.status ? "selected" : ""}>${x}</option>`).join("")}</select></div>
        <div class="field-row"><label for="sub-submitted">Date submitted</label>
          <input type="date" id="sub-submitted" value="${esc(s.submitted_on || "")}"></div>
        <div class="field-row"><label for="sub-deadline">Deadline</label>
          <input type="date" id="sub-deadline" value="${esc(s.deadline || "")}"></div>
        <div class="field-row"><label for="sub-days">Expected response (days)</label>
          <input type="number" id="sub-days" min="0" step="1" value="${s.response_days ?? ""}" placeholder="e.g. 90"></div>
        <div class="field-row"><label for="sub-cost">Submission fee</label>
          <div class="sub-cost"><input type="text" id="sub-currency" value="${esc(s.currency || "$")}" aria-label="Currency" maxlength="4">
          <input type="number" id="sub-cost" min="0" step="0.01" value="${s.cost || ""}" placeholder="0"></div></div>
        <div class="field-row" id="sub-decided-row"><label for="sub-decided">Response date</label>
          <input type="date" id="sub-decided" value="${esc(s.decided_on || "")}"></div>
        <div class="field-row wide"><label for="sub-notes">Notes</label>
          <textarea id="sub-notes" rows="3" placeholder="Reading period, editor, simultaneous submission...">${esc(s.notes || "")}</textarea></div>
        ${snippetRowHtml(snips.snippets)}
      </div>
      <div class="modal-actions">
        ${sub ? `<button class="btn btn-ghost btn-small sub-delete" id="sub-delete">Delete record</button>` : ""}
        <span style="flex:1"></span>
        <button class="btn btn-ghost" id="sub-cancel">Cancel</button>
        <button class="btn btn-gold" id="sub-save">${sub ? "Save" : "Add submission"}</button>
      </div>
    </div>`;
  document.body.appendChild(el);
  document.addEventListener("keydown", subDialogKeys);
  el.addEventListener("click", (ev) => { if (ev.target === el) closeSubDialog(); });
  document.getElementById("sub-cancel").addEventListener("click", closeSubDialog);

  const refreshSnippetRow = async () => {
    const d = await loadSnippets(true).catch(() => null);
    const row = document.querySelector("#sub-dialog .snip-use");
    if (!d || !row) return;
    row.outerHTML = snippetRowHtml(d.snippets);
    wireSnippetRow(snippetContext, refreshSnippetRow);
  };
  const snippetContext = () => ({
    venue: document.getElementById("sub-venue").value.trim(),
    title: sub ? sub.title : subDialogState.piece ? subDialogState.piece.title : piece ? piece.title : "",
  });
  wireSnippetRow(snippetContext, refreshSnippetRow);

  const decidedRow = document.getElementById("sub-decided-row");
  const statusSel = document.getElementById("sub-status");
  const syncDecided = () => {
    const decided = ["Accepted", "Declined", "Withdrawn"].includes(statusSel.value);
    decidedRow.classList.toggle("hidden", !decided);
    const d = document.getElementById("sub-decided");
    if (decided && !d.value) d.value = new Date().toISOString().slice(0, 10);
  };
  statusSel.addEventListener("change", syncDecided);
  syncDecided();

  const venueInput = document.getElementById("sub-venue");
  let vt;
  venueInput.addEventListener("input", () => {
    clearTimeout(vt);
    vt = setTimeout(() => applyVenueToDialog(venueInput.value, !sub), 300);
  });
  if (s.venue) applyVenueToDialog(s.venue, false);

  let chosen = piece || null;
  const search = document.getElementById("sub-piece-search");
  if (search) {
    const results = document.getElementById("sub-piece-results");
    let t;
    search.addEventListener("input", () => {
      clearTimeout(t);
      t = setTimeout(async () => {
        const q = search.value.trim().toLowerCase();
        chosen = null;
        subDialogState.piece = null;
        checkLineLimit();
        if (!q) { results.innerHTML = ""; return; }
        const r = await api(`/api/entries?search=${encodeURIComponent(q)}&page_size=8`);
        const projects = opts.projects.filter((p) => p.name.toLowerCase().includes(q));
        results.innerHTML = projects.map((p) => `<button class="proj-result" data-kind="project" data-id="${p.id}" data-title="${esc(p.name)}">${esc(p.name)} <span class="muted">project</span></button>`).join("")
          + r.rows.map((e) => `<button class="proj-result" data-kind="entry" data-id="${e.id}" data-title="${esc(e.title)}">${esc(e.title)} <span class="muted">${esc(e.top_folder)}</span></button>`).join("")
          || `<div class="hint">Nothing matches.</div>`;
        results.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
          chosen = { kind: b.dataset.kind, id: Number(b.dataset.id), title: b.dataset.title };
          subDialogState.piece = chosen;
          checkLineLimit();
          search.value = chosen.title;
          results.innerHTML = "";
        }));
      }, 200);
    });
  }

  if (sub) {
    document.getElementById("sub-delete").addEventListener("click", async () => {
      if (!confirm(`Delete the record of "${sub.title}" at ${sub.venue}? This only removes Minerva's note; your writing isn't touched.`)) return;
      try {
        await postJson(`/api/submissions/${sub.id}/delete`);
        closeSubDialog();
        toast("Deleted.");
        if (onDone) onDone();
      } catch (e) { toast(e.message, true); }
    });
  }

  document.getElementById("sub-save").addEventListener("click", async () => {
    const val = (id) => document.getElementById(id).value;
    const body = {
      venue: val("sub-venue"), status: val("sub-status"), submitted_on: val("sub-submitted"),
      deadline: val("sub-deadline"), response_days: val("sub-days"), cost: val("sub-cost") || 0,
      currency: val("sub-currency"), notes: val("sub-notes"),
      decided_on: decidedRow.classList.contains("hidden") ? "" : val("sub-decided"),
    };
    try {
      let saved;
      if (sub) saved = await postJson(`/api/submissions/${sub.id}`, body);
      else {
        if (!chosen) throw new Error("Choose the entry or project you submitted.");
        body[chosen.kind === "entry" ? "entry_id" : "project_id"] = chosen.id;
        saved = await postJson("/api/submissions", body);
      }
      closeSubDialog();
      toast(sub ? "Saved." : "Submission added.");
      subOptions(true).catch(() => {});
      await offerPublished(saved, sub);
      await offerWithdrawOthers(saved, sub);
      if (onDone) onDone();
    } catch (e) { toast(e.message, true); }
  });
  (document.getElementById("sub-piece-search") || document.getElementById("sub-venue")).focus();
}

async function offerPublished(saved, before) {
  // an accepted piece is usually a published one; offer to set the flag
  if (saved.kind !== "entry" || saved.missing || saved.status !== "Accepted") return;
  if (before && before.status === "Accepted") return;
  const e = await api(`/api/entries/${saved.entry_id}`).catch(() => null);
  if (!e || e.published) return;
  if (!confirm(`Congratulations! Mark "${saved.title}" as published at ${saved.venue}?`)) return;
  await postJson(`/api/entries/${saved.entry_id}/flags`, { published: true, published_where: saved.venue });
  if (state.currentEntryId === saved.entry_id && document.getElementById("flag-published")) {
    document.getElementById("flag-published").checked = true;
    document.getElementById("published-where").value = saved.venue;
    document.getElementById("published-where-row").style.display = "";
  }
}

async function offerWithdrawOthers(saved, before) {
  // a piece accepted in one place is usually withdrawn from the others
  if (saved.status !== "Accepted" || (before && before.status === "Accepted")) return;
  const others = await api(`/api/submissions/${saved.id}/elsewhere`).catch(() => []);
  if (!others.length) return;
  await new Promise((resolve) => {
    closeSubDialog();
    const el = document.createElement("div");
    el.id = "sub-dialog";
    el.className = "modal-backdrop";
    el.innerHTML = `
      <div class="modal" role="dialog" aria-modal="true" aria-labelledby="withdraw-title">
        <h2 id="withdraw-title">Tell the other venues</h2>
        <div class="hint" style="margin-top:0">"${esc(saved.title)}" is still waiting at ${others.length === 1 ? "one other place" : `${others.length} other places`}. Most venues ask to hear when a simultaneous submission is taken elsewhere. Mark the ones you'll withdraw from:</div>
        <ul class="withdraw-list">${others.map((o) => `
          <li><label><input type="checkbox" value="${o.id}" checked>
            <span class="sub-mini-venue">${esc(o.venue)}</span>${statusBadge(o)}
            <span class="sub-mini-date">${o.submitted_on ? `sent ${shortDate(o.submitted_on)}` : ""}</span></label></li>`).join("")}</ul>
        <div class="modal-actions">
          <span style="flex:1"></span>
          <button class="btn btn-ghost" id="withdraw-skip">Not now</button>
          <button class="btn btn-gold" id="withdraw-go">Mark withdrawn</button>
        </div>
      </div>`;
    document.body.appendChild(el);
    const done = () => { document.removeEventListener("keydown", keys); el.remove(); resolve(); };
    const keys = (ev) => { if (ev.key === "Escape") done(); };
    document.addEventListener("keydown", keys);
    document.getElementById("withdraw-skip").addEventListener("click", done);
    document.getElementById("withdraw-go").addEventListener("click", async () => {
      const ids = [...el.querySelectorAll("input:checked")].map((c) => Number(c.value));
      try {
        if (ids.length) {
          const r = await postJson("/api/submissions/withdraw", { ids });
          toast(`Marked ${r.withdrawn.length} as withdrawn. Remember to let ${r.withdrawn.length === 1 ? "that venue" : "those venues"} know.`);
        }
        done();
      } catch (e) { toast(e.message, true); }
    });
    document.getElementById("withdraw-go").focus();
  });
}

// ---- the panel on an entry or a project page ---------------------------------

function subPanelHtml() {
  return `<div class="panel" id="sub-panel"><h3>Submissions</h3><div class="hint" style="margin-top:0">Loading...</div></div>`;
}

async function renderSubPanel(piece) {
  const el = document.getElementById("sub-panel");
  if (!el) return;
  const key = piece.kind === "entry" ? "entry_id" : "project_id";
  let data;
  try {
    data = await api(`/api/submissions?${key}=${piece.id}`);
  } catch (e) {
    el.innerHTML = `<h3>Submissions</h3><div class="hint">${esc(e.message)}</div>`;
    return;
  }
  el.innerHTML = `
    <h3>Submissions</h3>
    ${data.rows.length ? `<ul class="sub-mini">${data.rows.map((s) => `
      <li><button class="sub-mini-row" data-sub="${s.id}">
        <span class="sub-mini-venue">${esc(s.venue)}</span>${statusBadge(s)}
        <span class="sub-mini-date">${s.submitted_on ? shortDate(s.submitted_on) : s.deadline ? `due ${shortDate(s.deadline)}` : ""}</span>
      </button></li>`).join("")}</ul>` : `<div class="hint" style="margin-top:0">Not submitted anywhere yet.</div>`}
    <button class="btn btn-small" id="sub-add" style="margin-top:8px">Add submission</button>
    <button class="btn btn-small btn-ghost" id="sub-research" style="margin-top:8px" title="Your venues that fit, and new places to try">Find places to send it</button>`;
  const refresh = () => renderSubPanel(piece);
  document.getElementById("sub-research").addEventListener("click", () => openResearch(piece));
  document.getElementById("sub-add").addEventListener("click", () => openSubDialog({ piece, onDone: refresh }));
  el.querySelectorAll("[data-sub]").forEach((b) => b.addEventListener("click", () =>
    openSubDialog({ sub: data.rows.find((s) => s.id === Number(b.dataset.sub)), onDone: refresh })));
}

// ---- the Submissions tab ------------------------------------------------------

function subFilterValues() {
  const f = subState.filters;
  const params = new URLSearchParams();
  for (const k of ["q", "status", "venue", "category", "project", "kind", "date_from", "date_to"]) if (f[k]) params.set(k, f[k]);
  if (f.open) params.set("open", "1");
  return params.toString();
}

function sortRows(rows) {
  const { key, dir } = subState.sort;
  const v = (r) => (key === "cost" ? Number(r.cost || 0) : (r[key] || "").toString().toLowerCase());
  return rows.slice().sort((a, b) => (v(a) < v(b) ? -1 : v(a) > v(b) ? 1 : 0) * dir);
}

function subsModeHtml() {
  return `<div class="seg" role="group" aria-label="Show">
    ${[["submissions", "Submissions"], ["venues", "Venues"]].map(([m, label]) =>
      `<button class="seg-btn ${subState.mode === m ? "active" : ""}" data-subs-mode="${m}" aria-pressed="${subState.mode === m}">${label}</button>`).join("")}
  </div>`;
}

function wireSubsMode() {
  document.querySelectorAll("[data-subs-mode]").forEach((b) => b.addEventListener("click", () => {
    if (subState.mode === b.dataset.subsMode) return;
    subState.mode = b.dataset.subsMode;
    renderSubmissions();
  }));
}

async function renderVenues() {
  appEl.innerHTML = `
    <div class="subs">
      <div class="subs-head">
        <h1>Venues</h1>
        ${helpLinkHtml("venues")}
        <span class="spacer"></span>
        ${subsModeHtml()}
        <button class="btn btn-gold" id="venue-add">Add venue</button>
      </div>
      <div class="hint">Notes on the places you send work: reading periods, fees and how long they take. Choosing a venue when you add a submission fills in its fee and expected response.</div>
      <div class="panel" id="venue-table"><div class="empty-state">Loading...</div></div>
    </div>`;
  wireSubsMode();
  const table = document.getElementById("venue-table");
  document.getElementById("venue-add").addEventListener("click", () => openVenueDialog(null, () => renderVenueList(table)));
  await renderVenueList(table);
}

async function renderSubmissions() {
  if (subState.mode === "venues") return renderVenues();
  appEl.innerHTML = `<div class="empty-state">Loading...</div>`;
  const opts = await subOptions(true);
  const f = subState.filters;
  const sel = (id, label, values, current) => `<select id="${id}" aria-label="${label}"><option value="">${label}: all</option>${values.map(([v, t]) => `<option value="${esc(v)}" ${v === current ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>`;
  appEl.innerHTML = `
    <div class="subs">
      <div class="subs-head">
        <h1>Submissions</h1>
        ${helpLinkHtml("submissions")}
        <span class="spacer"></span>
        ${subsModeHtml()}
        <button class="btn btn-ghost" id="subs-import">Import...</button>
        <button class="btn btn-ghost" id="subs-snippets" title="Cover letters, bios and acknowledgments">Snippets</button>
        <button class="btn btn-gold" id="subs-add">Add submission</button>
      </div>
      <div id="subs-summary" class="stat-tiles subs-tiles"></div>
      <div class="panel subs-filters">
        <input type="search" id="sf-q" placeholder="Search title, where, notes..." value="${esc(f.q || "")}">
        ${sel("sf-status", "Status", opts.statuses.map((s) => [s, s]), f.status)}
        ${sel("sf-venue", "Where", opts.venues.map((v) => [v, v]), f.venue)}
        ${sel("sf-category", "Category", opts.categories.map((c) => [c, c]), f.category)}
        ${sel("sf-project", "Project", opts.projects.map((p) => [p.tag, p.name]), f.project)}
        ${sel("sf-kind", "Type", [["entry", "Entries"], ["project", "Projects"]], f.kind)}
        <label class="subs-date">From <input type="date" id="sf-from" value="${esc(f.date_from || "")}"></label>
        <label class="subs-date">To <input type="date" id="sf-to" value="${esc(f.date_to || "")}"></label>
        <label class="filter-check"><input type="checkbox" id="sf-open" ${f.open ? "checked" : ""}> Still waiting</label>
        <button class="btn btn-ghost btn-small" id="sf-clear">Clear</button>
      </div>
      <div class="panel" id="subs-table"></div>
    </div>`;

  wireSubsMode();
  const bind = (id, key, ev = "change") => document.getElementById(id).addEventListener(ev, (e) => {
    f[key] = e.target.type === "checkbox" ? e.target.checked : e.target.value;
    loadSubmissionsTable();
  });
  bind("sf-status", "status"); bind("sf-venue", "venue"); bind("sf-category", "category");
  bind("sf-project", "project"); bind("sf-kind", "kind"); bind("sf-from", "date_from"); bind("sf-to", "date_to");
  bind("sf-open", "open");
  let t;
  document.getElementById("sf-q").addEventListener("input", (e) => {
    clearTimeout(t);
    t = setTimeout(() => { f.q = e.target.value.trim(); loadSubmissionsTable(); }, 250);
  });
  document.getElementById("sf-clear").addEventListener("click", () => { subState.filters = { open: false }; renderSubmissions(); });
  document.getElementById("subs-add").addEventListener("click", () => openSubDialog({ onDone: loadSubmissionsTable }));
  document.getElementById("subs-import").addEventListener("click", () => openImportDialog(renderSubmissions));
  document.getElementById("subs-snippets").addEventListener("click", () => openSnippets());
  await loadSubmissionsTable();
}

async function loadSubmissionsTable() {
  const el = document.getElementById("subs-table");
  if (!el) return;
  let data;
  try {
    data = await api(`/api/submissions?${subFilterValues()}`);
  } catch (e) {
    el.innerHTML = `<div class="empty-state">${esc(e.message)}</div>`;
    return;
  }
  const s = data.summary;
  document.getElementById("subs-summary").innerHTML =
    tile("Shown", s.count.toLocaleString(), plural(s.count, "submission", "submissions"))
    + tile("Waiting", s.waiting.toLocaleString(), s.overdue ? `${s.overdue} past expected reply` : "None overdue", s.overdue ? "gold" : "")
    + tile("Accepted", s.accepted.toLocaleString(), s.acceptance_rate === null ? "No replies yet" : `${Math.round(s.acceptance_rate * 100)}% of replies`)
    + tile("Fees", feesText(s.fees), "for the submissions shown");

  if (!data.rows.length) {
    const any = subFilterValues();
    el.innerHTML = any ? `<div class="empty-state">No submissions match these filters.</div>` : `
      <div class="empty-state empty-action">
        <p>No submissions yet. Add one here or from an entry's Submissions panel, or bring in the spreadsheet you already keep.</p>
        <div class="scan-links">
          <button class="btn btn-gold btn-small" id="subs-empty-add">Add a submission</button>
          <button class="btn btn-ghost btn-small" id="subs-empty-import">Import a spreadsheet</button>
        </div>
      </div>`;
    if (!any) {
      document.getElementById("subs-empty-add").addEventListener("click", () => openSubDialog({ onDone: loadSubmissionsTable }));
      document.getElementById("subs-empty-import").addEventListener("click", () => openImportDialog(renderSubmissions));
    }
    return;
  }
  const cols = [["title", "Piece"], ["venue", "Where"], ["submitted_on", "Submitted"], ["deadline", "Deadline"],
    ["expected_by", "Expected by"], ["cost", "Fee"], ["status", "Status"]];
  const { key, dir } = subState.sort;
  el.innerHTML = `
    <div class="table-scroll"><table class="entry-table subs-table">
      <thead><tr>${cols.map(([k, label]) => `<th><button class="th-sort" data-sort="${k}" aria-sort="${k === key ? (dir > 0 ? "ascending" : "descending") : "none"}">${label}${k === key ? (dir > 0 ? " ▲" : " ▼") : ""}</button></th>`).join("")}</tr></thead>
      <tbody>${sortRows(data.rows).map((r) => `
        <tr data-sub="${r.id}" class="${r.overdue ? "overdue" : ""}">
          <td><a href="#" data-piece="${r.kind}:${r.kind === "entry" ? r.entry_id : r.project_id}" ${r.missing ? 'class="missing" title="No longer in the library"' : ""}>${esc(r.title)}</a>
            <div class="recent-meta">${r.kind === "project" ? "Project" : esc(r.category || "")}${r.project && r.kind === "entry" ? ` · [${esc(r.project)}]` : ""}</div></td>
          <td>${esc(r.venue)}</td>
          <td>${r.submitted_on ? shortDate(r.submitted_on) : "—"}</td>
          <td>${r.deadline ? shortDate(r.deadline) : "—"}</td>
          <td>${r.expected_by ? shortDate(r.expected_by) : "—"}</td>
          <td>${money(r.cost, r.currency)}</td>
          <td>${statusBadge(r)}</td>
        </tr>`).join("")}</tbody>
    </table></div>`;
  el.querySelectorAll(".th-sort").forEach((b) => b.addEventListener("click", () => {
    subState.sort = { key: b.dataset.sort, dir: subState.sort.key === b.dataset.sort ? -subState.sort.dir : 1 };
    loadSubmissionsTable();
  }));
  el.querySelectorAll("tr[data-sub]").forEach((tr) => tr.addEventListener("click", (ev) => {
    if (ev.target.closest("a")) return;
    openSubDialog({ sub: data.rows.find((r) => r.id === Number(tr.dataset.sub)), onDone: loadSubmissionsTable });
  }));
  el.querySelectorAll("[data-piece]").forEach((a) => a.addEventListener("click", (ev) => {
    ev.preventDefault();
    if (a.classList.contains("missing")) { toast("That piece is no longer in the library.", true); return; }
    const [kind, id] = a.dataset.piece.split(":");
    if (kind === "entry") {
      state.view = "entries";
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === "entries"));
      state.returnTo = { view: "submissions" };
      openEntry(Number(id));
    } else {
      state.view = "projects";
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === "projects"));
      openProject(Number(id));
    }
  }));
}

// ---- importing a spreadsheet ------------------------------------------------
// The writer chooses a CSV file; Minerva guesses which column is which, then
// previews every row before anything is saved. Rows whose piece wasn't found
// can be matched by hand or skipped. Nothing is dropped silently: the result
// lists every row that wasn't imported, with the reason.

const importState = { text: "", name: "", plan: null, mapping: null, dayFirst: false, overrides: {}, source: null, emails: null };
const IMPORT_STATES = {
  ready: "Ready", update: "Will update", unmatched: "Needs a match", problem: "Problem", duplicate: "Already recorded",
  skipped: "Skipped", imported: "Imported", updated: "Updated",
};

function closeImportDialog() {
  const el = document.getElementById("import-dialog");
  if (el) el.remove();
  document.removeEventListener("keydown", importDialogKeys);
}

function importDialogKeys(ev) {
  if (ev.key === "Escape" && !document.querySelector("#import-dialog .import-match input:focus")) closeImportDialog();
}

function openImportDialog(onDone) {
  closeImportDialog();
  Object.assign(importState, { text: "", name: "", plan: null, mapping: null, dayFirst: false, overrides: {}, source: null, emails: null });
  const el = document.createElement("div");
  el.id = "import-dialog";
  el.className = "modal-backdrop";
  el.innerHTML = `
    <div class="modal modal-wide" role="dialog" aria-modal="true" aria-labelledby="import-title">
      <h2 id="import-title">Import submissions</h2>
      <p class="hint">Bring in the submission records you kept in a spreadsheet, an export from Submittable or The Grinder, or the confirmation and decision emails those services send (an .mbox mailbox or .eml files). Save a spreadsheet as CSV first: in Excel use File &gt; Save As &gt; CSV, in Google Sheets File &gt; Download &gt; CSV. You'll see every row before anything is saved, and your file isn't changed. Importing a newer export later updates statuses and response dates. ${helpLinkHtml("sub-import", "Getting your history out of Submittable or The Grinder")}</p>
      <div class="field-row"><label for="import-file">Spreadsheet (CSV) or emails</label>
        <input type="file" id="import-file" multiple accept=".csv,.txt,.tsv,text/csv,.mbox,.eml,message/rfc822"></div>
      <div id="import-body"></div>
      <div class="modal-actions">
        <span class="muted" id="import-summary"></span>
        <span style="flex:1"></span>
        <button class="btn btn-ghost" id="import-cancel">Cancel</button>
        <button class="btn btn-gold" id="import-go" disabled>Import</button>
      </div>
    </div>`;
  document.body.appendChild(el);
  document.addEventListener("keydown", importDialogKeys);
  const finish = () => { closeImportDialog(); if (onDone) onDone(); };
  document.getElementById("import-cancel").addEventListener("click", closeImportDialog);
  document.getElementById("import-file").addEventListener("change", async (ev) => {
    const files = [...ev.target.files];
    if (!files.length) return;
    importState.mapping = null;
    importState.overrides = {};
    importState.source = null;
    importState.emails = null;
    if (files.some((f) => /\.(mbox|eml)$/i.test(f.name))) {
      const form = new FormData();
      files.forEach((f) => form.append("files", f, f.name));
      document.getElementById("import-body").innerHTML = `<div class="empty-state">Reading emails...</div>`;
      try {
        importState.emails = await api("/api/submissions/import/emails", { method: "POST", body: form });
      } catch (e) {
        document.getElementById("import-body").innerHTML = `<div class="empty-state">${esc(e.message)}</div>`;
        return;
      }
      if (!importState.emails.used) {
        document.getElementById("import-body").innerHTML = `<div class="empty-state">${emailsFoundText(importState.emails)}</div>`;
        return;
      }
      importState.text = importState.emails.text;
      importState.name = "emails";
      importState.source = "";
    } else {
      const file = files[0];
      if (file.size > 5 * 1024 * 1024) { toast("That file is too large for a submissions list.", true); return; }
      importState.text = await file.text();
      importState.name = file.name;
    }
    await refreshImportPlan();
  });
  document.getElementById("import-go").addEventListener("click", async () => {
    const go = document.getElementById("import-go");
    go.disabled = true;
    try {
      const r = await postJson("/api/submissions/import", importBody());
      showImportResult(r, finish);
    } catch (e) {
      go.disabled = false;
      toast(e.message, true);
    }
  });
  document.getElementById("import-file").focus();
}

function importBody() {
  return { text: importState.text, name: importState.name, mapping: importState.mapping, day_first: importState.dayFirst,
    overrides: importState.overrides, source: importState.source };
}

async function refreshImportPlan() {
  const body = document.getElementById("import-body");
  try {
    importState.plan = await postJson("/api/submissions/import/preview", importBody());
  } catch (e) {
    importState.plan = null;
    body.innerHTML = `<div class="empty-state">${esc(e.message)}</div>`;
    document.getElementById("import-go").disabled = true;
    document.getElementById("import-summary").textContent = "";
    return;
  }
  importState.mapping = importState.plan.mapping;
  importState.source = importState.plan.source || "";
  renderImportPlan();
}

function importCountsText(counts) {
  const parts = [];
  const add = (k, one, many) => { if (counts[k]) parts.push(`${counts[k]} ${counts[k] === 1 ? one : many}`); };
  add("ready", "ready", "ready");
  add("update", "updates a record", "update records");
  add("unmatched", "needs a match", "need a match");
  add("problem", "has a problem", "have a problem");
  add("duplicate", "already recorded", "already recorded");
  add("skipped", "skipped", "skipped");
  return parts.join(" · ");
}

function renderImportPlan() {
  const p = importState.plan;
  const body = document.getElementById("import-body");
  const mapped = new Set(Object.values(p.mapping).map(Number));
  const colOptions = (field) => `<option value="">Not in this file</option>` + p.headings.map((h, i) =>
    `<option value="${i}" ${p.mapping[field] === i ? "selected" : ""}>${esc(h || `Column ${i + 1}`)}</option>`).join("");
  const unused = p.headings.filter((_, i) => !mapped.has(i));
  body.innerHTML = importState.emails ? `<p class="hint">${emailsFoundText(importState.emails)}</p>
    <h3 class="import-h">Rows</h3>
    <div class="import-rows"><table class="entry-table import-table">
      <thead><tr><th>Row</th><th>Piece</th><th>Where</th><th>Sent</th><th>Status</th><th>What happens</th><th></th></tr></thead>
      <tbody>${p.rows.map(importRowHtml).join("")}</tbody>
    </table></div>` : `
    <label class="import-source">This file is from
      <select id="import-source">${(p.sources || []).map((s) => `<option value="${esc(s.id)}" ${s.id === (p.source || "") ? "selected" : ""}>${esc(s.label)}</option>`).join("")}</select>
    </label>
    <h3 class="import-h">Which column holds what</h3>
    <div class="import-map">
      ${p.fields.map((f) => `<label><span>${esc(f.label)}${["piece", "venue"].includes(f.id) ? ` <span class="muted">(needed)</span>` : ""}</span>
        <select data-field="${f.id}">${colOptions(f.id)}</select></label>`).join("")}
    </div>
    <label class="filter-check"><input type="checkbox" id="import-dayfirst" ${importState.dayFirst ? "checked" : ""}> Dates are written day first (31/12/2024)</label>
    ${unused.length ? `<div class="hint">Not imported: ${unused.map((h) => esc(h || "a blank heading")).join(", ")}.</div>` : ""}
    ${p.needs_mapping ? `<div class="empty-state">Choose the columns that hold the piece's title and where it was sent.</div>` : `
    <h3 class="import-h">Rows</h3>
    <div class="import-rows"><table class="entry-table import-table">
      <thead><tr><th>Row</th><th>Piece</th><th>Where</th><th>Sent</th><th>Status</th><th>What happens</th><th></th></tr></thead>
      <tbody>${p.rows.map(importRowHtml).join("")}</tbody>
    </table></div>`}`;
  body.querySelectorAll("[data-field]").forEach((sel) => sel.addEventListener("change", () => {
    const m = { ...importState.mapping };
    if (sel.value === "") delete m[sel.dataset.field];
    else {
      // a column holds one thing
      Object.keys(m).forEach((k) => { if (m[k] === Number(sel.value)) delete m[k]; });
      m[sel.dataset.field] = Number(sel.value);
    }
    importState.mapping = m;
    refreshImportPlan();
  }));
  if (!importState.emails) document.getElementById("import-source").addEventListener("change", (ev) => {
    importState.source = ev.target.value;
    importState.mapping = null;  // guess again with that service's headings
    refreshImportPlan();
  });
  if (!importState.emails) document.getElementById("import-dayfirst").addEventListener("change", (ev) => { importState.dayFirst = ev.target.checked; refreshImportPlan(); });
  body.querySelectorAll("[data-skip]").forEach((b) => b.addEventListener("click", () => {
    importState.overrides[b.dataset.skip] = { skip: true };
    refreshImportPlan();
  }));
  body.querySelectorAll("[data-unskip]").forEach((b) => b.addEventListener("click", () => {
    delete importState.overrides[b.dataset.unskip];
    refreshImportPlan();
  }));
  body.querySelectorAll("[data-match]").forEach((b) => b.addEventListener("click", () => openImportMatch(b)));
  const ready = (p.counts && p.counts.ready) || 0;
  const updates = (p.counts && p.counts.update) || 0;
  const go = document.getElementById("import-go");
  go.disabled = !ready && !updates;
  go.textContent = ready && updates ? `Import ${ready} and update ${updates}`
    : ready ? `Import ${ready} ${ready === 1 ? "submission" : "submissions"}`
    : updates ? `Update ${updates} ${updates === 1 ? "submission" : "submissions"}` : "Import";
  document.getElementById("import-summary").textContent = p.needs_mapping ? "" : importCountsText(p.counts || {});
}

function emailsFoundText(e) {
  const read = plural(e.emails, "email", "emails");
  if (!e.used) return `Read ${read}, and none of them was a submission confirmation or decision from Submittable, Moksha, Duosuma or Chill Subs.`;
  return `Read ${read}: ${plural(e.used, "submission", "submissions")} found${e.skipped_count ? `, and ${plural(e.skipped_count, "email", "emails")} from a submission manager that didn't say a piece was received or decided` : ""}. Rows whose piece couldn't be told need a match.`;
}

function importRowHtml(r) {
  const rec = r.record || {};
  const piece = r.piece ? `${esc(r.piece.title)}${r.piece.kind === "project" ? ` <span class="muted">project</span>` : ""}`
    : `<span class="muted">${esc(r.title || "(blank)")}</span>`;
  const matchable = r.state !== "skipped" && r.state !== "duplicate";
  const actions = r.state === "skipped" ? `<button class="btn btn-ghost btn-small" data-unskip="${r.row}">Undo</button>`
    : `${matchable ? `<button class="btn btn-ghost btn-small" data-match="${r.row}" data-title="${esc(r.title)}">${r.piece ? "Change" : "Match"}</button>` : ""}
       ${r.state !== "duplicate" ? `<button class="btn btn-ghost btn-small" data-skip="${r.row}">Skip</button>` : ""}`;
  return `<tr class="import-${r.state}" data-row="${r.row}">
    <td>${r.row}</td><td>${piece}</td><td>${esc(r.venue)}</td><td>${esc(rec.submitted_on || "")}</td><td>${esc(rec.status || "")}</td>
    <td><span class="import-state">${IMPORT_STATES[r.state] || esc(r.state)}</span>${r.reason ? `<div class="hint">${esc(r.reason)}</div>` : ""}</td>
    <td class="import-actions">${actions}</td></tr>`;
}

// Match a row to an entry or project by hand.
function openImportMatch(btn) {
  document.querySelectorAll("#import-dialog .import-match").forEach((x) => x.remove());
  const row = btn.dataset.match;
  const tr = btn.closest("tr");
  const box = document.createElement("tr");
  box.className = "import-match";
  box.innerHTML = `<td></td><td colspan="6">
    <input type="text" placeholder="Search titles..." autocomplete="off" aria-label="Entry or project for row ${row}" value="${esc(btn.dataset.title)}">
    <div class="proj-results"></div></td>`;
  tr.after(box);
  const input = box.querySelector("input");
  const results = box.querySelector(".proj-results");
  let t;
  const look = async () => {
    const q = input.value.trim().toLowerCase();
    if (!q) { results.innerHTML = ""; return; }
    const opts = await subOptions();
    const r = await api(`/api/entries?search=${encodeURIComponent(q)}&page_size=8`);
    const projects = opts.projects.filter((p) => p.name.toLowerCase().includes(q));
    results.innerHTML = projects.map((p) => `<button class="proj-result" data-kind="project" data-id="${p.id}">${esc(p.name)} <span class="muted">project</span></button>`).join("")
      + r.rows.map((e) => `<button class="proj-result" data-kind="entry" data-id="${e.id}">${esc(e.title)} <span class="muted">${esc(e.top_folder)}</span></button>`).join("")
      || `<div class="hint">Nothing matches. Try fewer words.</div>`;
    results.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
      importState.overrides[row] = { kind: b.dataset.kind, id: Number(b.dataset.id) };
      refreshImportPlan();
    }));
  };
  input.addEventListener("input", () => { clearTimeout(t); t = setTimeout(look, 200); });
  input.addEventListener("keydown", (ev) => { if (ev.key === "Escape") { ev.stopPropagation(); box.remove(); } });
  input.focus();
  input.select();
  look();
}

function showImportResult(r, finish) {
  const left = r.not_imported || [];
  document.getElementById("import-body").innerHTML = `
    <div class="import-done">
      <p><strong>${r.imported || r.updated ? [r.imported ? `Imported ${r.imported} ${r.imported === 1 ? "submission" : "submissions"}` : "",
        r.updated ? `updated ${r.updated} already in Minerva` : ""].filter(Boolean).join(" and ").replace(/^u/, "U") + "." : "Nothing was imported."}</strong></p>
      ${left.length ? `<p>${left.length === 1 ? "This row wasn't" : `These ${left.length} rows weren't`} imported:</p>
        <div class="import-rows"><table class="entry-table import-table"><thead><tr><th>Row</th><th>Piece</th><th>Where</th><th>Why</th></tr></thead><tbody>
        ${left.map((x) => `<tr><td>${x.row}</td><td>${esc(x.piece ? x.piece.title : x.title || "(blank)")}</td><td>${esc(x.venue)}</td><td>${esc(x.reason || IMPORT_STATES[x.state] || "")}</td></tr>`).join("")}
        </tbody></table></div>
        <p class="hint">${importState.emails ? "Rows whose piece or venue couldn't be told can be added by hand with Add submission. Importing the same emails again is safe:" : "You can fix those rows in the spreadsheet and import the file again:"} rows already in Minerva are recognized, and only a newer status or response date is taken from them.</p>` : ""}
    </div>`;
  document.querySelector("#import-dialog .field-row").remove();
  document.getElementById("import-summary").textContent = "";
  document.getElementById("import-cancel").remove();
  const go = document.getElementById("import-go");
  go.textContent = "Done";
  go.disabled = false;
  go.replaceWith(go.cloneNode(true));
  document.getElementById("import-go").addEventListener("click", finish);
  document.getElementById("import-dialog").addEventListener("click", (ev) => { if (ev.target.id === "import-dialog") finish(); });
  subOptions(true).catch(() => {});
}
