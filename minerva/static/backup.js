// Backups: the Settings section, the strip on Home, and running a backup.
// Depends on helpers from app.js (api, esc, toast, setView, state) and
// onboarding.js (pickFolder, jsonPost).

const backupState = { polling: null };

function agoText(iso) {
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 60) return `${days} days ago`;
  return `${Math.round(days / 30)} months ago`;
}

function sizeText(bytes) {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1e3))} KB`;
}

function lastBackupLine(b) {
  if (!b.last) return "Not backed up yet.";
  const l = b.last;
  return `Last backed up ${agoText(l.at)}${l.changes_only ? " (changes only)" : ""}: ${l.files.toLocaleString()} files, ${sizeText(l.zip_bytes)}.`;
}

function backupStripHtml(b) {
  if (b.running.length) {
    return `<div class="backup-strip" id="backup-strip"><span>Backing up… <span id="backup-progress"></span></span></div>`;
  }
  if (!b.folder) {
    return `<div class="backup-strip due" id="backup-strip">
      <span>Your writing isn't backed up yet. A backup copies your whole library to another drive or OneDrive.</span>
      <a href="#" data-backup-settings>Set up backups</a></div>`;
  }
  const label = b.due ? (b.last ? `It's been a while. ${lastBackupLine(b)}` : "Your writing isn't backed up yet.") : lastBackupLine(b);
  return `<div class="backup-strip ${b.due ? "due" : ""}" id="backup-strip">
    <span>${esc(label)}</span>
    <button class="btn ${b.due ? "btn-gold" : "btn-ghost"} btn-small" data-backup-now>Back up now</button></div>`;
}

function wireBackupStrip(root, rerender) {
  root.querySelectorAll("[data-backup-settings]").forEach((a) => a.addEventListener("click", (ev) => {
    ev.preventDefault();
    state.scrollTo = "backup";
    setView("settings");
  }));
  root.querySelectorAll("[data-backup-now]").forEach((b) => b.addEventListener("click", () => runBackup(false, rerender)));
}

function backupSectionHtml(b) {
  const remind = b.remind_choices.map((d) => `<option value="${d}" ${d === b.remind_days ? "selected" : ""}>${
    d === 0 ? "Never" : d === 1 ? "Every day" : `Every ${d} days`}</option>`).join("");
  return `
    <section class="panel" id="backup">
      <h2>Backups ${helpLinkHtml("backups", "How")}</h2>
      <p class="muted">A backup copies your whole library into one dated zip file in a folder you choose. Pick somewhere off this drive, like OneDrive, an external drive or a USB stick. Old backups are never overwritten or deleted.</p>
      <label for="backup-folder">Backup folder</label>
      <div class="profile-row">
        <input type="text" id="backup-folder" placeholder="e.g. D:\\Backups" value="${esc(b.folder)}">
        <button class="btn btn-ghost" id="backup-browse">Browse…</button>
        <button class="btn" id="backup-folder-save">Save</button>
      </div>
      ${b.folder && !b.folder_ok ? `<div class="hint warn">That folder isn't available right now. Is the drive plugged in?</div>` : ""}
      <label for="backup-remind" style="margin-top:14px;display:block">Remind me on Home</label>
      <select id="backup-remind">${remind}</select>
      <p id="backup-last" style="margin-top:14px">${esc(lastBackupLine(b))}${b.last ? `<br><span class="hint">${esc(b.last.file)}</span>` : ""}</p>
      <div class="profile-row">
        <button class="btn btn-gold" id="backup-run" ${b.folder_ok ? "" : "disabled"}>Back up now</button>
        <button class="btn btn-ghost" id="backup-run-changes" ${b.folder_ok && b.last ? "" : "disabled"}
          title="Only files changed since the last backup. Quicker, but restoring needs the last full backup too.">Changes only</button>
        <span id="backup-progress" class="muted"></span>
      </div>
    </section>`;
}

function wireBackupSection(rerender) {
  const folder = document.getElementById("backup-folder");
  const saveFolder = async () => {
    try {
      await jsonPost("/api/backup/settings", { folder: folder.value });
      toast(folder.value ? "Backup folder saved." : "Backup folder cleared.");
      rerender();
    } catch (e) { toast(e.message, true); }
  };
  document.getElementById("backup-browse").addEventListener("click", async () => {
    const before = folder.value;
    await pickFolder(folder);
    if (folder.value && folder.value !== before) saveFolder();
  });
  document.getElementById("backup-folder-save").addEventListener("click", saveFolder);
  folder.addEventListener("keydown", (ev) => { if (ev.key === "Enter") saveFolder(); });
  document.getElementById("backup-remind").addEventListener("change", async (ev) => {
    try {
      await jsonPost("/api/backup/settings", { remind_days: Number(ev.target.value) });
      toast("Saved.");
    } catch (e) { toast(e.message, true); }
  });
  document.getElementById("backup-run").addEventListener("click", () => runBackup(false, rerender));
  document.getElementById("backup-run-changes").addEventListener("click", () => runBackup(true, rerender));
}

async function runBackup(changesOnly, onDone) {
  let job;
  try {
    job = await jsonPost("/api/backup/run", { changes_only: changesOnly });
  } catch (e) {
    toast(e.message, true);
    return;
  }
  document.querySelectorAll("[data-backup-now], #backup-run, #backup-run-changes").forEach((b) => { b.disabled = true; });
  pollBackup(job.id, onDone);
}

async function pollBackup(id, onDone) {
  clearTimeout(backupState.polling);
  let j;
  try { j = await api(`/api/jobs/${id}`); } catch (e) { return; }
  const el = document.getElementById("backup-progress");
  if (j.status === "running") {
    if (el) el.textContent = j.total ? `${Math.round((100 * j.done) / j.total)}%` : "";
    backupState.polling = setTimeout(() => pollBackup(id, onDone), 700);
    return;
  }
  if (j.status === "done") {
    toast(`Backed up ${j.result.files.toLocaleString()} files (${sizeText(j.result.zip_bytes)}).`);
  } else if (j.status === "failed") {
    toast(`Backup failed: ${j.error}`, true);
  }
  if (onDone) onDone();
}

// pick up a backup that was already running when the page was drawn
function resumeBackupPolling(b, onDone) {
  if (b.running.length) pollBackup(b.running[0].id, onDone);
}
