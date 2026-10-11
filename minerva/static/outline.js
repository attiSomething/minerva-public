// Project outline: the project's pieces as an outline or as index cards,
// each with a synopsis, a status and notes, plus placeholders for pieces
// not written yet. Shown on a project's page.
// Depends on helpers from app.js (api, esc, toast, state, openEntry, plural,
// projectPost, renderProject) and categories.js (categoryOptionsHtml).

const STATUS_LABELS = { "": "No status", idea: "Idea", drafting: "Drafting", revising: "Revising", done: "Done" };

const outlineState = { data: null, project: null, open: new Set(), timers: {} };

function outlineView() {
  try { return localStorage.getItem("minerva-outline-view") || "list"; } catch (e) { return "list"; }
}

function setOutlineView(v) {
  try { localStorage.setItem("minerva-outline-view", v); } catch (e) { /* private window */ }
}

async function renderOutline(p) {
  outlineState.project = p;
  const box = document.getElementById("outline");
  try {
    if (!state.categories) await loadCategories();
    outlineState.data = await api(`/api/projects/${p.id}/outline`);
  }
  catch (e) { box.innerHTML = `<div class="empty-state">${esc(e.message)}</div>`; return; }
  drawOutline();
}

function outlineCountsHtml(c) {
  const parts = ["idea", "drafting", "revising", "done"].filter((s) => c[s])
    .map((s) => `<span class="st-pill st-${s}">${c[s]} ${STATUS_LABELS[s].toLowerCase()}</span>`);
  return parts.join("");
}

function statusSelectHtml(item) {
  return `<select class="st-select st-${item.status || "none"}" data-status aria-label="Status of ${esc(item.title)}">
    ${Object.entries(STATUS_LABELS).map(([v, l]) => `<option value="${v}" ${item.status === v ? "selected" : ""}>${l}</option>`).join("")}
  </select>`;
}

function drawOutline() {
  const box = document.getElementById("outline");
  if (!box) return;
  const { items, counts } = outlineState.data;
  const view = outlineView();
  box.innerHTML = `
    <div class="outline-head">
      <h3 class="section-title">Outline</h3>
      <div class="outline-counts">${outlineCountsHtml(counts)}</div>
      <span style="flex:1"></span>
      <div class="seg" role="radiogroup" aria-label="Outline view">
        <button class="seg-btn ${view === "list" ? "active" : ""}" data-oview="list" role="radio" aria-checked="${view === "list"}">List</button>
        <button class="seg-btn ${view === "cards" ? "active" : ""}" data-oview="cards" role="radio" aria-checked="${view === "cards"}">Cards</button>
      </div>
      <button class="btn btn-small" id="outline-add">Add placeholder</button>
    </div>
    <form class="outline-new" id="outline-new" hidden>
      <input type="text" id="outline-new-title" placeholder="Title of a piece you haven't written yet" maxlength="200" required>
      <input type="text" id="outline-new-synopsis" placeholder="One line on what it will be (optional)" maxlength="400">
      <button class="btn btn-small" type="submit">Add</button>
      <button class="btn btn-small btn-ghost" type="button" id="outline-new-cancel">Cancel</button>
    </form>
    ${items.length ? (view === "cards" ? outlineCardsHtml(items) : outlineListHtml(items)) :
      `<div class="empty-state" style="padding:20px">Nothing in this project yet. Add entries from the right, or add a placeholder for a piece you plan to write.</div>`}
    ${items.length ? `<div class="hint">This order is the order the project exports in.${view === "cards" ? " Drag cards to rearrange them." : ""}</div>` : ""}`;
  wireOutline();
}

