// Images: drawings and diagrams found in transcribed scans, shown as a gallery
// under the Entries tab. Each one has a suggested kind and file name; "Save
// images" copies the chosen pages into the source's Images folder.

const imgState = { source: "", show: "unsaved", data: null };

async function renderImages() {
  appEl.innerHTML = `${entryPanesHtml("images")}<div id="img-body"><div class="empty-state">Loading...</div></div>`;
  wireEntryPanes();
  try { imgState.data = await api("/api/images"); }
  catch (e) { document.getElementById("img-body").innerHTML = `<div class="empty-state">${esc(e.message)}</div>`; return; }
  drawImages();
}

function drawImages() {
  const body = document.getElementById("img-body");
  const { images, kinds } = imgState.data;
  if (!images.length) {
    body.innerHTML = `<div class="empty-state">No drawings or diagrams yet. They show up here once a scanned source has a Master; transcription describes each one in [square brackets].</div>`;
    return;
  }
  const sources = [...new Set(images.map((i) => i.source))];
  if (imgState.source && !sources.includes(imgState.source)) imgState.source = "";
  const shown = images.filter((i) => (!imgState.source || i.source === imgState.source)
    && (imgState.show === "all" || (imgState.show === "saved") === (i.saved.length > 0)));
  body.innerHTML = `
    <div class="img-toolbar">
      <label>Source <select id="img-source"><option value="">All sources</option>
        ${sources.map((s) => `<option ${s === imgState.source ? "selected" : ""}>${esc(s)}</option>`).join("")}</select></label>
      <label>Show <select id="img-show">
        ${[["unsaved", "Not saved yet"], ["saved", "Saved"], ["all", "All"]].map(([v, l]) => `<option value="${v}" ${v === imgState.show ? "selected" : ""}>${l}</option>`).join("")}
      </select></label>
      <span class="recent-meta" id="img-count"></span>
      <button class="btn btn-primary" id="img-save">Save images</button>
    </div>
    ${shown.length ? `<div class="img-grid">${shown.map((img) => imgCardHtml(img, kinds)).join("")}</div>`
      : `<div class="empty-state">Nothing in this view.</div>`}`;
  document.getElementById("img-source").addEventListener("change", (e) => { imgState.source = e.target.value; drawImages(); });
  document.getElementById("img-show").addEventListener("change", (e) => { imgState.show = e.target.value; drawImages(); });
  body.querySelectorAll(".img-card input[type=checkbox]").forEach((cb) => cb.addEventListener("change", countImages));
  document.getElementById("img-save").addEventListener("click", saveImages);
  countImages();
}

function imgCardHtml(img, kinds) {
  const [first] = img.pages;
  const thumb = first
    ? `<img class="img-thumb" loading="lazy" alt="${esc(img.description)}" src="/api/scans/${encodeURIComponent(img.source)}/page/${first[0]}/${first[1]}.jpg">`
    : `<div class="img-thumb img-missing">Not matched to a page yet</div>`;
  const pick = first && !img.saved.length && !img.has_text;
  return `<div class="img-card" data-source="${esc(img.source)}" data-num="${img.num}">
    ${thumb}
    <label class="img-pick"><input type="checkbox" ${pick ? "checked" : ""} ${first ? "" : "disabled"}> Save</label>
    <input class="img-name" type="text" value="${esc(img.name)}" aria-label="File name">
    <select class="img-kind" aria-label="Kind">${kinds.map((k) => `<option ${k === img.kind ? "selected" : ""}>${k}</option>`).join("")}</select>
    <div class="recent-meta">${esc(img.source)} · Entry ${img.num}${img.date && img.date !== "none" ? ` · ${esc(img.date)}` : ""}${img.pages.length > 1 ? ` · ${img.pages.length} pages` : ""}</div>
    <div class="img-desc">${esc(img.description)}${img.has_text ? ` <span class="recent-meta">(on a page with writing)</span>` : ""}</div>
    ${img.saved.length ? `<div class="img-saved">Saved: ${img.saved.map(esc).join(", ")}</div>` : ""}
  </div>`;
}

function countImages() {
  const n = document.querySelectorAll(".img-card input[type=checkbox]:checked").length;
  document.getElementById("img-count").textContent = n ? `${n} selected` : "";
  const btn = document.getElementById("img-save");
  btn.disabled = !n;
  btn.textContent = n === 1 ? "Save 1 image" : n ? `Save ${n} images` : "Save images";
}

async function saveImages() {
  const bySource = {};
  document.querySelectorAll(".img-card").forEach((card) => {
    if (!card.querySelector("input[type=checkbox]").checked) return;
    const { source, num } = card.dataset;
    (bySource[source] = bySource[source] || []).push({
      num: Number(num), name: card.querySelector(".img-name").value, kind: card.querySelector(".img-kind").value });
  });
  const btn = document.getElementById("img-save");
  btn.disabled = true;
  let written = 0;
  try {
    for (const [source, items] of Object.entries(bySource)) {
      const r = await api("/api/images/save", { method: "POST", body: JSON.stringify({ source, items }) });
      written += r.written.length;
    }
    toast(`Saved ${written} image${written === 1 ? "" : "s"} to each source's Images folder.`);
  } catch (e) {
    toast(e.message, true);
  }
  await renderImages();
}
