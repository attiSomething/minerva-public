// Synced folders: an Obsidian vault or any folder of Markdown or text notes,
// read (never changed) each time Minerva looks. New and changed notes wait
// on Home for review; Settings > Synced folders adds folders and sets how
// their folders and tags map onto categories and tags.
// Used by home.js and onboarding.js (Settings).

// ---- Home ----------------------------------------------------------------------

function syncStripHtml(p) {
  if (!p || !(p.new + p.changed)) return "";
  const bits = [p.new ? plural(p.new, "new note", "new notes") : "", p.changed ? plural(p.changed, "changed note", "changed notes") : ""].filter(Boolean);
  return `<div class="backup-strip due sync-strip">
    <span>Your synced folders have ${bits.join(" and ")}${p.conflicts ? `, ${p.conflicts} also edited here` : ""}. Nothing changes until you review them.</span>
    <a href="#" data-sync-review>Review</a>
  </div>`;
}

function wireSyncStrip(root, refresh) {
  root.querySelectorAll("[data-sync-review]").forEach((a) => a.addEventListener("click", (ev) => {
    ev.preventDefault();
    openSyncReview(refresh);
  }));
}

// ---- review ------------------------------------------------------------------------

const syncReview = { items: [], onDone: null };

function closeSyncReview() {
  const el = document.getElementById("sync-review");
  if (el) el.remove();
  document.removeEventListener("keydown", syncReviewKeys);
}

function syncReviewKeys(ev) {
  if (ev.key === "Escape") closeSyncReview();
}

async function openSyncReview(onDone) {
  await loadCategories();
  closeSyncReview();
  syncReview.onDone = onDone || null;
  const el = document.createElement("div");
  el.id = "sync-review";
  el.className = "modal-backdrop";
  el.innerHTML = `
    <div class="modal modal-wide" role="dialog" aria-modal="true" aria-labelledby="sr-h">
      <h2 id="sr-h">New and changed notes</h2>
      <p class="hint">Ticked new notes become entries; ticked changed notes become a new version of their entry, with the old draft kept in Archive. Your notes folder is only read. ${helpLinkHtml("sync", "How syncing works")}</p>
      <div id="sr-rows"><div class="empty-state">Looking through your synced folders...</div></div>
      <div class="modal-actions">
        <span class="muted" id="sr-summary"></span>
        <span style="flex:1"></span>
        <button class="btn btn-ghost" id="sr-cancel">Not now</button>
        <button class="btn btn-gold" id="sr-go" disabled>Bring in</button>
      </div>
    </div>`;
  document.body.appendChild(el);
  document.addEventListener("keydown", syncReviewKeys);
  document.getElementById("sr-cancel").addEventListener("click", closeSyncReview);
  document.getElementById("sr-go").addEventListener("click", runSyncReview);
  let p;
  try { p = await api("/api/sync/pending"); } catch (e) { closeSyncReview(); toast(e.message, true); return; }
  syncReview.items = p.items.map((i) => Object.assign(i, {
    include: i.kind === "new" ? !i.existing_id : !i.conflict, never: false,
  }));
  renderSyncReview(p);
}

