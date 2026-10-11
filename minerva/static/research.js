// Submission research: where could this piece go? The writer's own Venues
// ranked by fit (offline), then new places suggested by their AI, each
// checkable against the venue's own website with the source of every fact.

HELP_TOPICS.research = { kind: "howto", name: "7 - Tracking Where a Poem Is Out.html", anchor: "Find places to send it" };

const research = { piece: null, data: null, found: [], checked: {}, added: new Set(), previewTimer: null };

const RESEARCH_LABELS = {
  reading_periods: "Reading period", open_now: "Open now", fee: "Fee", response_days: "Response",
  line_limit: "Line limit", how_many: "How many", simultaneous: "Simultaneous submissions",
  pays: "Pays", how_to_submit: "How to submit",
};

function closeResearch() {
  const el = document.getElementById("research-dialog");
  if (el) el.remove();
  document.removeEventListener("keydown", researchKeys);
}

function researchKeys(ev) { if (ev.key === "Escape") closeResearch(); }

async function openResearch(piece) {
  closeResearch();
  research.piece = piece;
  research.found = [];
  research.checked = {};
  research.added = new Set();
  const q = piece.kind === "entry" ? `entry_id=${piece.id}` : `project_id=${piece.id}`;
  let d;
  try { d = await api(`/api/research/fit?${q}`); } catch (e) { toast(e.message, true); return; }
  research.data = d;
  const f = d.fit;
  const el = document.createElement("div");
  el.id = "research-dialog";
  el.className = "modal-backdrop";
  const own = d.own.filter((v) => !v.sent).slice(0, 6);
  const sent = d.own.filter((v) => v.sent);
  const size = f.lines && f.kind.includes("poetry") ? `${f.lines} lines` : `${f.words.toLocaleString()} words`;
  el.innerHTML = `
    <div class="modal modal-wide research" role="dialog" aria-modal="true" aria-labelledby="rs-h">
      <h2 id="rs-h">Where to send ${esc(f.title)}</h2>
      <p class="muted">${esc(f.kind[0].toUpperCase() + f.kind.slice(1))}, ${esc(f.form)}, ${esc(size)}${f.pieces > 1 ? ` across ${f.pieces} pieces` : ""}${f.tags.length ? `. Tags: ${esc(f.tags.join(", "))}` : ""}. ${helpLinkHtml("research", "How this works")}</p>
      <h3>Your venues</h3>
      ${own.length ? `<ul class="rs-own">${own.map((v) => `
        <li><strong>${esc(v.name)}</strong>${v.website ? ` <a href="${esc(venueUrl(v.website))}" target="_blank" rel="noopener" class="muted">website</a>` : ""}
          <div class="hint">${esc(v.reasons.join(" ") || "No notes on this venue yet.")}</div></li>`).join("")}</ul>`
        : `<p class="hint">None yet. Venues you add or send work to show up here, best fit first.</p>`}
      ${sent.length ? `<p class="hint">Already sent there: ${sent.map((v) => `${esc(v.name)} (${esc(v.sent.toLowerCase())})`).join(", ")}.</p>` : ""}
      <h3>Find new places</h3>
      ${d.ai.ready ? "" : `<p class="warn-text">${esc(d.ai.reason)} <a href="#" data-rs-settings>Open Settings</a></p>`}
      <label for="rs-about">What it's about <span class="muted">(optional, helps the suggestions)</span></label>
      <textarea id="rs-about" rows="2" placeholder="e.g. grief and tides; a lighthouse keeper's last winter"></textarea>
      <label class="switch-row"><input type="checkbox" id="rs-title"><span>Include the title</span></label>
      <label class="switch-row"><input type="checkbox" id="rs-text"><span>Let the AI read the writing itself <span class="muted">(better suggestions; your unpublished words go to ${esc(d.ai.provider_label || "the AI service")})</span></span></label>
      <details class="rs-brief"><summary>What ${esc(d.ai.provider_label || "the AI")} is told</summary><pre id="rs-brief"></pre></details>
      <div class="modal-actions" style="justify-content:flex-start">
        <button class="btn btn-gold" id="rs-go" ${d.ai.ready ? "" : "disabled"}>Suggest places</button>
        <span id="rs-status" class="muted"></span>
      </div>
      <div id="rs-found"></div>
      <p class="hint">Suggestions come from the AI's memory, so check before you send. "Check their website" reads the venue's own pages and shows where each detail came from. Minerva doesn't read submission directories such as Duotrope or Submittable, whose terms don't allow it.</p>
      <div class="modal-actions"><span style="flex:1"></span><button class="btn" id="rs-close">Done</button></div>
    </div>`;
  document.body.appendChild(el);
  document.addEventListener("keydown", researchKeys);
  el.addEventListener("click", (ev) => { if (ev.target === el) closeResearch(); });
  document.getElementById("rs-close").addEventListener("click", closeResearch);
  const toSettings = el.querySelector("[data-rs-settings]");
  if (toSettings) toSettings.addEventListener("click", (ev) => { ev.preventDefault(); closeResearch(); setView("settings"); });
  ["rs-about", "rs-title", "rs-text"].forEach((id) => document.getElementById(id).addEventListener(id === "rs-about" ? "input" : "change", schedulePreview));
  document.getElementById("rs-go").addEventListener("click", suggestPlaces);
  refreshPreview();
}

