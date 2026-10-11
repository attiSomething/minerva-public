// Compare any two of an entry's drafts (current or archived), word by word.
// Depends on helpers from app.js (api, esc, toast, shortDate, plural, state).

const compareState = { layout: "inline" };

function compareOptions(e) {
  // newest first: the current draft, then archived text drafts by date
  const archived = e.archive.filter((a) => a.is_text)
    .slice().sort((x, y) => (y.modified || "").localeCompare(x.modified || ""));
  return [{ value: "", label: `Current draft (${e.draft_filename})` },
    ...archived.map((a) => ({ value: a.name, label: `${a.name}${a.modified ? ` · ${shortDate(a.modified)}` : ""}` }))];
}

function openCompare(e, a, b) {
  const opts = compareOptions(e);
  // default: the newest archived draft against the current one
  if (a === undefined) a = opts[1] ? opts[1].value : "";
  if (b === undefined) b = "";
  const select = (id, val) => `<select id="${id}">${opts.map((o) =>
    `<option value="${esc(o.value)}" ${o.value === val ? "selected" : ""}>${esc(o.label)}</option>`).join("")}</select>`;
  const el = document.getElementById("archive-preview");
  el.innerHTML = `
    <div class="panel compare-panel" style="margin-top:16px">
      <div class="panel-head-row">
        <h3>Compare drafts</h3>
        <div class="seg" role="radiogroup" aria-label="Layout">
          <button class="seg-btn" data-compare-layout="inline" role="radio">Inline</button>
          <button class="seg-btn" data-compare-layout="side" role="radio">Side by side</button>
        </div>
      </div>
      <div class="compare-pickers">
        <label>From ${select("cmp-a", a)}</label>
        <button class="btn btn-ghost btn-small" id="cmp-swap" title="Swap">⇄</button>
        <label>To ${select("cmp-b", b)}</label>
      </div>
      <div id="compare-result"><div class="empty-state">Comparing...</div></div>
    </div>`;
  const run = () => loadCompare(e.id);
  document.getElementById("cmp-a").addEventListener("change", run);
  document.getElementById("cmp-b").addEventListener("change", run);
  document.getElementById("cmp-swap").addEventListener("click", () => {
    const sa = document.getElementById("cmp-a"), sb = document.getElementById("cmp-b");
    [sa.value, sb.value] = [sb.value, sa.value];
    run();
  });
  el.querySelectorAll("[data-compare-layout]").forEach((btn) => btn.addEventListener("click", () => {
    compareState.layout = btn.dataset.compareLayout;
    showCompare();
  }));
  el.scrollIntoView({ behavior: "smooth", block: "start" });
  run();
}

async function loadCompare(entryId) {
  const a = document.getElementById("cmp-a").value, b = document.getElementById("cmp-b").value;
  const seq = (loadCompare.seq = (loadCompare.seq || 0) + 1);
  try {
    const r = await api(`/api/entries/${entryId}/compare?${new URLSearchParams({ a, b })}`);
    if (seq !== loadCompare.seq) return;
    compareState.result = r;
    showCompare();
  } catch (err) {
    document.getElementById("compare-result").innerHTML = `<div class="empty-state">${esc(err.message)}</div>`;
  }
}

function showCompare() {
  const r = compareState.result;
  const out = document.getElementById("compare-result");
  if (!r || !out) return;
  document.querySelectorAll("[data-compare-layout]").forEach((b) => {
    const on = b.dataset.compareLayout === compareState.layout;
    b.classList.toggle("active", on);
    b.setAttribute("aria-checked", on);
  });
  const label = (d) => `${d.current ? "Current draft" : esc(d.name)} · ${plural(d.words, "word", "words")}${d.modified ? ` · ${shortDate(d.modified)}` : ""}`;
  const summary = r.same ? "These two drafts are identical."
    : `${plural(r.added, "word", "words")} added, ${plural(r.removed, "word", "words")} removed.`;
  const piece = ([op, t]) => op === "eq" ? esc(t) : `<${op}>${esc(t)}</${op}>`;
  let body;
  if (compareState.layout === "side") {
    const left = r.changes.filter(([op]) => op !== "ins").map(piece).join("");
    const right = r.changes.filter(([op]) => op !== "del").map(piece).join("");
    body = `<div class="compare-side">
      <div><div class="compare-label">${label(r.a)}</div><div class="diff-view">${left}</div></div>
      <div><div class="compare-label">${label(r.b)}</div><div class="diff-view">${right}</div></div>
    </div>`;
  } else {
    body = `<div class="compare-label">${label(r.a)} → ${label(r.b)}</div>
      <div class="diff-view compare-inline">${r.changes.map(piece).join("")}</div>`;
  }
  out.innerHTML = `<div class="hint" style="margin:0 0 8px">${summary} Removed words are struck through in red; added words are highlighted in green.</div>${body}`;
}
