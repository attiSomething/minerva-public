// Search inside drafts (the "Inside drafts" mode of the Entries search box).
// Depends on helpers from app.js (api, esc, plural, openEntry, state).

async function renderTextSearch() {
  const q = document.getElementById("f-search").value.trim();
  const container = document.getElementById("entry-table-container");
  const countEl = document.getElementById("entry-count");
  document.getElementById("pagination-controls").innerHTML = "";
  if (q.length < 2) {
    countEl.textContent = "";
    container.innerHTML = `<div class="empty-state">Type at least two letters to search every draft, including the older ones in each entry's Archive.</div>`;
    return;
  }
  const params = new URLSearchParams({ q });
  const category = document.getElementById("f-category").value;
  const project = document.getElementById("f-project").value;
  if (category) params.set("category", category);
  if (project) params.set("project", project);
  const tag = document.getElementById("f-tag").value;
  if (tag) params.set("tag", tag);
  if (document.getElementById("f-current").checked) params.set("current", "1");
  const seq = (renderTextSearch.seq = (renderTextSearch.seq || 0) + 1);
  let r;
  try {
    r = await api(`/api/search?${params}`);
  } catch (e) {
    container.innerHTML = `<div class="empty-state">Search failed: ${esc(e.message)}</div>`;
    return;
  }
  if (seq !== renderTextSearch.seq || state.searchMode !== "text") return;  // a newer search is on its way
  if (!r.entries.length) {
    countEl.textContent = "";
    container.innerHTML = `<div class="empty-state">No drafts contain “${esc(q)}”.</div>`;
    return;
  }
  const places = [r.files || !r.notes ? plural(r.files, "draft", "drafts") : "", r.notes ? plural(r.notes, "note", "notes") : ""].filter(Boolean).join(" and ");
  countEl.textContent = `${plural(r.matches, "match", "matches")} in ${places} across ${plural(r.entries.length, "entry", "entries")}${r.truncated ? " (showing the first " + r.files + " drafts)" : ""}`;
  container.innerHTML = `<div class="text-replace-row"><button class="btn btn-small btn-ghost" id="text-replace" title="Replace this word or phrase in the current drafts, with a preview first">Replace in drafts...</button></div><div class="text-results">${r.entries.map((e) => `
    <div class="text-result" data-id="${e.id}">
      <div class="text-result-head">
        <a href="#" class="text-result-title" data-open="${e.id}">${esc(e.title)}</a>
        <span class="muted">${esc(e.category)}${e.project ? ` · ${esc(e.project)}` : ""}</span>
      </div>
      ${e.files.map((f) => `
        <div class="text-file">
          <div class="text-file-name">${f.kind === "current" ? `<span class="badge">Current draft</span>` : f.kind === "notes" ? `<span class="badge">Notes</span>` : `<span class="badge badge-dim">Archive</span> ${esc(f.name)}`}
            <span class="muted">${plural(f.matches, "match", "matches")}</span></div>
          ${f.snippets.map((s) => `<div class="text-snippet"><span class="line-no">${s.line}</span><span>${s.pieces.map((p) => p.hit ? `<mark>${esc(p.text)}</mark>` : esc(p.text)).join("")}</span></div>`).join("")}
        </div>`).join("")}
    </div>`).join("")}</div>`;
  container.querySelectorAll("[data-open]").forEach((a) => a.addEventListener("click", (ev) => {
    ev.preventDefault();
    openEntry(Number(a.dataset.open));
  }));
  document.getElementById("text-replace").addEventListener("click", () =>
    openLibraryReplace({ find: q, category, project, tag }));
}
