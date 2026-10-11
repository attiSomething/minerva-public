// Updates: a note on Home when a new Minerva is out, what changed, and
// installing it (after a backup) on request. Settings has the switch for
// automatic checks and a Check now button.

const upd = { status: null, hidden: false, jobId: null };

// Release notes are GitHub's markdown; show the headings and lists plainly.
function releaseNotesHtml(md) {
  const lines = (md || "").replace(/\r/g, "").split("\n");
  let out = "";
  let inList = false;
  const inline = (t) => esc(t)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, "$1")
    .replace(/https?:\/\/github\.com\/\S+\/pull\/(\d+)/g, "#$1")
    .replace(/ by @[\w-]+ in #\d+$/, "")
    .replace(/ by @[\w-]+/, "");
  lines.forEach((line) => {
    const item = line.match(/^\s*[-*]\s+(.*)/);
    if (item) {
      if (!inList) { out += "<ul>"; inList = true; }
      out += `<li>${inline(item[1])}</li>`;
      return;
    }
    if (inList) { out += "</ul>"; inList = false; }
    const h = line.match(/^#{1,4}\s+(.*)/);
    if (h) out += `<h4>${inline(h[1])}</h4>`;
    else if (line.trim() && !/^\*\*Full Changelog/.test(line)) out += `<p>${inline(line)}</p>`;
  });
  return (inList ? `${out}</ul>` : out) || "<p>No notes for this version.</p>";
}

// On Home: ask (at most once a day, when automatic checks are on) and
// show a note if there's something new.
async function loadUpdateNotice(el) {
  if (!el || upd.hidden) return;
  let s;
  try { s = await postJson("/api/updates/check", {}); } catch (e) { return; }
  upd.status = s;
  if (s.ready) {
    el.innerHTML = `<div class="update-strip"><span><strong>Minerva ${esc(s.latest.version)} is downloaded.</strong> Restart to finish updating.</span>
      <span style="flex:1"></span><button class="btn btn-small btn-gold" data-upd-ready>Restart now</button></div>`;
    el.querySelector("[data-upd-ready]").addEventListener("click", () => openUpdateReady({ version: s.latest.version }));
    return;
  }
  if (!s.available || s.skipped) { el.innerHTML = ""; return; }
  el.innerHTML = `
    <div class="update-strip">
      <span><strong>Minerva ${esc(s.latest.version)} is out.</strong> You have ${esc(s.current)}.</span>
      <span style="flex:1"></span>
      <button class="btn btn-small btn-gold" data-upd-open>See what's new</button>
      <button class="btn btn-small btn-ghost" data-upd-later>Later</button>
    </div>`;
  el.querySelector("[data-upd-open]").addEventListener("click", () => openUpdate());
  el.querySelector("[data-upd-later]").addEventListener("click", () => { upd.hidden = true; el.innerHTML = ""; });
}

function closeUpdate() {
  const el = document.getElementById("update-dialog");
  if (el) el.remove();
}

async function openUpdate() {
  closeUpdate();
  let s;
  try { s = await api("/api/updates"); } catch (e) { toast(e.message, true); return; }
  upd.status = s;
  const l = s.latest;
  const el = document.createElement("div");
  el.id = "update-dialog";
  el.className = "modal-backdrop";
  el.innerHTML = `
    <div class="modal modal-wide" role="dialog" aria-modal="true" aria-labelledby="upd-h">
      <h2 id="upd-h">Minerva ${esc(l.version)}</h2>
      <div id="upd-body">
        <p class="muted">Released ${esc(l.published ? shortDate(l.published.slice(0, 10)) : "recently")}. You have ${esc(s.current)}.</p>
        <div class="release-notes">${releaseNotesHtml(l.notes)}</div>
        ${s.can_install
          ? `<p class="hint">Updating backs your library up first (when a backup folder is set), downloads the new Minerva, checks it, then closes and reopens. Your library isn't changed. The old version is kept beside the new one as Minerva.exe.old.</p>`
          : `<p class="hint">This copy of Minerva can't update itself. Download the new version from <a href="${esc(l.page || s.releases_page)}" target="_blank" rel="noopener">the releases page</a>.</p>`}
        <div class="modal-actions">
          <button class="btn btn-ghost" id="upd-skip">Skip this version</button>
          <span style="flex:1"></span>
          <button class="btn btn-ghost" id="upd-later">Later</button>
          ${s.can_install ? `<button class="btn btn-gold" id="upd-go">Update now</button>` : ""}
        </div>
      </div>
    </div>`;
  document.body.appendChild(el);
  document.getElementById("upd-later").addEventListener("click", () => { upd.hidden = true; closeUpdate(); hideUpdateStrip(); });
  document.getElementById("upd-skip").addEventListener("click", async () => {
    try { await postJson("/api/updates/prefs", { skipped: l.version }); } catch (e) { toast(e.message, true); return; }
    closeUpdate();
    hideUpdateStrip();
    toast(`Minerva won't mention ${l.version} again. Settings can still install it.`);
  });
  const go = document.getElementById("upd-go");
  if (go) go.addEventListener("click", startUpdate);
  if (s.jobs && s.jobs.length) { upd.jobId = s.jobs[0].id; pollUpdate(); }
}

function hideUpdateStrip() {
  const strip = document.getElementById("update-notice");
  if (strip) strip.innerHTML = "";
}

