// Scans tab: transcribe scanned pages with the user's model, build the
// Master, proofread it side by side with the page, and file entries.

const scanState = {
  source: null,
  tab: "transcribe",
  master: null,
  current: null,
  page: null,      // [scan, page] shown in the proofreader
  together: false, // show all of an entry's pages at once
  dirty: false,
  pollTimer: null,
  aiStatus: null,
  fileOnlyReviewed: false,
  fileHideFiled: false,
};

function postJson(path, body) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
}

function srcPath(name) {
  return `/api/scans/${encodeURIComponent(name)}`;
}

function confirmDiscard() {
  return !scanState.dirty || confirm("You have unsaved changes to this entry. Discard them?");
}

function openEntryFromScans(id) {
  state.view = "entries";
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === "entries"));
  openEntry(id);
}

// Opens the Scans tab's proofreader on one entry, where its pages can be changed.
function openScanEntry(source, num) {
  Object.assign(scanState, { source, tab: "proofread", master: null, current: Number(num), page: null, dirty: false });
  setView("scans");
}

// A pop-over showing an entry's pages, one at a time or all together.
function openPageViewer(source, pages, names) {
  let i = 0;
  let together = false;
  const box = document.createElement("div");
  box.className = "page-viewer";
  const close = () => { box.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = (ev) => {
    if (ev.key === "Escape") close();
    else if (!together && ev.key === "ArrowRight" && i < pages.length - 1) { i++; draw(); }
    else if (!together && ev.key === "ArrowLeft" && i > 0) { i--; draw(); }
  };
  function draw() {
    box.innerHTML = `
      <div class="page-viewer-box">
        <div class="page-controls">
          ${together ? `<span>All ${pages.length} pages</span>` : `
            <button class="btn btn-small btn-ghost" data-pv="prev" ${i === 0 ? "disabled" : ""}>&larr;</button>
            <span>${esc(names[i])}${pages.length > 1 ? ` (${i + 1} of ${pages.length})` : ""}</span>
            <button class="btn btn-small btn-ghost" data-pv="next" ${i === pages.length - 1 ? "disabled" : ""}>&rarr;</button>`}
          <span class="spacer"></span>
          ${pages.length > 1 ? `<button class="btn btn-small btn-ghost" data-pv="together">${together ? "One page at a time" : "All pages together"}</button>` : ""}
          <button class="btn btn-small" data-pv="close">Close</button>
        </div>
        <div class="page-frame ${together ? "page-stack" : ""}">
          ${(together ? pages.map((p, k) => [p, k]) : [[pages[i], i]]).map(([p, k]) =>
            `${together ? `<div class="stack-label">${esc(names[k])}</div>` : ""}<img src="${pageUrl(source, p)}" alt="Scanned page" loading="lazy">`).join("")}
        </div>
      </div>`;
    box.querySelectorAll("img").forEach((img) => img.addEventListener("click", () => img.classList.toggle("zoomed")));
    box.querySelectorAll("[data-pv]").forEach((b) => b.addEventListener("click", () => {
      const a = b.dataset.pv;
      if (a === "close") return close();
      if (a === "prev") i--;
      if (a === "next") i++;
      if (a === "together") together = !together;
      draw();
    }));
  }
  box.addEventListener("click", (ev) => { if (ev.target === box) close(); });
  document.addEventListener("keydown", onKey);
  document.body.appendChild(box);
  draw();
}

async function renderScans() {
  clearTimeout(scanState.pollTimer);
  let data;
  try {
    [data, scanState.aiStatus] = await Promise.all([api("/api/scans"), api("/api/ai/status")]);
  } catch (e) {
    appEl.innerHTML = `<div class="empty-state">${esc(e.message)}</div>`;
    return;
  }
  if (scanState.source && !data.sources.some((s) => s.name === scanState.source)) scanState.source = null;
  if (!scanState.source && data.sources.length) scanState.source = data.sources[0].name;

  appEl.innerHTML = `
    <div class="scan-layout">
      <aside class="scan-sources">
        <h3>Sources ${helpLinkHtml("scans", "How")}</h3>
        <div class="hint" style="margin-top:0">A source is anything you've scanned or photographed: a journal, a notebook, letters, old printouts or documents. Each one is a folder inside <b>${esc(data.scans_dir)}</b> with its PDFs or photos in a Scans folder.</div>
        <div id="source-list">
          ${data.sources.length ? data.sources.map(sourceCardHtml).join("") :
            `<div class="hint">No sources yet. Bring scans in from a folder (Google Drive, Dropbox or OneDrive work too), or create one below and put its scans in its Scans folder.</div>`}
        </div>
        ${data.loose_files ? `<div class="hint warn-text">${data.loose_files} file${data.loose_files === 1 ? "" : "s"} sit directly in ${esc(data.scans_dir)}. Move them into a source folder to work with them.</div>` : ""}
        <div class="new-source">
          <input type="text" id="new-source-name" placeholder="New source, e.g. Old Letters">
          <button class="btn btn-small" id="new-source-btn">Add</button>
        </div>
        <button class="btn btn-small btn-ghost si-open" id="scan-intake-btn" title="Copy scans in from Google Drive, Dropbox, OneDrive or any folder">Bring in scans from a folder…</button>
      </aside>
      <section class="scan-detail" id="scan-detail"></section>
    </div>`;

  document.querySelectorAll("[data-source]").forEach((el) =>
    el.addEventListener("click", () => {
      if (!confirmDiscard()) return;
      scanState.dirty = false;
      scanState.source = el.dataset.source;
      scanState.master = null;
      scanState.current = null;
      renderScans();
    }));
  scanState.origins = data.origins || {};
  document.getElementById("scan-intake-btn").addEventListener("click", () => openScanIntake());
  document.getElementById("new-source-btn").addEventListener("click", async () => {
    const name = document.getElementById("new-source-name").value.trim();
    if (!name) return;
    try {
      await postJson("/api/scans", { name });
      scanState.source = name;
      toast(`Created ${name}. Put its scans in ${data.scans_dir}\\${name}\\Scans, then refresh.`);
      renderScans();
    } catch (e) { toast(e.message, true); }
  });

  if (scanState.source) await renderSourceDetail();
  else document.getElementById("scan-detail").innerHTML =
    `<div class="empty-state">Add a source to start transcribing.</div>`;
}

function sourceCardHtml(s) {
  const bits = [`${s.scans} scan${s.scans === 1 ? "" : "s"}`];
  if (s.has_master) bits.push(`${s.entries} entries`, `${s.reviewed} reviewed`, `${s.filed} filed`);
  else if (s.transcribed) bits.push(`${s.transcribed} transcribed`);
  return `<button class="source-card ${s.name === scanState.source ? "active" : ""}" data-source="${esc(s.name)}">
    <span class="source-name">${esc(s.name)}</span>
    <span class="source-meta">${bits.join(" · ")}</span>
  </button>`;
}

async function renderSourceDetail() {
  const el = document.getElementById("scan-detail");
  const tabs = [["transcribe", "Transcribe"], ["proofread", "Proofread"], ["file", "File entries"]];
  el.innerHTML = `
    <div class="scan-detail-head">
      <div class="scan-title">
        <h2>${esc(scanState.source)}</h2>
        ${(scanState.origins || {})[scanState.source] ? `<button class="btn btn-small btn-ghost" id="scan-check-new" title="${esc(scanState.origins[scanState.source].folder)}">Check for new scans</button>` : ""}
      </div>
      <div class="dup-tabs">
        ${tabs.map(([k, label]) => `<button class="btn btn-small ${scanState.tab === k ? "" : "btn-ghost"}" data-scan-tab="${k}">${label}</button>`).join("")}
      </div>
    </div>
    <div id="scan-tab"></div>`;
  const checkNew = document.getElementById("scan-check-new");
  if (checkNew) checkNew.addEventListener("click", () => {
    const o = scanState.origins[scanState.source];
    openScanIntake({ folder: o.folder, source: scanState.source, subfolders: o.subfolders !== false });
  });
  el.querySelectorAll("[data-scan-tab]").forEach((b) =>
    b.addEventListener("click", () => {
      if (!confirmDiscard()) return;
      scanState.dirty = false;
      scanState.tab = b.dataset.scanTab;
      renderSourceDetail();
    }));
  if (scanState.tab === "transcribe") await renderTranscribeTab();
  else if (scanState.tab === "proofread") await renderProofreadTab();
  else await renderFileTab();
}

function aiBanner(feature) {
  const st = scanState.aiStatus && scanState.aiStatus[feature];
  if (!st || st.ready) return "";
  return `<div class="ai-banner">${esc(st.reason)} <button class="btn btn-small btn-ghost" data-goto-settings>Open Settings</button>
    <div class="hint">Two ways to turn it on: <a href="#" data-help="ai-local">run a model on your computer</a> (free and private) or <a href="#" data-help="ai-service">use an AI service</a> (pennies per use).</div></div>`;
}

function wireSettingsLinks(root) {
  root.querySelectorAll("[data-goto-settings]").forEach((b) => b.addEventListener("click", () => setView("settings")));
}

// -------------------------------------------------------------------------
// Transcribe
// -------------------------------------------------------------------------

async function renderTranscribeTab() {
  const el = document.getElementById("scan-tab");
  el.innerHTML = `<div class="empty-state">Reading scans...</div>`;
  let st;
  try { st = await api(`${srcPath(scanState.source)}/status`); }
  catch (e) { el.innerHTML = `<div class="empty-state">${esc(e.message)}</div>`; return; }

  const ready = scanState.aiStatus.scanning.ready;
  const job = (st.jobs || []).find((j) => j.label === scanState.source) || (st.jobs || [])[0];
  const addable = st.scans.filter((s) => !s.in_master && s.pages && s.transcribed_pages >= s.pages);
  const ai = scanState.aiStatus.scanning;
  const ocr = !!ai.builtin_ocr;

  el.innerHTML = `
    ${aiBanner("scanning")}
    ${st.scans.length === 0 ? `<div class="empty-state">No scans yet. Put PDFs or photos in <b>${esc(st.folder)}\\Scans</b> and come back.</div>` : `
    <table class="entry-table scan-table">
      <thead><tr><th style="width:28px"><input type="checkbox" id="scan-all"></th><th>Scan</th><th>Pages</th><th>Transcribed</th><th>Text file</th><th></th></tr></thead>
      <tbody>
        ${st.scans.map((s) => `
          <tr>
            <td><input type="checkbox" class="scan-pick" value="${s.num}" ${s.transcribed_pages >= s.pages && s.pages ? "" : "checked"} ${s.error ? "disabled" : ""}></td>
            <td>${esc(s.filename)}</td>
            <td>${s.error ? `<span class="warn-text">${esc(s.error)}</span>` : s.pages}</td>
            <td>${s.pages ? `${s.transcribed_pages} / ${s.pages}` : ""}</td>
            <td class="muted">${esc(s.text_output || "")}</td>
            <td>${s.in_master ? '<span class="badge badge-project">In Master</span>' : ""}</td>
          </tr>`).join("")}
      </tbody>
    </table>
    <div class="scan-actions">
      <button class="btn" id="transcribe-btn" ${(ready || ocr) && !job ? "" : "disabled"}>${ready ? "Transcribe selected" : ocr ? "Read typed pages" : "Transcribe selected"}</button>
      <label class="filter-check" style="margin:0"><input type="checkbox" id="redo-pages"> Redo pages already transcribed</label>
      <span class="spacer"></span>
      <button class="btn btn-gold" id="master-btn" ${addable.length && !job ? "" : "disabled"}>${st.has_master ? `Add ${addable.length || ""} new scan${addable.length === 1 ? "" : "s"} to the Master` : "Build the Master"}</button>
    </div>
    <div class="hint" id="scan-estimate"></div>
    ${ocr ? `<div class="hint">${ready
      ? "Each page is read first by Windows' built-in text recognition, free and offline. Pages that read like typed text are kept from that; handwritten ones go on to your model."
      : "AI-assisted scanning is off, so Minerva reads typed pages with Windows' built-in text recognition, free and offline. Handwritten pages are left for when AI is on, and you can still type them up yourself."}</div>` : ""}
    ${ready ? `<div class="hint">${ocr ? "The rest are" : "Each page is"} sent to ${esc(ai.provider_label || ai.provider)}${ai.model ? " (" + esc(ai.model) + ")" : ""} as ${ocr ? "images" : "an image"}, and your provider bills you for it. Finished pages are kept, so stopping and starting again never pays twice.</div>` : ""}
    <div id="job-box"></div>
    <div class="hint">The Master combines finished scans into numbered entries, joining pages the model marked as continuing, with notes on hard-to-read words at the end. ${st.has_master ? "Your current Master is backed up in the library's .minerva folder before anything is added." : ""}</div>
    `}`;
  wireSettingsLinks(el);
  if (!st.scans.length) return;

  const picked = () => ({
    scans: [...el.querySelectorAll(".scan-pick:checked")].map((c) => Number(c.value)),
    redo: document.getElementById("redo-pages").checked,
  });
  let estimate = null;
  const refreshEstimate = async () => {
    const body = picked();
    const box = document.getElementById("scan-estimate");
    estimate = null;
    if (!ready || !body.scans.length) { box.textContent = ""; return; }
    try { estimate = await postJson(`${srcPath(scanState.source)}/estimate`, body); }
    catch (e) { box.textContent = ""; return; }
    box.innerHTML = `${esc(estimateText(estimate))}${estimate.builtin_ocr && estimate.pages ? " Typed pages are read free first, so it may cost less." : ""} ${aiCostLinksHtml()}`;
  };
  el.addEventListener("change", (ev) => {
    if (ev.target.matches(".scan-pick, #scan-all, #redo-pages")) refreshEstimate();
  });
  refreshEstimate();

  document.getElementById("scan-all").addEventListener("change", (ev) =>
    el.querySelectorAll(".scan-pick:not([disabled])").forEach((c) => { c.checked = ev.target.checked; }));
  document.getElementById("transcribe-btn").addEventListener("click", async () => {
    const { scans, redo } = picked();
    if (!scans.length) { toast("Choose at least one scan.", true); return; }
    try {
      if (ready) {
        const est = estimate || await postJson(`${srcPath(scanState.source)}/estimate`, { scans, redo });
        if (est.confirm && !await aiConfirm(estimateText(est), "Start transcribing")) return;
      }
      const j = await postJson(`${srcPath(scanState.source)}/transcribe`, { scans, redo });
      pollJob(j.id);
    } catch (e) { toast(e.message, true); }
  });
  document.getElementById("master-btn").addEventListener("click", async () => {
    try {
      const r = await postJson(`${srcPath(scanState.source)}/master`, {});
      toast(r.created ? `Master created with ${r.added} entries.` : `Added ${r.added} entries to the Master.`);
      scanState.master = null;
      renderScans();
    } catch (e) { toast(e.message, true); }
  });
  if (job) pollJob(job.id);
}

function estimateText(est) {
  if (!est.pages) return "Every page selected is already transcribed.";
  const pages = `${est.pages.toLocaleString()} page${est.pages === 1 ? "" : "s"}`;
  const total = est.input_tokens + est.output_tokens;
  const tokens = total >= 1e6 ? `about ${(total / 1e6).toFixed(1)} million tokens` : `about ${Math.max(1, Math.round(total / 1000)).toLocaleString()}k tokens`;
  const basis = est.measured_pages ? `based on the ${est.measured_pages} pages read so far` : "a rough guess until a few pages are read";
  if (est.cost == null) return `This sends ${pages} to your model, ${tokens} (${basis}).`;
  const cost = est.cost < 0.01 ? "under 1 cent" : `about $${est.cost.toFixed(2)}`;
  return `This sends ${pages} to your model, ${tokens}, ${cost} at the provider's list price (${basis}).`;
}

async function pollJob(id) {
  clearTimeout(scanState.pollTimer);
  const box = document.getElementById("job-box");
  if (!box) return;
  let j;
  try { j = await api(`/api/jobs/${id}`); } catch (e) { return; }
  const pct = j.total ? Math.round((100 * j.done) / j.total) : 0;
  box.innerHTML = `
    <div class="job-box">
      <div class="job-head"><b>${j.status === "running" ? "Transcribing" : j.status === "done" ? "Finished" : j.status === "stopped" ? "Stopped" : "Couldn't finish"}</b> ${esc(j.label)}
        ${j.status === "running" ? `<button class="btn btn-small btn-ghost" id="job-stop">Stop after this page</button>` : ""}</div>
      <div class="progress"><div style="width:${j.status === "done" ? 100 : pct}%"></div></div>
      <div class="hint">${esc(j.error || j.message || "")}</div>
    </div>`;
  const stop = document.getElementById("job-stop");
  if (stop) stop.addEventListener("click", async () => {
    stop.disabled = true;
    await postJson(`/api/jobs/${id}/cancel`);
  });
  if (j.status === "running") {
    scanState.pollTimer = setTimeout(() => pollJob(id), 1500);
  } else {
    if (j.status === "done") toast(transcribeDoneText(j.result));
    else if (j.status === "failed") toast(j.error || "Transcription stopped with an error.", true);
    setTimeout(() => { if (state.view === "scans" && scanState.tab === "transcribe") renderScans(); }, 1200);
  }
}

function transcribeDoneText(r) {
  const p = (r && r.pages) || {};
  if (!p.free && !p.left) return "Transcription finished.";
  const bits = [];
  if (p.free) bits.push(`${plural(p.free, "typed page", "typed pages")} read free`);
  if (p.ai) bits.push(`${plural(p.ai, "page", "pages")} read by your model`);
  if (p.left) bits.push(`${plural(p.left, "page looks", "pages look")} handwritten and ${p.left === 1 ? "was" : "were"} left for AI`);
  return `Finished: ${bits.join(", ")}.`;
}

// -------------------------------------------------------------------------
// Proofread
// -------------------------------------------------------------------------

async function loadMaster() {
  scanState.master = await api(`${srcPath(scanState.source)}/master`);
  return scanState.master;
}

function entryLabel(e) {
  if (e.title) return e.title;
  const line = (e.body || "").split("\n").find((l) => l.trim()) || "";
  return line.length > 48 ? line.slice(0, 48) + "…" : line;
}

async function renderProofreadTab() {
  const el = document.getElementById("scan-tab");
  try { if (!scanState.master) await loadMaster(); }
  catch (e) {
    el.innerHTML = `<div class="empty-state">${esc(e.message)} Transcribe some scans and build the Master first.</div>`;
    return;
  }
  const m = scanState.master;
  if (!m.entries.length) { el.innerHTML = `<div class="empty-state">The Master has no entries.</div>`; return; }
  if (!scanState.current || !m.entries.some((e) => e.num === scanState.current)) {
    const firstOpen = m.entries.find((e) => !e.reviewed) || m.entries[0];
    scanState.current = firstOpen.num;
    scanState.page = null;
  }
  const reviewed = m.entries.filter((e) => e.reviewed).length;
  el.innerHTML = `
    <div class="proof-layout">
      <div class="proof-list">
        <div class="hint" style="margin:0 0 6px">${reviewed} of ${m.entries.length} reviewed
          <button class="link-btn" id="rematch-btn" title="Find each entry's pages again from its text. Pages you set by hand are kept.">Match pages again</button></div>
        <div id="proof-entries">
          ${m.entries.map((e) => `
            <button class="proof-row ${e.num === scanState.current ? "active" : ""} ${e.reviewed ? "reviewed" : ""}" data-num="${e.num}">
              <span class="proof-num">${e.num}</span>
              <span class="proof-title">${esc(entryLabel(e))}</span>
              ${e.notes.length ? '<span class="note-dot" title="Has notes on hard-to-read words"></span>' : ""}
            </button>`).join("")}
        </div>
      </div>
      <div class="proof-page" id="proof-page"></div>
      <div class="proof-edit" id="proof-edit"></div>
    </div>`;
  el.querySelectorAll(".proof-row").forEach((b) =>
    b.addEventListener("click", () => {
      if (!confirmDiscard()) return;
      scanState.dirty = false;
      scanState.current = Number(b.dataset.num);
      scanState.page = null;
      renderProofreadTab();
    }));
  document.getElementById("rematch-btn").addEventListener("click", async () => {
    if (!confirm("Find every entry's pages again from its text? Pages you chose by hand stay as they are.")) return;
    try {
      const r = await postJson(`${srcPath(scanState.source)}/rematch`, {});
      const sure = (r.methods.matched || 0) + (r.methods.transcribed || 0) + (r.methods.manual || 0);
      toast(`Pages found for ${sure} of ${r.entries} entries.` + (r.methods.label ? ` ${r.methods.label} use their label's page as a guess.` : ""));
      scanState.master = null;
      scanState.page = null;
      renderProofreadTab();
    } catch (err) { toast(err.message, true); }
  });
  const active = el.querySelector(".proof-row.active");
  if (active) active.scrollIntoView({ block: "nearest" });
  renderProofPage();
  renderProofEditor();
}

function currentEntry() {
  return scanState.master.entries.find((e) => e.num === scanState.current);
}

// Pages are [scan, page] pairs. An entry's pages can run from one scan file
// into the next, and a page can hold several entries.
function samePage(a, b) { return a && b && a[0] === b[0] && a[1] === b[1]; }

function pageName(m, p) {
  return `${m.scans[p[0]] || "Scan " + p[0]}, page ${p[1]}`;
}

function pageUrl(source, p) {
  return `${srcPath(source)}/page/${p[0]}/${p[1]}.jpg`;
}

// The page before or after p in the source, crossing into the next scan file.
function stepPage(m, p, dir) {
  const nums = Object.keys(m.scans).map(Number).sort((x, y) => x - y);
  const count = (n) => m.scan_pages[n] || 1;
  let [scan, page] = p;
  page += dir;
  if (page < 1) {
    const i = nums.indexOf(scan) - 1;
    if (i < 0) return null;
    scan = nums[i]; page = count(scan);
  } else if (page > count(scan)) {
    const i = nums.indexOf(scan) + 1;
    if (i >= nums.length) return null;
    scan = nums[i]; page = 1;
  }
  return [scan, page];
}

function entriesOnPage(m, p) {
  return m.entries.filter((x) => (x.pages || []).some((q) => samePage(q, p)));
}

function renderProofPage() {
  const e = currentEntry();
  const m = scanState.master;
  const el = document.getElementById("proof-page");
  const nums = Object.keys(m.scans).map(Number);
  if (!nums.length) {
    el.innerHTML = `<div class="empty-state">This source has no scan files.</div>`;
    return;
  }
  const pages = (e.pages || []).filter((p) => m.scans[p[0]]);
  if (!scanState.page || !m.scans[scanState.page[0]]) scanState.page = pages[0] || [Math.min(...nums), 1];
  const view = scanState.page;
  const linked = pages.findIndex((p) => samePage(p, view));
  const together = scanState.together && pages.length > 1;
  const others = entriesOnPage(m, view).filter((x) => x.num !== e.num);

  el.innerHTML = `
    <div class="entry-pages">
      <span class="muted">Entry ${e.num} is on</span>
      ${pages.map((p, i) => `<button class="page-chip ${!together && i === linked ? "active" : ""}" data-chip="${i}" title="${esc(pageName(m, p))}">${p[0] !== pages[0][0] || nums.length > 1 ? `Scan ${p[0]} · ` : ""}p. ${p[1]}</button>`).join("") ||
        '<span class="warn-text">no pages yet</span>'}
      ${pages.length > 1 ? `<button class="btn btn-small btn-ghost" id="pg-together">${together ? "One page at a time" : "All pages together"}</button>` : ""}
    </div>
    ${e.link && e.link.note ? `<div class="hint warn-text page-note">${esc(e.link.note)}</div>` : ""}
    ${together ? `
      <div class="page-frame page-stack">
        ${pages.map((p) => `<div class="stack-label">${esc(pageName(m, p))}</div><img src="${pageUrl(scanState.source, p)}" alt="Scanned page" loading="lazy">`).join("")}
      </div>` : `
    <div class="page-controls">
      <button class="btn btn-small btn-ghost" id="pg-prev" title="Previous page in this source">&larr;</button>
      <span>${esc(pageName(m, view))}</span>
      <button class="btn btn-small btn-ghost" id="pg-next" title="Next page in this source">&rarr;</button>
      <span class="spacer"></span>
      ${linked >= 0
        ? `<button class="btn btn-small btn-ghost" id="pg-unlink" ${pages.length < 2 ? 'disabled title="An entry needs at least one page."' : 'title="Take this page out of the entry"'}>Remove page</button>`
        : `<button class="btn btn-small" id="pg-link" title="This entry continues on this page">Add page</button>`}
      <a class="btn btn-small btn-ghost" href="${pageUrl(scanState.source, view)}" target="_blank" rel="noopener">Open</a>
    </div>
    ${others.length ? `<div class="page-others">Also on this page: ${others.map((x) => `<a href="#" data-goto="${x.num}">Entry ${x.num}</a>`).join(", ")}</div>` : ""}
    <div class="page-frame"><img id="page-img" src="${pageUrl(scanState.source, view)}" alt="Scanned page"></div>`}`;

  el.querySelectorAll("[data-chip]").forEach((b) => b.addEventListener("click", () => {
    scanState.together = false;
    scanState.page = pages[Number(b.dataset.chip)];
    renderProofPage();
  }));
  const tog = document.getElementById("pg-together");
  if (tog) tog.addEventListener("click", () => { scanState.together = !together; renderProofPage(); });
  el.querySelectorAll(".page-stack img, #page-img").forEach((img) => {
    img.addEventListener("click", () => img.classList.toggle("zoomed"));
    img.addEventListener("error", () => {
      img.replaceWith(Object.assign(document.createElement("div"), { className: "empty-state", textContent: "This page couldn't be shown." }));
    });
  });
  if (together) return;
  document.getElementById("pg-prev").addEventListener("click", () => {
    const p = stepPage(m, view, -1);
    if (p) { scanState.page = p; renderProofPage(); }
  });
  document.getElementById("pg-next").addEventListener("click", () => {
    const p = stepPage(m, view, 1);
    if (p) { scanState.page = p; renderProofPage(); }
  });
  el.querySelectorAll("[data-goto]").forEach((a) => a.addEventListener("click", (ev) => {
    ev.preventDefault();
    if (!confirmDiscard()) return;
    scanState.dirty = false;
    scanState.current = Number(a.dataset.goto);
    scanState.page = view;
    renderProofreadTab();
  }));
  const link = document.getElementById("pg-link");
  if (link) link.addEventListener("click", () => {
    const next = [...pages, view].sort((x, y) => x[0] - y[0] || x[1] - y[1]);
    saveEntryPages(e, next);
  });
  const unlink = document.getElementById("pg-unlink");
  if (unlink) unlink.addEventListener("click", () => saveEntryPages(e, pages.filter((p) => !samePage(p, view))));
}

async function saveEntryPages(e, pages) {
  try {
    const r = await postJson(`${srcPath(scanState.source)}/master/${e.num}/pages`, { pages });
    e.pages = r.pages;
    e.link = { method: "manual", note: null };
    renderProofPage();
  } catch (err) { toast(err.message, true); }
}

function renderProofEditor() {
  const e = currentEntry();
  const el = document.getElementById("proof-edit");
  el.innerHTML = `
    <div class="edit-meta">Entry ${e.num} · ${esc(e.label)}${e.filed ? ` · filed as <a href="#" id="open-filed">${esc(e.filed.title)}</a>` : ""}</div>
    <div class="proof-fields">
      <input type="text" id="pf-title" placeholder="Title (optional)" value="${esc(e.title)}">
      <input type="text" id="pf-date" placeholder="Date" value="${esc(e.date)}">
    </div>
    <textarea id="pf-body" spellcheck="true">${esc(e.body)}</textarea>
    ${e.notes.length ? `<div class="proof-notes"><b>Notes on hard-to-read words</b>${e.notes.map((n) => `<div>${esc(n)}</div>`).join("")}</div>` : ""}
    <div class="save-row">
      <button class="btn" id="pf-save-next">Save and mark reviewed</button>
      <button class="btn btn-ghost" id="pf-save">Save</button>
      <label class="filter-check" style="margin:0 0 0 auto"><input type="checkbox" id="pf-reviewed" ${e.reviewed ? "checked" : ""}> Reviewed</label>
    </div>
    ${e.filed ? `<div class="hint">This entry is already filed in your library. Changes here update the Master only, not the filed copy.</div>` : ""}`;
  ["pf-title", "pf-date", "pf-body"].forEach((id) =>
    document.getElementById(id).addEventListener("input", () => { scanState.dirty = true; }));
  document.getElementById("pf-save").addEventListener("click", () => saveProofEntry(false));
  document.getElementById("pf-save-next").addEventListener("click", () => saveProofEntry(true));
  document.getElementById("pf-reviewed").addEventListener("change", async (ev) => {
    try {
      await postJson(`${srcPath(scanState.source)}/master/${e.num}/reviewed`, { reviewed: ev.target.checked });
      e.reviewed = ev.target.checked;
      renderScans();
    } catch (err) { toast(err.message, true); }
  });
  const link = document.getElementById("open-filed");
  if (link) link.addEventListener("click", (ev) => { ev.preventDefault(); if (confirmDiscard()) { scanState.dirty = false; openEntryFromScans(e.filed.id); } });
}

async function saveProofEntry(andNext) {
  const e = currentEntry();
  const body = {
    version: scanState.master.version,
    body: document.getElementById("pf-body").value,
    title: document.getElementById("pf-title").value,
    date: document.getElementById("pf-date").value,
  };
  if (andNext) body.reviewed = true;
  try {
    const r = await postJson(`${srcPath(scanState.source)}/master/${e.num}`, body);
    scanState.master.version = r.version;
    scanState.dirty = false;
    toast("Saved to the Master.");
    await loadMaster();
    if (andNext) {
      const idx = scanState.master.entries.findIndex((x) => x.num === e.num);
      const next = scanState.master.entries.slice(idx + 1).find((x) => !x.reviewed);
      if (next) { scanState.current = next.num; scanState.page = null; }
    }
    renderScans();
  } catch (err) { toast(err.message, true); }
}

// -------------------------------------------------------------------------
// File entries
// -------------------------------------------------------------------------

async function renderFileTab() {
  const el = document.getElementById("scan-tab");
  try { await loadMaster(); }
  catch (e) {
    el.innerHTML = `<div class="empty-state">${esc(e.message)} Transcribe some scans and build the Master first.</div>`;
    return;
  }
  await loadCategories();
  const m = scanState.master;
  const rows = m.entries.filter((e) => (!scanState.fileOnlyReviewed || e.reviewed || e.filed) &&
    (!scanState.fileHideFiled || !e.filed));
  const open = m.entries.filter((e) => !e.filed).length;
  const orgReady = scanState.aiStatus.organizing.ready;
  el.innerHTML = `
    <div class="hint" style="margin-top:0">Filing makes each entry a folder in your library with a <b>[J]</b> draft that remembers its pages, so its scan is one click away later. ${open} of ${m.entries.length} entries aren't filed yet. Those rows have a title box and category menu so you can set both before filing; filed entries link to the entry.</div>
    <div class="scan-actions">
      <label class="filter-check" style="margin:0"><input type="checkbox" id="only-reviewed" ${scanState.fileOnlyReviewed ? "checked" : ""}> Only show reviewed entries</label>
      <label class="filter-check" style="margin:0"><input type="checkbox" id="hide-filed" ${scanState.fileHideFiled ? "checked" : ""}> Hide filed entries</label>
      <span class="spacer"></span>
      <button class="btn btn-ghost" id="suggest-btn" ${orgReady ? "" : "disabled"} title="${orgReady ? "" : esc(scanState.aiStatus.organizing.reason)}">Suggest titles and categories</button>
      <button class="btn btn-gold" id="file-btn">File selected</button>
    </div>
    <table class="entry-table file-table">
      <thead><tr><th style="width:28px"><input type="checkbox" id="file-all"></th><th>#</th><th>Status</th><th>Title</th><th>Category</th><th>Date</th><th>Begins</th></tr></thead>
      <tbody>
        ${rows.map((e, i) => {
          const next = rows[i + 1];
          const canJoin = !e.filed && next && !next.filed && next.num === e.num + 1;
          return `
          <tr data-num="${e.num}" class="${e.filed ? "filed" : "unfiled"}">
            <td>${e.filed ? "" : `<input type="checkbox" class="file-pick" value="${e.num}">`}</td>
            <td class="file-num">${e.num}${e.reviewed ? ' <span class="ok-text" title="Reviewed">✓</span>' : ""}
              ${canJoin ? `<button class="join-btn" data-join="${e.num}" aria-pressed="false" title="File this and the next entry as one piece">join next</button>` : ""}</td>
            <td>${e.filed ? `<span class="status-filed">${e.filed.joined ? `Filed, joined ${e.filed.joined[0]}–${e.filed.joined[1]}` : "Filed"}</span>` : '<span class="status-unfiled">Not filed</span>'}</td>
            <td>${e.filed ? `<a href="#" data-open-entry="${e.filed.id}">${esc(e.filed.title)}</a>` :
              `<input type="text" class="file-title" value="${esc(entryLabel(e).replace(/…$/, ""))}"><span class="joined-note">Joined to the entry above</span>`}</td>
            <td>${e.filed ? esc(e.filed.category) :
              `<select class="file-cat" data-category-menu>${categoryOptionsHtml(state.categories.includes("Misc") ? "Misc" : state.categories[0], { withNew: true })}</select>`}</td>
            <td class="muted">${esc(e.date)}</td>
            <td class="muted file-begins">${esc((e.body || "").slice(0, 90))}</td>
          </tr>`;
        }).join("")}
      </tbody>
    </table>`;
  el.querySelectorAll(".file-cat").forEach((sel) => wireCategorySelect(sel));
  scanState.fileJoins = scanState.fileJoins || new Set();
  const applyJoins = () => {
    el.querySelectorAll("tbody tr").forEach((tr) => {
      const prev = tr.previousElementSibling;
      const joined = !!prev && scanState.fileJoins.has(Number(prev.dataset.num)) && !!prev.querySelector("[data-join]");
      tr.classList.toggle("joined", joined);
      const pick = tr.querySelector(".file-pick");
      if (pick && joined) pick.checked = false;
      const btn = tr.querySelector("[data-join]");
      if (btn) {
        const on = scanState.fileJoins.has(Number(tr.dataset.num));
        btn.classList.toggle("active", on);
        btn.setAttribute("aria-pressed", on);
        btn.textContent = on ? "joined ↓" : "join next";
      }
    });
  };
  el.querySelectorAll("[data-join]").forEach((b) => b.addEventListener("click", () => {
    const n = Number(b.dataset.join);
    if (scanState.fileJoins.has(n)) scanState.fileJoins.delete(n); else scanState.fileJoins.add(n);
    applyJoins();
  }));
  applyJoins();
  document.getElementById("hide-filed").addEventListener("change", (ev) => {
    scanState.fileHideFiled = ev.target.checked;
    renderFileTab();
  });
  document.getElementById("only-reviewed").addEventListener("change", (ev) => {
    scanState.fileOnlyReviewed = ev.target.checked;
    renderFileTab();
  });
  document.getElementById("file-all").addEventListener("change", (ev) =>
    el.querySelectorAll(".file-pick").forEach((c) => { c.checked = ev.target.checked; }));
  el.querySelectorAll("[data-open-entry]").forEach((a) =>
    a.addEventListener("click", (ev) => { ev.preventDefault(); openEntryFromScans(Number(a.dataset.openEntry)); }));

  const picked = () => [...el.querySelectorAll(".file-pick:checked")].map((c) => c.closest("tr"))
    .filter((tr) => !tr.classList.contains("joined"));
  // the last entry of the run that starts at this row
  const through = (tr) => {
    let last = tr;
    while (last.nextElementSibling && last.nextElementSibling.classList.contains("joined")) last = last.nextElementSibling;
    return Number(last.dataset.num);
  };
  document.getElementById("suggest-btn").addEventListener("click", async (ev) => {
    const trs = picked();
    if (!trs.length) { toast("Choose the entries you want suggestions for.", true); return; }
    if (trs.length > 60) { toast("Choose 60 entries or fewer at a time.", true); return; }
    ev.target.disabled = true;
    ev.target.textContent = "Asking...";
    try {
      const r = await postJson(`${srcPath(scanState.source)}/suggest`, { nums: trs.map((tr) => Number(tr.dataset.num)) });
      trs.forEach((tr) => {
        const s = r[tr.dataset.num];
        if (!s) return;
        if (s.title) tr.querySelector(".file-title").value = s.title;
        if (s.category) tr.querySelector(".file-cat").value = s.category;
        tr.classList.add("suggested");
      });
      toast("Suggestions filled in. Check them, then file.");
    } catch (e) { toast(e.message, true); }
    ev.target.disabled = false;
    ev.target.textContent = "Suggest titles and categories";
  });
  document.getElementById("file-btn").addEventListener("click", async () => {
    const trs = picked();
    if (!trs.length) { toast("Choose the entries to file.", true); return; }
    const items = trs.map((tr) => ({
      num: Number(tr.dataset.num),
      through: through(tr),
      title: tr.querySelector(".file-title").value,
      category: tr.querySelector(".file-cat").value,
    }));
    const joins = items.filter((it) => it.through > it.num);
    const joinNote = joins.length ? ` ${joins.map((it) => `Entries ${it.num}–${it.through}`).join(", ")} ${joins.length === 1 ? "becomes one entry" : "each become one entry"}.` : "";
    if (!confirm(`Create ${items.length} new entr${items.length === 1 ? "y" : "ies"} in your library?${joinNote}`)) return;
    try {
      const r = await postJson(`${srcPath(scanState.source)}/file`, { items });
      r.created.forEach((c) => { for (let n = c.num; n < c.through; n++) scanState.fileJoins.delete(n); });
      toast(`Filed ${r.created.length} entr${r.created.length === 1 ? "y" : "ies"}.` +
        (r.skipped.length ? ` Skipped ${r.skipped.length}.` : ""));
      renderFileTab();
    } catch (e) { toast(e.message, true); }
  });
}
