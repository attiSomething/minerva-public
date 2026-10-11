// Categories: the library's top-level folders. Settings lists them with
// rename and remove; any category menu can end with "New category..." so a
// category can be added right where an entry is being sorted.

const NEW_CATEGORY = "__new__";

async function loadCategories() {
  state.categories = await api("/api/categories");
  return state.categories;
}

// New entries and imports start in the category used last time.
function defaultCategory() {
  let last = "";
  try { last = localStorage.getItem("minerva.lastCategory") || ""; } catch (e) { /* storage off */ }
  const cats = state.categories || [];
  return cats.includes(last) ? last : cats[0] || "";
}

function rememberCategory(c) {
  try { if (c) localStorage.setItem("minerva.lastCategory", c); } catch (e) { /* storage off */ }
}

function categoryOptionsHtml(selected, { withNew = false } = {}) {
  return (state.categories || []).map((c) =>
    `<option value="${esc(c)}" ${c === selected ? "selected" : ""}>${esc(c)}</option>`).join("")
    + (withNew ? `<option value="${NEW_CATEGORY}">New category…</option>` : "");
}

// Ask for a name and add the category. Returns its name, or null if the
// person cancels or it couldn't be added.
async function addCategoryPrompt() {
  const name = prompt("Name the new category. Minerva makes a folder for it in your library.");
  if (!name || !name.trim()) return null;
  try {
    await postJson("/api/categories", { name });
  } catch (e) {
    toast(e.message, true);
    return null;
  }
  const list = await loadCategories();
  return list.find((c) => c.toLowerCase() === name.trim().replace(/\s+/g, " ").replace(/[ .]+$/, "").toLowerCase()) || null;
}

// For a <select> built with withNew: picking "New category..." adds one and
// selects it; cancelling goes back to the previous choice. onPick gets the
// final value when it changed.
function wireCategorySelect(sel, onPick) {
  let previous = sel.value;
  sel.addEventListener("change", async () => {
    if (sel.value !== NEW_CATEGORY) {
      previous = sel.value;
      if (onPick) onPick(sel.value);
      return;
    }
    const name = await addCategoryPrompt();
    if (!name) { sel.value = previous; return; }
    document.querySelectorAll("select[data-category-menu]").forEach((s) => {
      const keep = s === sel ? name : s.value;
      s.innerHTML = categoryOptionsHtml(keep, { withNew: true });
    });
    previous = name;
    toast(`Added the category "${name}".`);
    if (onPick) onPick(name);
  });
}

// ---- Settings section -----------------------------------------------------

function categoriesSectionHtml(details) {
  return `
    <section class="panel" id="categories-section">
      <h2>Categories</h2>
      <p class="muted">The folders at the top of your library. Renaming one renames its folder; every entry in it keeps its history, links and submissions.</p>
      <ul class="cat-list">
        ${details.map((c) => `
          <li data-cat="${esc(c.name)}">
            <span class="cat-name">${esc(c.name)}</span>
            <span class="muted">${c.entries.toLocaleString()} entr${c.entries === 1 ? "y" : "ies"}</span>
            <span class="spacer"></span>
            <button class="btn btn-small btn-ghost" data-cat-rename>Rename</button>
            ${c.entries ? "" : `<button class="btn btn-small btn-ghost" data-cat-remove>Remove</button>`}
          </li>`).join("")}
      </ul>
      <div class="profile-row">
        <input type="text" id="cat-new" maxlength="60" placeholder="New category, e.g. Essays">
        <button class="btn" id="cat-add">Add</button>
      </div>
    </section>`;
}

function wireCategoriesSection(refresh) {
  const sec = document.getElementById("categories-section");
  if (!sec) return;
  const done = async (msg) => { await loadCategories(); toast(msg); refresh(); };
  const add = async () => {
    const input = document.getElementById("cat-new");
    try {
      await postJson("/api/categories", { name: input.value });
      await done(`Added "${input.value.trim()}".`);
    } catch (e) { toast(e.message, true); }
  };
  document.getElementById("cat-add").addEventListener("click", add);
  document.getElementById("cat-new").addEventListener("keydown", (ev) => { if (ev.key === "Enter") add(); });
  sec.querySelectorAll("[data-cat-rename]").forEach((b) => b.addEventListener("click", async () => {
    const old = b.closest("li").dataset.cat;
    const name = prompt(`Rename "${old}" to:`, old);
    if (!name || name.trim() === old) return;
    try {
      await postJson("/api/categories/rename", { old, new: name });
      await done(`Renamed "${old}".`);
    } catch (e) { toast(e.message, true); }
  }));
  sec.querySelectorAll("[data-cat-remove]").forEach((b) => b.addEventListener("click", async () => {
    const name = b.closest("li").dataset.cat;
    if (!confirm(`Stop using "${name}" as a category? It has no entries. Its folder stays in your library.`)) return;
    try {
      await postJson("/api/categories/remove", { name });
      await done(`Removed "${name}".`);
    } catch (e) { toast(e.message, true); }
  }));
}