function renderSyncReview(p) {
  const box = document.getElementById("sr-rows");
  if (!box) return;
  const items = syncReview.items;
  if (!items.length) {
    box.innerHTML = `<div class="empty-state">Nothing new or changed.${p && p.missing && p.missing.length ? ` Minerva can't find ${esc(p.missing.join(", "))} right now.` : ""}</div>`;
    document.getElementById("sr-go").disabled = true;
    return;
  }
  const row = (r, i) => `
    <tr data-sr="${i}" class="${r.include ? "" : "import-skipped"}">
      <td><input type="checkbox" data-sr-include ${r.include ? "checked" : ""} ${r.never ? "disabled" : ""} aria-label="Bring in ${esc(r.title)}"></td>
      <td>${r.kind === "new"
        ? `<input type="text" data-sr-title value="${esc(r.title)}" maxlength="120" aria-label="Title">`
        : `<strong>${esc(r.entry_title)}</strong>`}
        <div class="hint">${esc(r.source)}: ${esc(r.rel_path)}</div></td>
      <td>${r.kind === "new"
        ? `<select data-sr-cat aria-label="Category">${categoryOptionsHtml(r.category)}</select>`
        : esc(r.category)}</td>
      <td>${r.tags.length ? esc(r.tags.join(", ")) : `<span class="muted">none</span>`}</td>
      <td>${r.kind === "new" ? (r.existing_id ? `<div class="fi-warn">An entry with this title already exists, so this is left unticked.</div>` : "New entry")
        : r.conflict ? `<div class="fi-warn">Also edited in Minerva since the last sync. Ticking it saves the note as the new version; your Minerva version goes to Archive.</div>`
        : "New version"}
        ${r.notes && r.notes.length ? `<div class="hint">${esc(r.notes.join("; "))}</div>` : ""}
        <div><a href="#" data-sr-never>${r.never ? "Offer it again" : "Don't offer this again"}</a></div></td>
    </tr>`;
  box.innerHTML = `<div class="import-rows"><table class="entry-table import-table">
    <thead><tr><th></th><th>Note</th><th>Category</th><th>Tags</th><th></th></tr></thead>
    <tbody>${items.map(row).join("")}</tbody></table></div>`;
  box.querySelectorAll("tr[data-sr]").forEach((tr) => {
    const r = items[Number(tr.dataset.sr)];
    tr.querySelector("[data-sr-include]").addEventListener("change", (ev) => { r.include = ev.target.checked; renderSyncReview(); });
    const t = tr.querySelector("[data-sr-title]");
    if (t) t.addEventListener("input", (ev) => { r.title = ev.target.value; });
    const c = tr.querySelector("[data-sr-cat]");
    if (c) c.addEventListener("change", (ev) => { r.category = ev.target.value; });
    tr.querySelector("[data-sr-never]").addEventListener("click", (ev) => {
      ev.preventDefault();
      r.never = !r.never;
      if (r.never) r.include = false;
      renderSyncReview();
    });
  });
  const n = items.filter((r) => r.include).length;
  const never = items.filter((r) => r.never).length;
  const go = document.getElementById("sr-go");
  go.disabled = !(n + never);
  go.textContent = n ? `Bring in ${plural(n, "note", "notes")}` : never ? "Save" : "Bring in";
  document.getElementById("sr-summary").textContent =
    `${plural(items.filter((r) => r.kind === "new").length, "new note", "new notes")}, ${plural(items.filter((r) => r.kind === "changed").length, "changed", "changed")}`;
}

async function runSyncReview() {
  const go = document.getElementById("sr-go");
  const choices = syncReview.items.filter((r) => r.include || r.never).map((r) => ({
    source_id: r.source_id, rel_path: r.rel_path,
    action: r.never ? "ignore" : r.kind === "new" ? "import" : "update",
    title: (r.title || "").trim(), category: r.category,
  }));
  go.disabled = true;
  let out;
  try { out = await postJson("/api/sync/apply", { choices }); }
  catch (e) { go.disabled = false; toast(e.message, true); return; }
  closeSyncReview();
  const bits = [out.made.length ? `${plural(out.made.length, "entry", "entries")} added` : "",
    out.updated.length ? `${plural(out.updated.length, "entry", "entries")} updated` : ""].filter(Boolean);
  toast(bits.length ? `${bits.join(", ")}.` : "Saved.");
  if (syncReview.onDone) syncReview.onDone();
}

// ---- Settings ----------------------------------------------------------------------

