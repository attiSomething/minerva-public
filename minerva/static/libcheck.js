// Library check: things in the library folder Minerva can't make sense of.
// Depends on helpers from app.js (api, esc, toast, setView, state, openEntry, plural).

function libraryCheckStripHtml(issues) {
  if (!issues.length) return "";
  return `<div class="backup-strip due" id="check-strip">
    <span>${plural(issues.length, "thing", "things")} in your library ${issues.length === 1 ? "needs" : "need"} a look.</span>
    <a href="#" data-goto-checks>Review</a></div>`;
}

function wireLibraryCheckStrip(root) {
  root.querySelectorAll("[data-goto-checks]").forEach((a) => a.addEventListener("click", (ev) => {
    ev.preventDefault();
    setView("checks");
  }));
}

async function renderChecks() {
  appEl.innerHTML = `<div class="empty-state">Checking your library...</div>`;
  let data;
  try {
    data = await api("/api/library/check");
  } catch (e) {
    appEl.innerHTML = `<div class="empty-state">Could not check the library: ${esc(e.message)}</div>`;
    return;
  }
  if (state.view !== "checks") return;
  const groups = {};
  data.issues.forEach((i) => { (groups[i.title] = groups[i.title] || { help: i.help, items: [] }).items.push(i); });
  appEl.innerHTML = `
    <div class="checks">
      <div class="checks-head">
        <div>
          <h2>Library check ${helpLinkHtml("checks", "How")}</h2>
          <p class="muted">Folders and files Minerva couldn't make sense of. Minerva doesn't change any of these; fix them in your library folder, then check again.</p>
        </div>
        <button class="btn" id="checks-again">Check again</button>
      </div>
      ${data.issues.length ? Object.entries(groups).map(([title, g]) => `
        <section class="panel">
          <h3>${esc(title)} <span class="count-pill">${g.items.length}</span></h3>
          <p class="hint" style="margin-top:0">${esc(g.help)}</p>
          <ul class="check-list">
            ${g.items.map((i) => `<li>
              <div><code>${esc(i.path)}</code>${i.detail ? `<div class="hint">${esc(i.detail)}</div>` : ""}</div>
              <div class="check-actions">
                ${i.entry_id ? `<button class="btn btn-ghost btn-small" data-check-open="${i.entry_id}">Open entry</button>` : ""}
                <button class="btn btn-ghost btn-small" data-check-reveal="${esc(i.path)}">Show in folder</button>
              </div>
            </li>`).join("")}
          </ul>
        </section>`).join("") : data.lost_notes.length ? "" : `<div class="panel empty-state">Everything looks good. Every entry folder has one clear current draft Minerva can read.</div>`}
      ${lostNotesHtml(data.lost_notes)}
    </div>`;
  document.getElementById("checks-again").addEventListener("click", async (ev) => {
    ev.target.disabled = true;
    try {
      await api("/api/sync", { method: "POST" });
      refreshAlertsBadge();
    } catch (e) { toast(e.message, true); }
    renderChecks();
  });
  wireLostNotes();
  appEl.querySelectorAll("[data-check-open]").forEach((b) => b.addEventListener("click", () => {
    state.view = "entries";
    document.querySelectorAll(".tab-btn").forEach((x) => x.classList.toggle("active", x.dataset.view === "entries"));
    state.returnTo = { view: "checks" };
    openEntry(Number(b.dataset.checkOpen));
  }));
  appEl.querySelectorAll("[data-check-reveal]").forEach((b) => b.addEventListener("click", async () => {
    try {
      await api("/api/library/reveal", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: b.dataset.checkReveal }) });
    } catch (e) { toast(e.message, true); }
  }));
}

// Notes whose entry Minerva can't find any more (renamed or moved outside
// Minerva). They're kept until the writer attaches them somewhere or lets
// them go.
function lostNotesHtml(lost) {
  if (!lost.length) return "";
  return `<section class="panel">
    <h3>Notes without an entry <span class="count-pill">${lost.length}</span></h3>
    <p class="hint" style="margin-top:0">Minerva kept notes for entries it can no longer find, perhaps renamed or moved outside Minerva. Attach them to the entry they belong to.</p>
    <ul class="check-list">
      ${lost.map((n) => `<li data-lost="${n.id}">
        <div style="flex:1;min-width:0"><b>${esc(n.title)}</b> <span class="hint">was <code>${esc(n.rel_path)}</code></span>
          <div class="lost-note-text">${esc(n.body.length > 400 ? n.body.slice(0, 400) + "…" : n.body)}</div>
          <div class="lost-attach" hidden>
            <input type="search" placeholder="Search entries by title..." data-lost-search>
            <div class="lost-results"></div>
          </div></div>
        <div class="check-actions">
          <button class="btn btn-ghost btn-small" data-lost-attach>Attach to entry</button>
          <button class="btn btn-ghost btn-small" data-lost-forget>Forget</button>
        </div>
      </li>`).join("")}
    </ul></section>`;
}

function wireLostNotes() {
  appEl.querySelectorAll("[data-lost]").forEach((li) => {
    const id = Number(li.dataset.lost);
    const box = li.querySelector(".lost-attach");
    const input = li.querySelector("[data-lost-search]");
    const results = li.querySelector(".lost-results");
    li.querySelector("[data-lost-attach]").addEventListener("click", () => {
      box.hidden = !box.hidden;
      if (!box.hidden) input.focus();
    });
    let timer;
    input.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        const q = input.value.trim();
        if (!q) { results.innerHTML = ""; return; }
        const found = await api(`/api/entries?search=${encodeURIComponent(q)}&page_size=8`);
        results.innerHTML = found.rows.length ? found.rows.map((e) =>
          `<button class="btn btn-ghost btn-small" data-attach-to="${e.id}">${esc(e.title)} <span class="hint">${esc(e.top_folder)}</span></button>`).join("")
          : `<div class="hint">No entries match.</div>`;
        results.querySelectorAll("[data-attach-to]").forEach((b) => b.addEventListener("click", async () => {
          try {
            await postJson(`/api/notes/lost/${id}/attach`, { entry_id: Number(b.dataset.attachTo) });
            toast("Notes attached.");
            renderChecks();
          } catch (e) { toast(e.message, true); }
        }));
      }, 250);
    });
    li.querySelector("[data-lost-forget]").addEventListener("click", async () => {
      if (!confirm("Forget these notes? They can't be brought back.")) return;
      try {
        await postJson(`/api/notes/lost/${id}/forget`, {});
        renderChecks();
      } catch (e) { toast(e.message, true); }
    });
  });
}
