// Tags and saved collections. Tags go on an entry from its page; the
// Entries filters can narrow to one tag, and any set of filters can be
// saved as a collection that stays one click away. Settings lists every tag
// for renaming or removing.
// Depends on helpers from app.js (api, esc, toast, state, postJson) and
// is used by app.js (renderEntries, renderEdit) and onboarding.js (settings).

async function loadTags() {
  state.allTags = await api("/api/tags").catch(() => []);
  return state.allTags;
}

function tagChipsHtml(tags, { small = false } = {}) {
  return tags.map((t) => `<span class="tag-chip${small ? " small" : ""}">${esc(t)}</span>`).join("");
}

// ---- Entries filters -------------------------------------------------------

function tagFilterHtml() {
  const tags = state.allTags || [];
  return `<div class="filter-group">
    <label for="f-tag">Tag</label>
    <select id="f-tag">
      <option value="">All</option>
      ${tags.map((t) => `<option value="${esc(t.tag)}">${esc(t.tag)} (${t.count})</option>`).join("")}
    </select>
    ${tags.length ? "" : `<div class="hint">Add tags to an entry from its page.</div>`}
  </div>`;
}

function collectionsHtml() {
  const cols = state.collections || [];
  return `<div class="filter-group collections">
    <label>Collections</label>
    ${cols.length ? `<div class="collection-list">${cols.map((c) => `
      <span class="collection" data-collection="${c.id}">
        <button class="link-btn" data-apply-collection="${c.id}" title="${esc(describeFilters(c.filters))}">${esc(c.name)}</button>
        <button class="icon-btn" data-delete-collection="${c.id}" aria-label="Delete the collection ${esc(c.name)}" title="Delete this collection">&times;</button>
      </span>`).join("")}</div>` : `<div class="hint">Save the filters you use often.</div>`}
    <button class="btn btn-small btn-ghost" id="save-collection">Save these filters…</button>
  </div>`;
}

function describeFilters(f) {
  const parts = [];
  if (f.search) parts.push(`${f.mode === "text" ? "inside drafts" : "title"}: "${f.search}"`);
  if (f.tag) parts.push(`tag ${f.tag}`);
  if (f.category) parts.push(f.category);
  if (f.project) parts.push(f.project === "__none__" ? "no project" : `project ${f.project}`);
  if (f.published) parts.push(f.published === "1" ? "published" : "not published");
  if (f.to_edit) parts.push("to edit");
  if (f.to_record) parts.push("to record");
  if (f.needs_review) parts.push("needs review");
  if (f.current) parts.push("current drafts only");
  return parts.join(", ");
}

function currentEntryFilters() {
  const v = (id) => document.getElementById(id).value;
  const c = (id) => document.getElementById(id).checked;
  return {
    search: v("f-search").trim(), mode: state.searchMode === "text" ? "text" : "titles",
    category: v("f-category"), project: v("f-project"), published: v("f-published"), tag: v("f-tag"),
    to_edit: c("f-to-edit"), to_record: c("f-to-record"), needs_review: c("f-needs-review"), current: c("f-current"),
  };
}

function applyEntryFilters(f) {
  const set = (id, val) => {
    const el = document.getElementById(id);
    if (el.tagName === "SELECT" && val && ![...el.options].some((o) => o.value === val)) {
      el.insertAdjacentHTML("beforeend", `<option value="${esc(val)}">${esc(val)}</option>`);
    }
    el.value = val || "";
  };
  set("f-search", f.search); state.searchQuery = f.search || "";
  set("f-category", f.category); set("f-project", f.project); set("f-published", f.published); set("f-tag", f.tag);
  ["to_edit", "to_record", "needs_review", "current"].forEach((k) => {
    document.getElementById(`f-${k.replace("_", "-")}`).checked = !!f[k];
  });
  state.searchMode = f.mode === "text" ? "text" : "titles";
  applySearchMode();
  loadAndRenderEntryTable(true);
}

function wireCollections() {
  const redraw = () => {
    const box = document.querySelector(".filter-group.collections");
    if (box) { box.outerHTML = collectionsHtml(); wireCollections(); }
  };
  document.getElementById("save-collection").addEventListener("click", async () => {
    const f = currentEntryFilters();
    const what = describeFilters(f);
    if (!what) { toast("Choose a filter or type a search first; a collection saves what you've chosen.", true); return; }
    const name = prompt(`Name this collection (${what}):`, f.tag || f.search || "");
    if (!name || !name.trim()) return;
    try {
      state.collections = await postJson("/api/collections", { name, filters: f });
      toast(`Saved "${name.trim()}".`);
      redraw();
    } catch (e) { toast(e.message, true); }
  });
  document.querySelectorAll("[data-apply-collection]").forEach((b) => b.addEventListener("click", () => {
    const c = state.collections.find((x) => x.id === Number(b.dataset.applyCollection));
    if (c) applyEntryFilters(c.filters);
  }));
  document.querySelectorAll("[data-delete-collection]").forEach((b) => b.addEventListener("click", async () => {
    const c = state.collections.find((x) => x.id === Number(b.dataset.deleteCollection));
    if (!c || !confirm(`Delete the collection "${c.name}"? The entries in it aren't touched.`)) return;
    try {
      state.collections = await postJson(`/api/collections/${c.id}/delete`, {});
      redraw();
    } catch (e) { toast(e.message, true); }
  }));
}

