// Views: generated overviews of the library, in their own tab. Timeline lists
// the scanned journals in date order and every entry by year; a journal can
// be summarized by the organizing model when asked.

const VIEW_PANES = [["timeline", "Timeline"], ["histories", "People histories"]];
const viewsState = { pane: "timeline", by: "journal", data: null, openYears: new Set(), timer: null, person: null, people: [], filter: "" };

function viewPanesHtml(active) {
  return `<div class="entry-panes" role="tablist" aria-label="Views">
    ${VIEW_PANES.map(([v, label]) => `<button class="entry-pane ${v === active ? "active" : ""}" role="tab" aria-selected="${v === active}" data-view-pane="${v}">${label}</button>`).join("")}
    <span class="spacer"></span>
    ${helpLinkHtml("views")}
  </div>`;
}

async function renderViews() {
  clearTimeout(viewsState.timer);
  if (viewsState.pane === "timeline") await renderTimeline();
  else await renderHistories();
}

function wireViewPanes() {
  appEl.querySelectorAll("[data-view-pane]").forEach((b) => b.addEventListener("click", () => {
    if (b.classList.contains("active")) return;
    viewsState.pane = b.dataset.viewPane;
    renderViews();
  }));
}

async function renderTimeline() {
  appEl.innerHTML = `${viewPanesHtml("timeline")}<div id="tl-body"><div class="empty-state">Loading...</div></div>`;
  wireViewPanes();
  try { viewsState.data = await api("/api/views/timeline"); }
  catch (e) { document.getElementById("tl-body").innerHTML = `<div class="empty-state">${esc(e.message)}</div>`; return; }
  drawTimeline();
  const [job] = viewsState.data.jobs;
  if (job) pollSummaryJob(job.id);
}

function tlRange(a, b) {
  if (!a) return "Undated";
  return a === b ? dayDate(a) : `${dayDate(a)} – ${dayDate(b)}`;
}

function chips(counts) {
  return Object.entries(counts).map(([c, n]) => `<span class="tl-chip">${n} ${esc(c)}</span>`).join("");
}

function drawTimeline() {
  const body = document.getElementById("tl-body");
  const { journals, years } = viewsState.data;
  const by = viewsState.by;
  body.innerHTML = `
    <div class="tl-toolbar">
      <div class="seg" role="group" aria-label="Group by">
        ${[["journal", "By journal"], ["year", "By year"]].map(([m, l]) => `<button class="seg-btn ${by === m ? "active" : ""}" aria-pressed="${by === m}" data-by="${m}">${l}</button>`).join("")}
      </div>
      <span id="tl-saved" class="recent-meta"></span>
      <button class="btn" id="tl-save">Save as text</button>
    </div>
    <div id="tl-job"></div>
    ${by === "journal" ? journalsHtml(journals) : yearsHtml(years)}`;
  body.querySelectorAll("[data-by]").forEach((b) => b.addEventListener("click", () => { viewsState.by = b.dataset.by; drawTimeline(); }));
  document.getElementById("tl-save").addEventListener("click", saveTimeline);
  wireEmptyActions(body);
  body.querySelectorAll("[data-summarize]").forEach((b) => b.addEventListener("click", () => summarizeJournal(b.dataset.summarize)));
  body.querySelectorAll("[data-year]").forEach((b) => b.addEventListener("click", () => {
    const y = b.dataset.year;
    if (viewsState.openYears.has(y)) viewsState.openYears.delete(y); else viewsState.openYears.add(y);
    drawTimeline();
  }));
  body.querySelectorAll("[data-entry]").forEach((b) => b.addEventListener("click", () => {
    state.returnTo = { view: "views" };
    openEntry(Number(b.dataset.entry));
  }));
}

function journalsHtml(journals) {
  if (!journals.length) return `<div class="empty-state">No scanned journals yet. Each one shows here once it has a Master; switch to By year to see the whole library.</div>`;
  return `<ol class="tl-list">${journals.map((j) => `
    <li class="tl-item">
      <div class="tl-when">${tlRange(j.first, j.last)}</div>
      <div class="tl-card">
        <div class="tl-head"><h3>${esc(j.name)}</h3>
          <button class="btn btn-small btn-ghost" data-summarize="${esc(j.name)}">${j.notes ? "Summarize again" : "Summarize"}</button></div>
        <div class="recent-meta">${j.entries} entries${j.dated < j.entries ? ` (${j.dated} dated)` : ""}</div>
        ${Object.keys(j.filed).length ? `<div class="tl-chips">Filed: ${chips(j.filed)}</div>` : ""}
        ${j.people.length ? `<div class="tl-line">Mentions most: ${j.people.map(esc).join(", ")}</div>` : ""}
        ${j.notes ? notesHtml(j) : ""}
      </div>
    </li>`).join("")}</ol>`;
}