function outlineListHtml(items) {
  return `<ol class="outline-list">${items.map((it, i) => {
    const open = outlineState.open.has(it.id);
    const ph = it.kind === "placeholder";
    return `<li class="ol-item ${ph ? "ol-placeholder" : ""}" data-item="${it.id}">
      <div class="ol-row">
        <span class="order-cell">
          <button class="icon-btn" data-omove="-1" ${i === 0 ? "disabled" : ""} title="Move up" aria-label="Move ${esc(it.title)} up">&uarr;</button>
          <button class="icon-btn" data-omove="1" ${i === items.length - 1 ? "disabled" : ""} title="Move down" aria-label="Move ${esc(it.title)} down">&darr;</button>
        </span>
        <span class="ol-title">${ph
          ? `<input type="text" class="ol-title-input" data-title value="${esc(it.title)}" aria-label="Placeholder title"> <span class="badge">Not written yet</span>`
          : `<a href="#" data-oopen="${it.entry_id}">${esc(it.title)}</a> <span class="badge badge-tag-${it.draft_tag}">${esc(it.draft_tag || "?")}</span>`}</span>
        ${statusSelectHtml(it)}
        <span class="ol-words muted">${ph ? "" : plural(it.word_count, "word", "words")}</span>
        <button class="btn btn-small btn-ghost" data-onotes aria-expanded="${open}">${open ? "Hide" : "Notes"}${it.notes && !open ? " •" : ""}</button>
      </div>
      <input type="text" class="ol-synopsis" data-synopsis value="${esc(it.synopsis)}" placeholder="One line on what this piece is..." maxlength="400" aria-label="Synopsis of ${esc(it.title)}">
      ${open ? outlineDetailHtml(it) : ""}
    </li>`;
  }).join("")}</ol>`;
}

function outlineDetailHtml(it) {
  const ph = it.kind === "placeholder";
  return `<div class="ol-detail">
    <textarea data-onotes-text spellcheck="true" placeholder="${ph ? "Ideas, lines, research for this piece..." : "Notes for this entry (the same notes as on its page)..."}">${esc(it.notes)}</textarea>
    <div class="ol-actions">
      ${ph ? `
        <label>Start writing in <select data-ocat>${categoryOptionsHtml(usualCategory())}</select></label>
        <button class="btn btn-small" data-ostart>Start writing</button>
        <button class="btn btn-small btn-ghost" data-olink-toggle>Link an existing entry</button>
        <span style="flex:1"></span>
        <button class="btn btn-small btn-ghost" data-odelete>Delete placeholder</button>
        <div class="ol-link" hidden><input type="search" data-olink-search placeholder="Search entries by title..."><div class="lost-results" data-olink-results></div></div>`
      : `<span style="flex:1"></span>
        <button class="btn btn-small btn-ghost" data-oremove title="Take this entry out of the project. The entry stays in your library.">Remove from project</button>`}
    </div>
  </div>`;
}

// New pieces default to the category most of the project already lives in.
function usualCategory() {
  const n = {};
  outlineState.data.items.forEach((i) => { if (i.category) n[i.category] = (n[i.category] || 0) + 1; });
  const best = Object.entries(n).sort((a, b) => b[1] - a[1])[0];
  return best ? best[0] : (state.categories || [])[0];
}

function outlineCardsHtml(items) {
  return `<div class="outline-cards">${items.map((it, i) => {
    const ph = it.kind === "placeholder";
    return `<div class="ol-card ${ph ? "ol-placeholder" : ""}" data-item="${it.id}" draggable="true">
      <div class="ol-card-head">
        <span class="ol-num">${i + 1}</span>
        ${statusSelectHtml(it)}
      </div>
      <div class="ol-card-title">${ph ? `${esc(it.title)} <span class="badge">Not written yet</span>`
        : `<a href="#" data-oopen="${it.entry_id}">${esc(it.title)}</a>`}</div>
      <textarea class="ol-card-synopsis" data-synopsis rows="3" placeholder="One line on what this piece is..." maxlength="400" aria-label="Synopsis of ${esc(it.title)}">${esc(it.synopsis)}</textarea>
      <div class="ol-card-foot">
        <span class="muted">${ph ? "" : plural(it.word_count, "word", "words")}${it.notes ? `${ph ? "" : " · "}has notes` : ""}</span>
        <span>
          <button class="icon-btn" data-omove="-1" ${i === 0 ? "disabled" : ""} title="Move earlier" aria-label="Move ${esc(it.title)} earlier">&larr;</button>
          <button class="icon-btn" data-omove="1" ${i === items.length - 1 ? "disabled" : ""} title="Move later" aria-label="Move ${esc(it.title)} later">&rarr;</button>
        </span>
      </div>
    </div>`;
  }).join("")}</div>`;
}

function outlinePost(path, body) {
  return projectPost(`/outline${path}`, body);
}