// ---- Entry page -------------------------------------------------------------

function tagsPanelHtml(e) {
  return `<div class="panel tags-panel">
    <h3><label for="tag-input">Tags</label></h3>
    <div class="tag-edit" id="tag-edit">${e.tags.map(tagEditChip).join("")}</div>
    <input type="text" id="tag-input" list="tag-options" placeholder="Add a tag, then Enter" maxlength="40" autocomplete="off">
    <datalist id="tag-options">${(state.allTags || []).map((t) => `<option value="${esc(t.tag)}">`).join("")}</datalist>
  </div>`;
}

function tagEditChip(t) {
  return `<span class="tag-chip">${esc(t)}<button class="tag-x" data-untag="${esc(t)}" aria-label="Remove the tag ${esc(t)}" title="Remove">&times;</button></span>`;
}

function wireTagsPanel(entryId, initial) {
  let tags = initial.slice();
  const box = document.getElementById("tag-edit");
  const input = document.getElementById("tag-input");
  const draw = () => {
    box.innerHTML = tags.map(tagEditChip).join("");
    box.querySelectorAll("[data-untag]").forEach((b) => b.addEventListener("click", () => {
      save(tags.filter((t) => t !== b.dataset.untag));
    }));
  };
  const save = async (next) => {
    try {
      const r = await postJson(`/api/entries/${entryId}/tags`, { tags: next });
      tags = r.tags;
      state.allTags = r.all;
      draw();
    } catch (e) { toast(e.message, true); }
  };
  const add = () => {
    const parts = input.value.split(",").map((s) => s.trim().replace(/^#/, "")).filter(Boolean);
    input.value = "";
    if (!parts.length) return;
    const have = new Set(tags.map((t) => t.toLowerCase()));
    save(tags.concat(parts.filter((p) => !have.has(p.toLowerCase()))));
  };
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" || ev.key === ",") { ev.preventDefault(); add(); }
    else if (ev.key === "Backspace" && !input.value && tags.length) save(tags.slice(0, -1));
  });
  input.addEventListener("change", () => { if (input.value.trim()) add(); });
  draw();
}

// ---- Settings ---------------------------------------------------------------

function tagsSectionHtml(tags) {
  return `
    <section class="panel" id="tags-section">
      <h2>Tags</h2>
      <p class="muted">Tags group entries across categories and projects. Add them from an entry's page. Renaming a tag onto one that exists joins them. Removing a tag only takes it off entries; the entries aren't touched.</p>
      ${tags.length ? `<ul class="cat-list">
        ${tags.map((t) => `
          <li data-tag="${esc(t.tag)}">
            <span class="tag-chip">${esc(t.tag)}</span>
            <span class="muted">${t.count.toLocaleString()} entr${t.count === 1 ? "y" : "ies"}</span>
            <span class="spacer"></span>
            <button class="btn btn-small btn-ghost" data-tag-rename>Rename</button>
            <button class="btn btn-small btn-ghost" data-tag-remove>Remove</button>
          </li>`).join("")}
      </ul>` : `<p class="hint">No tags yet.</p>`}
    </section>`;
}

function wireTagsSection(refresh) {
  const sec = document.getElementById("tags-section");
  if (!sec) return;
  sec.querySelectorAll("[data-tag-rename]").forEach((b) => b.addEventListener("click", async () => {
    const old = b.closest("li").dataset.tag;
    const name = prompt(`Rename the tag "${old}" to:`, old);
    if (!name || name.trim() === old) return;
    try {
      state.allTags = await postJson("/api/tags/rename", { old, new: name });
      toast(`Renamed "${old}".`);
      refresh();
    } catch (e) { toast(e.message, true); }
  }));
  sec.querySelectorAll("[data-tag-remove]").forEach((b) => b.addEventListener("click", async () => {
    const tag = b.closest("li").dataset.tag;
    if (!confirm(`Take the tag "${tag}" off every entry?`)) return;
    try {
      state.allTags = await postJson("/api/tags/remove", { tag });
      refresh();
    } catch (e) { toast(e.message, true); }
  }));
}
