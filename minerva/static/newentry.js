// New entry: start a blank draft, or paste text in. Pasted text can be
// split into several entries at separator lines (***) or three blank
// lines, with a preview where each piece's title can be changed first.
// Used by app.js (Entries) and home.js (Home).

const newEntryState = { pieces: null, timer: null };

function closeNewEntry() {
  const el = document.getElementById("new-entry-dialog");
  if (el) el.remove();
  document.removeEventListener("keydown", newEntryKeys);
}

function newEntryKeys(ev) {
  if (ev.key === "Escape") closeNewEntry();
}

function wordCount(text) {
  return (String(text).match(/\S+/g) || []).length;
}

async function openNewEntry({ text = "", category = "", project = "" } = {}) {
  if (state.projectsCache.length === 0) await loadProjects();
  await loadCategories();
  closeNewEntry();
  newEntryState.pieces = null;
  const el = document.createElement("div");
  el.id = "new-entry-dialog";
  el.className = "modal-backdrop";
  const cat = category || defaultCategory();
  el.innerHTML = `
    <div class="modal modal-wide" role="dialog" aria-modal="true" aria-labelledby="ne-title-h">
      <h2 id="ne-title-h">New entry</h2>
      <p class="hint">Start a blank draft, or paste in writing from anywhere. Minerva makes the entry's folder and current draft in your library. Have files instead? <a href="#" id="ne-to-import">Import files</a>. ${helpLinkHtml("intake", "Bringing in old drafts")}</p>
      <div class="ne-grid">
        <div class="field-row"><label for="ne-title">Title</label>
          <input type="text" id="ne-title" maxlength="120" autocomplete="off" placeholder="Untitled"></div>
        <div class="field-row"><label for="ne-category">Category</label>
          <select id="ne-category" data-category-menu>${categoryOptionsHtml(cat, { withNew: true })}</select></div>
        <div class="field-row"><label for="ne-project">Project</label>
          <select id="ne-project"><option value="">No project</option>
            ${state.projectsCache.map((p) => `<option value="${esc(p.tag)}" ${p.tag === project ? "selected" : ""}>${esc(p.name)}</option>`).join("")}
          </select></div>
      </div>
      <div class="field-row"><label for="ne-text">Text <span class="muted">(optional)</span></label>
        <textarea id="ne-text" rows="10" spellcheck="true" placeholder="Paste a draft here, or leave this empty to start writing.">${esc(text)}</textarea></div>
      <label class="filter-check" id="ne-split-row" hidden><input type="checkbox" id="ne-split"> Split into separate entries at *** lines or three blank lines</label>
      <div id="ne-pieces"></div>
      <div class="modal-actions">
        <span class="muted" id="ne-summary"></span>
        <span style="flex:1"></span>
        <button class="btn btn-ghost" id="ne-cancel">Cancel</button>
        <button class="btn btn-gold" id="ne-create">Create entry</button>
      </div>
    </div>`;
  document.body.appendChild(el);
  document.addEventListener("keydown", newEntryKeys);
  document.getElementById("ne-cancel").addEventListener("click", closeNewEntry);
  document.getElementById("ne-to-import").addEventListener("click", (ev) => {
    ev.preventDefault();
    const cat = document.getElementById("ne-category").value;
    const proj = document.getElementById("ne-project").value;
    closeNewEntry();
    openFileImport({ category: cat, project: proj });
  });
  wireCategorySelect(document.getElementById("ne-category"));
  const textEl = document.getElementById("ne-text");
  const splitEl = document.getElementById("ne-split");
  textEl.addEventListener("input", () => { clearTimeout(newEntryState.timer); newEntryState.timer = setTimeout(refreshNewEntry, 350); });
  splitEl.addEventListener("change", refreshNewEntry);
  document.getElementById("ne-create").addEventListener("click", createNewEntries);
  await refreshNewEntry();
  document.getElementById(text ? "ne-text" : "ne-title").focus();
}

// Show the split option when the paste looks like more than one piece, and
// the preview of pieces when it's on.
async function refreshNewEntry() {
  const textEl = document.getElementById("ne-text");
  if (!textEl) return;
  const text = textEl.value;
  const splitRow = document.getElementById("ne-split-row");
  const split = document.getElementById("ne-split").checked;
  const titleEl = document.getElementById("ne-title");
  let pieces = [];
  if (text.trim()) {
    try {
      pieces = await postJson("/api/entries/paste/preview", { text, split: true });
    } catch (e) { toast(e.message, true); return; }
  }
  splitRow.hidden = pieces.length < 2;
  titleEl.placeholder = (pieces[0] && pieces[0].title) || "Untitled";
  const many = split && pieces.length > 1;
  newEntryState.pieces = many ? pieces : null;
  document.getElementById("ne-title").closest(".field-row").hidden = many;
  const box = document.getElementById("ne-pieces");
  box.innerHTML = many ? `
    <div class="ne-pieces">${pieces.map((p, i) => `
      <div class="ne-piece">
        <input type="text" maxlength="120" value="${esc(p.title)}" data-piece="${i}" aria-label="Title of piece ${i + 1}">
        <span class="muted">${wordCount(p.text).toLocaleString()} words</span>
        <div class="ne-first muted">${esc(p.text.split("\n").filter((l) => l.trim()).slice(1, 3).join(" / "))}</div>
      </div>`).join("")}</div>` : "";
  box.querySelectorAll("[data-piece]").forEach((inp) => inp.addEventListener("input", () => {
    newEntryState.pieces[Number(inp.dataset.piece)].title = inp.value;
  }));
  const btn = document.getElementById("ne-create");
  btn.textContent = many ? `Create ${pieces.length} entries` : "Create entry";
  document.getElementById("ne-summary").textContent = text.trim() && !many ? `${wordCount(text).toLocaleString()} words` : "";
}

async function createNewEntries() {
  const btn = document.getElementById("ne-create");
  const category = document.getElementById("ne-category").value;
  rememberCategory(category);
  const project = document.getElementById("ne-project").value;
  const titleEl = document.getElementById("ne-title");
  const text = document.getElementById("ne-text").value;
  const items = newEntryState.pieces
    ? newEntryState.pieces.map((p) => ({ title: p.title.trim() || "Untitled", text: p.text }))
    : [{ title: titleEl.value.trim() || titleEl.placeholder || "Untitled", text }];
  btn.disabled = true;
  try {
    const made = await postJson("/api/entries/new", { items, category, project });
    closeNewEntry();
    if (made.length === 1) {
      toast(made[0].title === items[0].title ? "Entry created." : `Created as "${made[0].title}" (that title was taken).`);
      state.view = "entries";
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === "entries"));
      await openEntry(made[0].id);
    } else {
      toast(`Created ${made.length} entries in ${category}.`);
      await setView("entries");
    }
  } catch (e) {
    btn.disabled = false;
    toast(e.message, true);
  }
}