function outlineItem(id) {
  return outlineState.data.items.find((i) => i.id === id);
}

async function saveOutlineField(id, fields, { redraw = false } = {}) {
  try {
    const data = await outlinePost(`/${id}`, fields);
    outlineState.data = data;
    if (redraw) drawOutline();
    else {
      const counts = document.querySelector(".outline-counts");
      if (counts) counts.innerHTML = outlineCountsHtml(data.counts);
    }
  } catch (e) { toast(e.message, true); }
}

async function outlineOrder(ids) {
  try {
    outlineState.data = await outlinePost("/order", { item_ids: ids });
    drawOutline();
  } catch (e) { toast(e.message, true); renderOutline(outlineState.project); }
}

function wireOutline() {
  const box = document.getElementById("outline");
  const p = outlineState.project;
  box.querySelectorAll("[data-oview]").forEach((b) => b.addEventListener("click", () => {
    setOutlineView(b.dataset.oview);
    drawOutline();
  }));

  const form = document.getElementById("outline-new");
  document.getElementById("outline-add").addEventListener("click", () => {
    form.hidden = false;
    document.getElementById("outline-new-title").focus();
  });
  document.getElementById("outline-new-cancel").addEventListener("click", () => { form.hidden = true; });
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      const data = await outlinePost("/add", { title: document.getElementById("outline-new-title").value,
        synopsis: document.getElementById("outline-new-synopsis").value });
      outlineState.data = data;
      drawOutline();
    } catch (e) { toast(e.message, true); }
  });

  box.querySelectorAll("[data-item]").forEach((el) => {
    const id = Number(el.dataset.item);
    const q = (sel) => el.querySelector(sel);
    q("[data-status]").addEventListener("change", (ev) => {
      ev.target.className = `st-select st-${ev.target.value || "none"}`;
      saveOutlineField(id, { status: ev.target.value });
    });
    const syn = q("[data-synopsis]");
    syn.addEventListener("change", () => saveOutlineField(id, { synopsis: syn.value }));
    syn.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); syn.blur(); } });
    const title = q("[data-title]");
    if (title) title.addEventListener("change", () => saveOutlineField(id, { title: title.value }));
    el.querySelectorAll("[data-omove]").forEach((b) => b.addEventListener("click", () => {
      const ids = outlineState.data.items.map((i) => i.id);
      const i = ids.indexOf(id);
      const j = i + Number(b.dataset.omove);
      [ids[i], ids[j]] = [ids[j], ids[i]];
      outlineOrder(ids);
    }));
    const notesBtn = q("[data-onotes]");
    if (notesBtn) notesBtn.addEventListener("click", () => {
      if (outlineState.open.has(id)) outlineState.open.delete(id); else outlineState.open.add(id);
      drawOutline();
      const t = document.querySelector(`[data-item="${id}"] [data-onotes-text]`);
      if (t) t.focus();
    });
    const notesText = q("[data-onotes-text]");
    if (notesText) {
      const save = () => { clearTimeout(outlineState.timers[id]); saveOutlineField(id, { notes: notesText.value }); };
      notesText.addEventListener("input", () => {
        clearTimeout(outlineState.timers[id]);
        outlineState.timers[id] = setTimeout(save, 700);
      });
      notesText.addEventListener("blur", save);
    }
    const start = q("[data-ostart]");
    if (start) start.addEventListener("click", async () => {
      start.disabled = true;
      try {
        const data = await outlinePost(`/${id}/start`, { category: q("[data-ocat]").value });
        outlineState.open.delete(id);
        state.projectsCache = [];
        toast(`Created "${outlineItem(id).title}". Write away.`);
        state.returnTo = { view: "project", id: p.id };
        state.view = "entries";
        document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === "entries"));
        openEntry(data.entry_id);
      } catch (e) { start.disabled = false; toast(e.message, true); }
    });
    const linkToggle = q("[data-olink-toggle]");
    if (linkToggle) {
      const wrap = q(".ol-link");
      const input = q("[data-olink-search]");
      const results = q("[data-olink-results]");
      linkToggle.addEventListener("click", () => { wrap.hidden = !wrap.hidden; if (!wrap.hidden) input.focus(); });
      let timer;
      input.addEventListener("input", () => {
        clearTimeout(timer);
        timer = setTimeout(async () => {
          const term = input.value.trim();
          if (!term) { results.innerHTML = ""; return; }
          const r = await api(`/api/entries?search=${encodeURIComponent(term)}&page_size=8`);
          const taken = new Set(outlineState.data.items.filter((i) => i.entry_id).map((i) => i.entry_id));
          const rows = r.rows.filter((e) => !taken.has(e.id));
          results.innerHTML = rows.length ? rows.map((e) =>
            `<button class="btn btn-ghost btn-small" data-olink="${e.id}" ${e.project_tag && e.project_tag !== p.tag ? `title="Moves it out of [${esc(e.project_tag)}]"` : ""}>${esc(e.title)} <span class="hint">${esc(e.top_folder)}</span></button>`).join("")
            : `<div class="hint">No other entries match.</div>`;
          results.querySelectorAll("[data-olink]").forEach((b) => b.addEventListener("click", async () => {
            try {
              outlineState.data = await outlinePost(`/${id}/link`, { entry_id: Number(b.dataset.olink) });
              outlineState.open.delete(id);
              state.projectsCache = [];
              renderProject();
            } catch (e) { toast(e.message, true); }
          }));
        }, 220);
      });
    }
    const del = q("[data-odelete]");
    if (del) del.addEventListener("click", async () => {
      const it = outlineItem(id);
      if ((it.synopsis || it.notes) && !confirm(`Delete the placeholder "${it.title}" and its notes?`)) return;
      try {
        outlineState.data = await outlinePost(`/${id}/delete`, {});
        outlineState.open.delete(id);
        drawOutline();
      } catch (e) { toast(e.message, true); }
    });
    const remove = q("[data-oremove]");
    if (remove) remove.addEventListener("click", async () => {
      try {
        const r = await projectPost("/entries", { remove: [outlineItem(id).entry_id] });
        if (r.problems.length) toast(r.problems.join(" "), true);
        outlineState.open.delete(id);
        state.projectsCache = [];
        renderProject();
      } catch (e) { toast(e.message, true); }
    });
  });

  box.querySelectorAll("[data-oopen]").forEach((a) => a.addEventListener("click", (ev) => {
    ev.preventDefault();
    state.returnTo = { view: "project", id: p.id };
    state.view = "entries";
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === "entries"));
    openEntry(Number(a.dataset.oopen));
  }));

  wireCardDrag(box);
}

