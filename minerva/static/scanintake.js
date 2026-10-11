// Scans tab: bring scans in from a folder outside the library, usually a
// Google Drive, Dropbox or OneDrive folder. The folder is only read; its
// scans are copied into a source's Scans folder.

const scanIntake = { folder: "", source: "", subfolders: true, timer: null, jobId: null, preview: null };

function closeScanIntake() {
  clearTimeout(scanIntake.timer);
  const el = document.getElementById("scan-intake-dialog");
  if (el) el.remove();
  document.removeEventListener("keydown", scanIntakeKeys);
}

function scanIntakeKeys(ev) {
  if (ev.key === "Escape" && !scanIntake.jobId) closeScanIntake();
}

// folder/source prefill "Check for new scans" on a source that remembers
// where it came from
async function openScanIntake({ folder = "", source = "", subfolders = true } = {}) {
  closeScanIntake();
  Object.assign(scanIntake, { folder, source, subfolders, jobId: null, preview: null });
  let found = { cloud: [], origins: {} };
  try { found = await api("/api/scan-intake/folders"); } catch (e) { /* the box still works */ }
  const el = document.createElement("div");
  el.id = "scan-intake-dialog";
  el.className = "modal-backdrop";
  el.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="si-h">
      <h2 id="si-h">Bring in scans from a folder</h2>
      <p class="hint">Pick the folder your scans are saved to, such as a folder in Google Drive, Dropbox or OneDrive that your phone's scanner app saves to. Its PDFs and photos are copied into a source in your library. Nothing in the folder is changed. Bring the same folder in again later and only new scans are copied.</p>
      ${found.cloud.length ? `<div class="si-cloud">
        <span class="muted">Start in:</span>
        ${found.cloud.map((c, i) => `<button class="btn btn-small btn-ghost" data-si-cloud="${i}" title="${esc(c.path)}">${esc(c.label)}</button>`).join("")}
      </div>` : `<div class="hint">No Google Drive, Dropbox or OneDrive folder was found on this computer. If you use one, install its desktop app so its files show up as a folder, or pick any folder below.</div>`}
      <label for="si-folder">Folder</label>
      <div class="profile-row">
        <input type="text" id="si-folder" placeholder="e.g. G:\\My Drive\\Scans" value="${esc(folder)}">
        <button class="btn btn-ghost" id="si-browse">Browse…</button>
      </div>
      <label class="check-row"><input type="checkbox" id="si-sub" ${subfolders ? "checked" : ""}> Include folders inside it</label>
      <label for="si-source" style="margin-top:10px;display:block">Source name</label>
      <input type="text" id="si-source" placeholder="The folder's name" value="${esc(source)}">
      <div id="si-preview" class="si-preview"></div>
      <div class="modal-actions">
        <span class="muted" id="si-progress"></span>
        <span style="flex:1"></span>
        <button class="btn btn-ghost" id="si-cancel">Cancel</button>
        <button class="btn btn-gold" id="si-go" disabled>Bring in</button>
      </div>
    </div>`;
  document.body.appendChild(el);
  document.addEventListener("keydown", scanIntakeKeys);

  const folderEl = document.getElementById("si-folder");
  const sourceEl = document.getElementById("si-source");
  const subEl = document.getElementById("si-sub");
  const refresh = () => { clearTimeout(scanIntake.timer); scanIntake.timer = setTimeout(previewScanIntake, 300); };
  el.querySelectorAll("[data-si-cloud]").forEach((b) => b.addEventListener("click", () => {
    folderEl.value = found.cloud[Number(b.dataset.siCloud)].path;
    refresh();
  }));
  document.getElementById("si-browse").addEventListener("click", () => pickFolder(folderEl));
  folderEl.addEventListener("change", refresh);
  folderEl.addEventListener("input", refresh);
  sourceEl.addEventListener("input", refresh);
  subEl.addEventListener("change", refresh);
  document.getElementById("si-cancel").addEventListener("click", () => {
    if (scanIntake.jobId) postJson(`/api/jobs/${scanIntake.jobId}/cancel`).catch(() => {});
    else closeScanIntake();
  });
  document.getElementById("si-go").addEventListener("click", runScanIntake);
  if (folder) previewScanIntake();
}

function scanIntakeBody() {
  return {
    folder: document.getElementById("si-folder").value.trim(),
    source: document.getElementById("si-source").value.trim(),
    subfolders: document.getElementById("si-sub").checked,
  };
}

async function previewScanIntake() {
  const out = document.getElementById("si-preview");
  const go = document.getElementById("si-go");
  if (!out) return;
  const body = scanIntakeBody();
  go.disabled = true;
  scanIntake.preview = null;
  if (!body.folder) { out.innerHTML = ""; return; }
  out.innerHTML = `<span class="muted">Looking in the folder…</span>`;
  let p;
  try { p = await postJson("/api/scan-intake/preview", body); }
  catch (e) { out.innerHTML = `<div class="hint warn">${esc(e.message)}</div>`; return; }
  if (JSON.stringify(scanIntakeBody()) !== JSON.stringify(body)) return; // typed on since
  scanIntake.preview = p;
  const src = document.getElementById("si-source");
  if (!src.value) src.placeholder = p.source;
  if (!p.files) {
    out.innerHTML = `<div class="hint">No PDFs or photos in that folder${body.subfolders ? " or the folders inside it" : ""}.</div>`;
    return;
  }
  const lines = [];
  lines.push(p.new
    ? `<b>${p.new.toLocaleString()}</b> scan${p.new === 1 ? "" : "s"} to copy (${sizeText(p.bytes)}) into ${p.source_exists ? "the existing source" : "a new source"} <b>${esc(p.source)}</b>.`
    : `All ${p.files.toLocaleString()} scans are already in <b>${esc(p.source)}</b>. Nothing new to bring in.`);
  if (p.already && p.new) lines.push(`${p.already.toLocaleString()} already there will be skipped.`);
  if (p.cloud_only) lines.push(`${p.cloud_only.toLocaleString()} ${p.cloud_only === 1 ? "is" : "are"} only in the cloud so far. Your cloud app will download ${p.cloud_only === 1 ? "it" : "them"} as ${p.cloud_only === 1 ? "it's" : "they're"} copied, which can take a while.`);
  if (p.capped) lines.push(`That's a lot of files, so only the first ${p.files.toLocaleString()} were counted. Bring in again afterwards for the rest.`);
  out.innerHTML = `<div class="hint">${lines.join("<br>")}</div>` +
    (p.sample.length ? `<ul class="si-sample">${p.sample.map((s) => `<li>${esc(s)}</li>`).join("")}${p.new > p.sample.length ? `<li class="muted">and ${(p.new - p.sample.length).toLocaleString()} more</li>` : ""}</ul>` : "");
  go.disabled = !p.new;
}