function researchBody() {
  const p = research.piece;
  return {
    [p.kind === "entry" ? "entry_id" : "project_id"]: p.id,
    about: document.getElementById("rs-about").value,
    include_title: document.getElementById("rs-title").checked,
    include_text: document.getElementById("rs-text").checked,
  };
}

function schedulePreview() {
  clearTimeout(research.previewTimer);
  research.previewTimer = setTimeout(refreshPreview, 300);
}

async function refreshPreview() {
  const pre = document.getElementById("rs-brief");
  if (!pre) return;
  try { pre.textContent = (await postJson("/api/research/preview", researchBody())).brief; } catch (e) { pre.textContent = e.message; }
}

async function suggestPlaces() {
  const go = document.getElementById("rs-go");
  const status = document.getElementById("rs-status");
  go.disabled = true;
  status.textContent = "Asking for suggestions...";
  try {
    const r = await postJson("/api/research/suggest", { ...researchBody(), avoid: research.found.map((v) => v.name) });
    research.found = research.found.concat(r.venues);
    status.textContent = "";
    go.textContent = "Suggest more";
    renderFound();
  } catch (e) {
    status.textContent = "";
    toast(e.message, true);
  }
  go.disabled = false;
}

function rememberedHtml(v) {
  const r = v.remembered || {};
  const bits = [["Reads", r.reading_periods], ["Fee", r.fee], ["Response", r.response_time], ["Line limit", r.line_limit]]
    .filter(([, x]) => x).map(([k, x]) => `${k}: ${esc(x)}`);
  return bits.length ? `<div class="hint">From the AI's memory, not checked: ${bits.join("; ")}.</div>` : "";
}

function checkedHtml(c) {
  const keys = Object.keys(RESEARCH_LABELS).filter((k) => c.facts[k]);
  if (!keys.length) return `<div class="hint warn-text">Their pages didn't say. Read <a href="${esc(c.website)}" target="_blank" rel="noopener">their website</a> yourself.</div>`;
  return `<dl class="rs-facts">${keys.map((k) => {
    const f = c.facts[k];
    return `<dt>${RESEARCH_LABELS[k]}</dt><dd>${esc(String(f.value))}${k === "response_days" ? " days" : k === "line_limit" ? " lines" : ""}
      <div class="rs-quote">“${esc(f.quote)}” <a href="${esc(f.url)}" target="_blank" rel="noopener">source</a></div></dd>`;
  }).join("")}</dl><div class="hint">Checked ${esc(shortDate(c.checked_on))} on ${c.pages.length} page${c.pages.length === 1 ? "" : "s"} of their website.${c.dropped.length ? ` ${c.dropped.length === 1 ? "One detail the AI gave wasn't" : `${c.dropped.length} details the AI gave weren't`} on their pages, so ${c.dropped.length === 1 ? "it's" : "they're"} left out.` : ""}</div>`;
}

function renderFound() {
  const box = document.getElementById("rs-found");
  if (!box) return;
  box.innerHTML = research.found.map((v, i) => {
    const c = research.checked[v.name];
    return `<div class="rs-card">
      <div class="rs-card-head"><strong>${esc(v.name)}</strong>${v.type ? ` <span class="badge">${esc(v.type)}</span>` : ""}
        ${v.website ? `<a href="${esc(v.website)}" target="_blank" rel="noopener" class="muted">${esc(v.website.replace(/^https?:\/\//, "").replace(/\/$/, ""))}</a>` : ""}</div>
      ${v.why ? `<div>${esc(v.why)}</div>` : ""}
      ${c ? checkedHtml(c) : rememberedHtml(v)}
      ${v.directory ? `<div class="hint">The AI gave a submissions directory instead of their own website. Minerva doesn't read directories; look up their site in your browser.</div>` : ""}
      <div class="rs-actions">
        ${v.website && !v.directory && !c ? `<button class="btn btn-small btn-ghost" data-rs-check="${i}">Check their website</button>` : ""}
        ${research.added.has(v.name) ? `<span class="muted">In Venues</span>` : `<button class="btn btn-small" data-rs-add="${i}">Add to Venues</button>`}
        <span class="muted" data-rs-busy="${i}"></span>
      </div></div>`;
  }).join("");
  box.querySelectorAll("[data-rs-check]").forEach((b) => b.addEventListener("click", () => checkVenue(Number(b.dataset.rsCheck), b)));
  box.querySelectorAll("[data-rs-add]").forEach((b) => b.addEventListener("click", () => addVenue(Number(b.dataset.rsAdd), b)));
}

async function checkVenue(i, btn) {
  const v = research.found[i];
  btn.disabled = true;
  const busy = document.querySelector(`[data-rs-busy="${i}"]`);
  if (busy) busy.textContent = "Reading their website...";
  try {
    research.checked[v.name] = await postJson("/api/research/check", { name: v.name, website: v.website });
  } catch (e) {
    toast(e.message, true);
  }
  renderFound();
}

async function addVenue(i, btn) {
  const v = research.found[i];
  btn.disabled = true;
  try {
    await postJson("/api/research/add", { name: v.name, website: v.website, why: v.why, checked: research.checked[v.name] || null });
    research.added.add(v.name);
    subOptions(true).catch(() => {});
    toast(`${v.name} is in Venues${research.checked[v.name] ? ", with what their website says" : ""}.`);
  } catch (e) { toast(e.message, true); }
  renderFound();
}