// Cards rearrange by drag and drop: dropping on the left half of a card puts
// the dragged one before it, on the right half after it. The arrow buttons
// on each card do the same from the keyboard.
function wireCardDrag(box) {
  let dragged = null;
  box.querySelectorAll(".ol-card").forEach((card) => {
    card.addEventListener("dragstart", (ev) => {
      if (ev.target.closest("textarea, select, a")) { ev.preventDefault(); return; }
      dragged = Number(card.dataset.item);
      card.classList.add("dragging");
      ev.dataTransfer.effectAllowed = "move";
      ev.dataTransfer.setData("text/plain", String(dragged));
    });
    card.addEventListener("dragend", () => {
      card.classList.remove("dragging");
      box.querySelectorAll(".drop-before, .drop-after").forEach((c) => c.classList.remove("drop-before", "drop-after"));
    });
    card.addEventListener("dragover", (ev) => {
      if (dragged === null || Number(card.dataset.item) === dragged) return;
      ev.preventDefault();
      const r = card.getBoundingClientRect();
      const after = ev.clientX > r.left + r.width / 2;
      card.classList.toggle("drop-after", after);
      card.classList.toggle("drop-before", !after);
    });
    card.addEventListener("dragleave", () => card.classList.remove("drop-before", "drop-after"));
    card.addEventListener("drop", (ev) => {
      ev.preventDefault();
      const target = Number(card.dataset.item);
      const after = card.classList.contains("drop-after");
      card.classList.remove("drop-before", "drop-after");
      if (dragged === null || target === dragged) return;
      const ids = outlineState.data.items.map((i) => i.id).filter((i) => i !== dragged);
      ids.splice(ids.indexOf(target) + (after ? 1 : 0), 0, dragged);
      dragged = null;
      outlineOrder(ids);
    });
  });
}