function syncSectionHtml(sources) {
  return `
    <section class="panel" id="synced-folders">
      <h2>Synced folders ${helpLinkHtml("sync", "How")}</h2>
      <p class="muted">Keep writing in Obsidian or another notes app? Point Minerva at the folder of Markdown or text notes. Each time you open Home, new and changed notes wait there for you to review. The folder is only read, never changed.</p>
      ${sources.length ? `<ul class="sync-list">${sources.map((s) => `
        <li data-sync="${s.id}">
          <div><strong>${esc(s.name)}</strong> <span class="muted">${esc(s.path)}</span>
            ${s.exists ? "" : `<span class="fi-warn">Can't find this folder right now.</span>`}
            <div class="hint">${plural(s.tracked, "note", "notes")} brought in · others go to ${esc(s.default_category)}</div></div>
          <div class="scan-links">
            <button class="btn btn-small btn-ghost" data-sync-map>Folders and tags...</button>
            <button class="btn btn-small btn-ghost" data-sync-stop>Stop syncing</button>
          </div>
        </li>`).join("")}</ul>
        <button class="btn btn-small" id="sync-check">Check now</button>` : ""}
      <div class="sync-add">
        <div class="path-row">
          <input type="text" id="sync-path" placeholder="C:\\Users\\you\\Documents\\Obsidian Vault" aria-label="Folder to sync">
          <button class="btn btn-ghost" type="button" id="sync-pick">Choose folder…</button>
        </div>
        <label for="sync-cat">Notes outside a matching folder go to</label>
        <select id="sync-cat">${categoryOptionsHtml("Misc")}</select>
        <button class="btn" id="sync-add">Add folder</button>
      </div>
    </section>`;
}

function wireSyncSection(refresh) {
  const sec = document.getElementById("synced-folders");
  if (!sec) return;
  document.getElementById("sync-pick").addEventListener("click", () => pickFolder(document.getElementById("sync-path")));
  document.getElementById("sync-add").addEventListener("click", async () => {
    try {
      const s = await postJson("/api/sync/sources", { path: document.getElementById("sync-path").value, category: document.getElementById("sync-cat").value });
      toast(`Syncing ${s.name}. Check how its folders and tags map before bringing notes in.`);
      await refresh();
      openSyncMapping(s.id, refresh);
    } catch (e) { toast(e.message, true); }
  });
  const check = document.getElementById("sync-check");
  if (check) check.addEventListener("click", () => openSyncReview(refresh));
  sec.querySelectorAll("li[data-sync]").forEach((li) => {
    const id = Number(li.dataset.sync);
    li.querySelector("[data-sync-map]").addEventListener("click", () => openSyncMapping(id, refresh));
    li.querySelector("[data-sync-stop]").addEventListener("click", async () => {
      if (!confirm("Stop syncing this folder? Entries already brought in stay in your library, and the folder isn't touched.")) return;
      try { await postJson(`/api/sync/sources/${id}/delete`, {}); toast("Stopped syncing."); refresh(); }
      catch (e) { toast(e.message, true); }
    });
  });
}

async function openSyncMapping(id, refresh) {
  await loadCategories();
  let ov;
  try { ov = await api(`/api/sync/sources/${id}/mapping`); } catch (e) { toast(e.message, true); return; }
  const old = document.getElementById("sync-map");
  if (old) old.remove();
  const cats = (sel, extra) => categoryOptionsHtml(sel) + (extra ? `<option value="__skip__" ${sel === "__skip__" ? "selected" : ""}>Don't bring in</option>` : "");
  const el = document.createElement("div");
  el.id = "sync-map";
  el.className = "modal-backdrop";
  el.innerHTML = `
    <div class="modal modal-wide" role="dialog" aria-modal="true" aria-labelledby="sm-h">
      <h2 id="sm-h">${esc(ov.source.name)}: folders and tags</h2>
      <p class="hint">Each top folder in ${esc(ov.source.path)} picks the category its notes go to. Tags in a note (in its front matter or written as #tag) become Minerva tags; rename one here, or clear the box to leave it out.</p>
      <div class="ne-grid">
        <div>
          <h3>Folders</h3>
          <table class="entry-table"><tbody>${ov.folders.map((f, i) => `
            <tr><td>${f.name ? esc(f.name) : `<span class="muted">(notes not in a folder)</span>`} <span class="muted">${plural(f.notes, "note", "notes")}</span></td>
              <td><select data-sm-folder="${i}" aria-label="Category for ${esc(f.name || "loose notes")}">${cats(f.category, true)}</select></td></tr>`).join("") || `<tr><td class="muted">No notes found.</td></tr>`}
          </tbody></table>
          <div class="field-row"><label for="sm-default">Anything else goes to</label><select id="sm-default">${cats(ov.source.default_category)}</select></div>
        </div>
        <div>
          <h3>Tags</h3>
          ${ov.tags.length ? `<table class="entry-table"><tbody>${ov.tags.map((t, i) => `
            <tr><td>#${esc(t.name)} <span class="muted">${plural(t.notes, "note", "notes")}</span></td>
              <td><input type="text" data-sm-tag="${i}" value="${esc(t.maps_to)}" aria-label="Minerva tag for ${esc(t.name)}" maxlength="40"></td></tr>`).join("")}
          </tbody></table>` : `<p class="muted">No tags in these notes.</p>`}
        </div>
      </div>
      <div class="modal-actions">
        <span style="flex:1"></span>
        <button class="btn btn-ghost" id="sm-cancel">Cancel</button>
        <button class="btn btn-gold" id="sm-save">Save and review notes</button>
      </div>
    </div>`;
  document.body.appendChild(el);
  const close = () => el.remove();
  el.addEventListener("keydown", (ev) => { if (ev.key === "Escape") close(); });
  document.getElementById("sm-cancel").addEventListener("click", close);
  document.getElementById("sm-save").addEventListener("click", async () => {
    const folder_map = {}, tag_map = {};
    el.querySelectorAll("[data-sm-folder]").forEach((s) => { folder_map[ov.folders[Number(s.dataset.smFolder)].name] = s.value; });
    el.querySelectorAll("[data-sm-tag]").forEach((t) => { tag_map[ov.tags[Number(t.dataset.smTag)].name] = t.value.trim(); });
    try {
      await postJson(`/api/sync/sources/${id}/mapping`, { folder_map, tag_map, default_category: document.getElementById("sm-default").value });
    } catch (e) { toast(e.message, true); return; }
    close();
    if (refresh) await refresh();
    openSyncReview(refresh);
  });
}
