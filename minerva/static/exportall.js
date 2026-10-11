// Export everything: all the writing plus what Minerva knows about it, in
// open formats, as a .zip or a folder. Lives in Settings beside Backups.

HELP_TOPICS["export-everything"] = { kind: "doc", name: BASICS, anchor: "Export everything" };

const xall = { jobId: null };

async function renderExportAllSettings() {
  const box = document.getElementById("export-all-settings");
  if (!box) return;
  let s;
  try { s = await api("/api/export-all"); } catch (e) { box.innerHTML = ""; return; }
  box.innerHTML = `
    <h2>Export everything ${helpLinkHtml("export-everything", "What an export holds")}</h2>
    <p class="muted">Every file in your library, plus your notes, tags, projects, outlines, submissions and the rest as spreadsheets (CSV) and plain text, with a README saying what each file is. It opens without Minerva, so your work is never locked in. Your library isn't changed.</p>
    <label for="xall-folder">Save it in</label>
    <div class="profile-row">
      <input type="text" id="xall-folder" placeholder="e.g. D:\\Exports" value="${esc(s.folder)}">
      <button class="btn btn-ghost" id="xall-browse">Browse…</button>
    </div>
    <div class="xall-as" role="radiogroup" aria-label="Export as">
      <label><input type="radio" name="xall-as" value="zip" ${s.zip ? "checked" : ""}> One .zip file</label>
      <label><input type="radio" name="xall-as" value="folder" ${s.zip ? "" : "checked"}> A folder</label>
    </div>
    <label class="switch-row"><input type="checkbox" id="xall-media" ${s.media ? "checked" : ""}>
      <span>Include scans, pictures and recordings <span class="muted">(much bigger)</span></span></label>
    <div class="profile-row">
      <button class="btn btn-gold" id="xall-go">Export everything</button>
      <button class="btn btn-ghost hidden" id="xall-stop">Stop</button>
    </div>
    <div id="xall-progress"></div>`;
  const folder = document.getElementById("xall-folder");
  document.getElementById("xall-browse").addEventListener("click", () => pickFolder(folder));
  document.getElementById("xall-go").addEventListener("click", startExportAll);
  document.getElementById("xall-stop").addEventListener("click", () => {
    if (xall.jobId) postJson(`/api/jobs/${xall.jobId}/cancel`).catch(() => {});
  });
  if (s.running && s.running.length) { xall.jobId = s.running[0].id; exportAllRunning(true); pollExportAll(); }
}

function exportAllRunning(on) {
  const go = document.getElementById("xall-go");
  const stop = document.getElementById("xall-stop");
  if (go) go.disabled = on;
  if (stop) stop.classList.toggle("hidden", !on);
}

async function startExportAll() {
  const folder = document.getElementById("xall-folder").value.trim();
  if (!folder) { toast("Choose a folder to save the export in.", true); return; }
  const asZip = document.querySelector('input[name="xall-as"]:checked').value === "zip";
  const media = document.getElementById("xall-media").checked;
  let j;
  try { j = await postJson("/api/export-all", { folder, zip: asZip, media }); } catch (e) { toast(e.message, true); return; }
  xall.jobId = j.id;
  exportAllRunning(true);
  pollExportAll();
}

async function pollExportAll() {
  let j;
  try { j = await api(`/api/jobs/${xall.jobId}`); } catch (e) { return; }
  const out = document.getElementById("xall-progress");
  if (j.status === "running") {
    if (out) {
      const pct = j.total ? Math.round((100 * j.done) / j.total) : null;
      out.innerHTML = `<div class="progress ${pct == null ? "indeterminate" : ""}"><div style="width:${pct == null ? 100 : pct}%"></div></div>
        <p class="muted">${esc(j.message || "Starting...")}</p>`;
    }
    setTimeout(pollExportAll, 700);
    return;
  }
  xall.jobId = null;
  exportAllRunning(false);
  if (!out) {
    if (j.status === "done") toast(`Exported to ${j.result.name}.`);
    return;
  }
  if (j.status === "done") {
    const r = j.result;
    out.innerHTML = `<p><strong>Done.</strong> ${r.files.toLocaleString()} files from your library and ${r.records} records, in <code>${esc(r.path)}</code>.</p>
      <button class="btn btn-ghost btn-small" id="xall-show">Show in folder</button>`;
    document.getElementById("xall-show").addEventListener("click", () =>
      postJson("/api/export-all/reveal", {}).catch((e) => toast(e.message, true)));
  } else if (j.status === "failed") {
    out.innerHTML = `<p class="warn-text">${esc(j.error)}</p>`;
  } else {
    out.innerHTML = `<p class="muted">Stopped. Nothing was left behind.</p>`;
  }
}