async function startUpdate() {
  let j;
  try { j = await postJson("/api/updates/install", {}); } catch (e) { toast(e.message, true); return; }
  upd.jobId = j.id;
  pollUpdate();
}

async function pollUpdate() {
  let j;
  try { j = await api(`/api/jobs/${upd.jobId}`); } catch (e) { return; }
  const body = document.getElementById("upd-body");
  if (j.status === "running") {
    if (body) {
      const pct = j.total ? Math.round((100 * j.done) / j.total) : null;
      body.innerHTML = `<p>Updating. Keep writing if you like; Minerva asks before it closes.</p>
        <div class="progress ${pct == null ? "indeterminate" : ""}"><div style="width:${pct == null ? 100 : pct}%"></div></div>
        <p class="muted">${esc(j.message || "Starting...")}</p>
        <div class="modal-actions"><span style="flex:1"></span><button class="btn btn-ghost" id="upd-stop">Stop</button></div>`;
      document.getElementById("upd-stop").addEventListener("click", () => postJson(`/api/jobs/${upd.jobId}/cancel`).catch(() => {}));
    }
    setTimeout(pollUpdate, 1000);
    return;
  }
  upd.jobId = null;
  if (!body) {
    if (j.status === "done") openUpdateReady(j.result);
    else if (j.status === "failed") toast(`The update stopped: ${j.error}`, true);
    return;
  }
  if (j.status === "done") { closeUpdate(); openUpdateReady(j.result); return; }
  body.innerHTML = `<p class="${j.status === "failed" ? "warn-text" : ""}">${j.status === "failed" ? esc(j.error) : "Stopped. Nothing was changed."}</p>
    <div class="modal-actions"><span style="flex:1"></span><button class="btn" id="upd-close">Close</button></div>`;
  document.getElementById("upd-close").addEventListener("click", closeUpdate);
}

function openUpdateReady(r) {
  closeUpdate();
  const el = document.createElement("div");
  el.id = "update-dialog";
  el.className = "modal-backdrop";
  el.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="upd-h">
      <h2 id="upd-h">Minerva ${esc(r.version)} is ready</h2>
      <p>${r.backup === "done" ? "Your library is backed up. " : r.backup === "skipped" ? "No backup folder is set, so there was no backup (an update doesn't change your library). " : ""}Save anything you're working on, then restart to finish. Minerva closes and opens again as ${esc(r.version)}.</p>
      <div class="modal-actions"><span style="flex:1"></span>
        <button class="btn btn-ghost" id="upd-not-yet" title="Home and Settings will offer it again">Not yet</button>
        <button class="btn btn-gold" id="upd-restart">Restart now</button></div>
    </div>`;
  document.body.appendChild(el);
  document.getElementById("upd-not-yet").addEventListener("click", closeUpdate);
  document.getElementById("upd-restart").addEventListener("click", async (ev) => {
    ev.target.disabled = true;
    try { await postJson("/api/updates/restart", {}); } catch (e) { toast(e.message, true); ev.target.disabled = false; return; }
    el.querySelector(".modal").innerHTML = `<h2>Restarting...</h2><p>Minerva ${esc(r.version)} will open in a moment.</p>`;
  });
}

// ---- Settings ------------------------------------------------------------------

async function renderUpdateSettings() {
  const box = document.getElementById("update-settings");
  if (!box) return;
  let s;
  try { s = await api("/api/updates"); } catch (e) { box.innerHTML = ""; return; }
  const checked = s.checked_at ? ` Last checked ${esc(shortDate(s.checked_at.slice(0, 10)))}.` : "";
  box.innerHTML = `
    <h2>Updates</h2>
    <p>This is Minerva ${esc(s.current)}.${s.available ? ` <strong>Version ${esc(s.latest.version)} is out.</strong>` : s.latest ? " It's the newest version." : ""}${checked}</p>
    <label class="switch-row"><input type="checkbox" id="upd-auto" ${s.auto ? "checked" : ""}>
      <span>Check for new versions once a day <span class="muted">(asks GitHub, where Minerva is published; nothing about you or your writing is sent)</span></span></label>
    <div class="save-row">
      <button class="btn btn-ghost" id="upd-check">Check now</button>
      ${s.ready ? `<button class="btn btn-gold" id="upd-ready">Restart to finish updating</button>`
        : s.available ? `<button class="btn btn-gold" id="upd-see">See what's new</button>` : ""}
    </div>`;
  document.getElementById("upd-auto").addEventListener("change", async (ev) => {
    try { await postJson("/api/updates/prefs", { auto: ev.target.checked }); } catch (e) { toast(e.message, true); }
  });
  document.getElementById("upd-check").addEventListener("click", async (ev) => {
    ev.target.disabled = true;
    try {
      const r = await postJson("/api/updates/check", { force: true });
      toast(r.available ? `Minerva ${r.latest.version} is out.` : "This is the newest Minerva.");
    } catch (e) { toast(e.message, true); }
    renderUpdateSettings();
  });
  const ready = document.getElementById("upd-ready");
  if (ready) ready.addEventListener("click", () => openUpdateReady({ version: s.latest.version }));
  const see = document.getElementById("upd-see");
  if (see) see.addEventListener("click", () => openUpdate());
}