async function runScanIntake() {
  const body = scanIntakeBody();
  let job;
  try { job = await postJson("/api/scan-intake/run", body); }
  catch (e) { toast(e.message, true); return; }
  scanIntake.jobId = job.id;
  document.getElementById("si-go").disabled = true;
  ["si-folder", "si-source", "si-sub", "si-browse"].forEach((id) => { document.getElementById(id).disabled = true; });
  document.getElementById("si-cancel").textContent = "Stop";
  pollScanIntake();
}

async function pollScanIntake() {
  let j;
  try { j = await api(`/api/jobs/${scanIntake.jobId}`); } catch (e) { return; }
  const prog = document.getElementById("si-progress");
  if (j.status === "running") {
    if (prog) prog.textContent = j.total ? `${Math.round((100 * j.done) / j.total)}% · ${j.message}` : j.message;
    scanIntake.timer = setTimeout(pollScanIntake, 600);
    return;
  }
  scanIntake.jobId = null;
  closeScanIntake();
  if (j.status === "failed") { toast(`Couldn't bring the scans in: ${j.error}`, true); return; }
  const r = j.result;
  if (r) {
    let msg = `Copied ${r.copied.toLocaleString()} scan${r.copied === 1 ? "" : "s"} into ${r.source}.`;
    if (j.status === "stopped") msg = `Stopped. ${msg}`;
    if (r.failed.length) msg += ` ${r.failed.length} couldn't be copied: ${r.failed.slice(0, 3).map((f) => `${f.file} (${f.error})`).join("; ")}${r.failed.length > 3 ? "…" : ""}`;
    toast(msg, r.failed.length > 0);
    scanState.source = r.source;
    scanState.tab = "transcribe";
  }
  if (state.view === "scans") renderScans();
}