function notesHtml(j) {
  const parts = [["events", "Events"], ["themes", "Themes"], ["places", "Places"], ["people", "People"], ["projects", "Projects"]]
    .filter(([k]) => (j.notes[k] || []).length);
  return `${j.notes_current ? "" : `<div class="hint warn">The journal changed since this was summarized.</div>`}
    <div class="tl-notes">${parts.map(([k, label]) => `
      <div><h4>${label}</h4><ul>${j.notes[k].map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>`).join("")}</div>`;
}

function yearsHtml(years) {
  if (!years.length) return emptyLibraryHtml();
  return `<ol class="tl-list">${years.map((y) => {
    const open = viewsState.openYears.has(y.year);
    return `<li class="tl-item">
      <div class="tl-when">${esc(y.year)}</div>
      <div class="tl-card">
        <div class="tl-head"><button class="link-btn tl-year" data-year="${esc(y.year)}" aria-expanded="${open}">${y.count} ${y.count === 1 ? "entry" : "entries"}, ${y.words.toLocaleString()} words</button></div>
        <div class="tl-chips">${chips(y.categories)}</div>
        ${open ? `<ul class="tl-entries">${y.entries.map((e) => `
          <li><span class="recent-meta">${e.date ? dayDate(e.date) : "—"}</span>
            <button class="link-btn" data-entry="${e.id}">${esc(e.title)}</button>
            <span class="recent-meta">${esc(e.category)}${e.journal ? ` · ${esc(e.journal)}` : ""}</span></li>`).join("")}</ul>` : ""}
      </div>
    </li>`;
  }).join("")}</ol>`;
}

async function saveTimeline() {
  try {
    const r = await postJson("/api/views/timeline/save");
    document.getElementById("tl-saved").textContent = `Saved to ${r.path}`;
    toast("Timeline saved.");
  } catch (e) { toast(e.message, true); }
}

async function summarizeJournal(source) {
  let est;
  try { est = await postJson("/api/views/timeline/estimate", { source }); } catch (e) { toast(e.message, true); return; }
  const price = est.cost === null ? "" : est.cost < 0.01 ? ", under 1 cent at list price" : `, about $${est.cost.toFixed(2)} at list price`;
  if (!await aiConfirm(`Summarize ${source}? Its ${est.entries} entries go to your organizing model as text, about ${est.input_tokens.toLocaleString()} tokens${price}.`)) return;
  try {
    const job = await postJson("/api/views/timeline/summarize", { source });
    pollSummaryJob(job.id);
  } catch (e) { toast(e.message, true); }
}

async function pollSummaryJob(id) {
  clearTimeout(viewsState.timer);
  const box = document.getElementById("tl-job");
  if (!box) return;
  let j;
  try { j = await api(`/api/jobs/${id}`); } catch (e) { return; }
  document.querySelectorAll("[data-summarize]").forEach((b) => { b.disabled = j.status === "running"; });
  if (j.status === "running") {
    box.innerHTML = `<div class="job-box"><div class="job-head"><b>Summarizing</b> ${esc(j.label)}</div>
      <div class="progress"><div style="width:${j.total ? Math.round((100 * j.done) / j.total) : 5}%"></div></div>
      <div class="hint">${esc(j.message || "Waiting for the model...")}</div></div>`;
    viewsState.timer = setTimeout(() => pollSummaryJob(id), 1500);
    return;
  }
  if (j.status === "done") toast(`Summarized ${j.label}.`);
  else if (j.status === "failed") toast(j.error || "The summary stopped with an error.", true);
  await renderTimeline();
}

// ---- People histories ---------------------------------------------------------

async function renderHistories() {
  appEl.innerHTML = `${viewPanesHtml("histories")}<div id="hist-body"><div class="empty-state">Loading...</div></div>`;
  wireViewPanes();
  try { viewsState.people = await api("/api/views/people"); }
  catch (e) { document.getElementById("hist-body").innerHTML = `<div class="empty-state">${esc(e.message)}</div>`; return; }
  const list = viewsState.people;
  if (!list.length) {
    document.getElementById("hist-body").innerHTML = `<div class="empty-state">No one here yet. People histories come from the People list: open Entries, then People, and find the people in a journal.</div>`;
    return;
  }
  if (!list.some((p) => p.id === viewsState.person)) viewsState.person = list[0].id;
  document.getElementById("hist-body").innerHTML = `
    <div class="tl-toolbar">
      <input type="search" id="hist-filter" placeholder="Search names..." value="${esc(viewsState.filter)}">
      <span id="hist-saved" class="recent-meta"></span>
      <button class="btn" id="hist-save">Save as text</button>
    </div>
    <div class="hist-layout">
      <ul class="hist-people" id="hist-people"></ul>
      <div class="hist-detail" id="hist-detail"><div class="empty-state">Loading...</div></div>
    </div>`;
  drawHistoryList();
  document.getElementById("hist-filter").addEventListener("input", (e) => { viewsState.filter = e.target.value; drawHistoryList(); });
  document.getElementById("hist-save").addEventListener("click", async () => {
    try {
      const r = await postJson("/api/views/people/save");
      document.getElementById("hist-saved").textContent = `Saved to ${r.path}`;
      toast("People histories saved.");
    } catch (e) { toast(e.message, true); }
  });
  await showHistory(viewsState.person);
}

function drawHistoryList() {
  const q = viewsState.filter.trim().toLowerCase();
  const el = document.getElementById("hist-people");
  el.innerHTML = viewsState.people
    .filter((p) => !q || [p.name, ...p.aliases].some((n) => n.toLowerCase().includes(q)))
    .map((p) => `<li><button class="hist-person ${p.id === viewsState.person ? "active" : ""}" data-hist="${p.id}">
      <span>${esc(p.name)}</span><span class="recent-meta">${p.count}${p.written ? (p.current ? " · written" : " · out of date") : ""}</span></button></li>`).join("")
    || `<li class="recent-meta">No match.</li>`;
  el.querySelectorAll("[data-hist]").forEach((b) => b.addEventListener("click", () => showHistory(Number(b.dataset.hist))));
}

async function showHistory(id) {
  viewsState.person = id;
  drawHistoryList();
  const box = document.getElementById("hist-detail");
  let h;
  try { h = await api(`/api/views/people/${id}`); } catch (e) { box.innerHTML = `<div class="empty-state">${esc(e.message)}</div>`; return; }
  if (viewsState.person !== id) return;
  box.innerHTML = `
    <div class="tl-head"><h3>${esc(h.name)}</h3>
      <button class="btn btn-small ${h.text ? "btn-ghost" : "btn-primary"}" id="hist-write">${h.text ? "Write again" : "Write history"}</button></div>
    <div class="recent-meta">${h.aliases.length ? `Also ${h.aliases.map(esc).join(", ")} · ` : ""}${h.count} ${h.count === 1 ? "mention" : "mentions"} · ${tlRange(h.first, h.last)}</div>
    ${h.about ? `<p class="person-about">${esc(h.about)}</p>` : ""}
    ${h.text ? `${h.current ? "" : `<div class="hint warn">Their mentions changed since this was written.</div>`}
      <div class="hist-text">${h.text.split(/\n\s*\n/).map((para) => `<p>${esc(para)}</p>`).join("")}</div>`
      : `<p class="hint">Below are the passages that mention them, in date order. Write history turns these passages into a short account using your organizing model.</p>`}
    <h4 class="hist-head">Passages</h4>
    <ol class="hist-passages">${h.mentions.map((m) => `
      <li><div class="recent-meta">${m.iso ? dayDate(m.iso) : m.date ? esc(m.date) : "Undated"} · ${esc(m.source)}, entry ${m.num}${m.title ? `: ${esc(m.title)}` : ""}
        ${m.filed ? `<button class="link-btn" data-entry="${m.filed.id}">open</button>` : ""}</div>
        <div>${esc(m.excerpt)}</div></li>`).join("")}</ol>`;
  box.querySelectorAll("[data-entry]").forEach((b) => b.addEventListener("click", () => {
    state.returnTo = { view: "views" };
    openEntry(Number(b.dataset.entry));
  }));
  document.getElementById("hist-write").addEventListener("click", (ev) => writeHistory(id, ev.target));
}

async function writeHistory(id, btn) {
  let est;
  try { est = await postJson(`/api/views/people/${id}/estimate`); } catch (e) { toast(e.message, true); return; }
  const price = est.cost === null ? "" : est.cost < 0.01 ? ", under 1 cent at list price" : `, about $${est.cost.toFixed(2)} at list price`;
  if (!await aiConfirm(`Send the ${est.mentions} passages that mention them to your organizing model? About ${est.input_tokens.toLocaleString()} tokens${price}.`)) return;
  btn.disabled = true;
  btn.textContent = "Writing...";
  try {
    await postJson(`/api/views/people/${id}/write`);
    viewsState.people = await api("/api/views/people");
  } catch (e) { toast(e.message, true); }
  if (viewsState.pane === "histories" && document.getElementById("hist-detail")) await showHistory(id);
}
