// Sharing: final drafts, templates, and exporting entries and projects.

const shareState = { options: null };

async function shareOptions(refresh) {
  if (!shareState.options || refresh) shareState.options = await api("/api/share/options");
  return shareState.options;
}

function postShare(path, body) {
  return api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
}

function uploadFile(path, file, fields) {
  const form = new FormData();
  form.append("file", file);
  Object.entries(fields || {}).forEach(([k, v]) => form.append(k, v));
  return api(path, { method: "POST", body: form });
}

const FORMAT_LABELS = { txt: "Plain text (.txt)", docx: "Word (.docx)", pdf: "PDF (.pdf)" };

// After an export: where it went, and buttons to open it.
function exportResultHtml(r) {
  return `
    <div class="export-result">
      <div>Saved <b>${esc(r.name)}</b> in ${esc(r.folder)}.</div>
      <div class="scan-links">
        <button class="btn btn-small" data-export-open="${esc(r.name)}">Open</button>
        <button class="btn btn-small btn-ghost" data-export-reveal="${esc(r.name)}">Show in folder</button>
        <a class="btn btn-small btn-ghost" href="/api/exports/file?name=${encodeURIComponent(r.name)}">Download</a>
      </div>
    </div>`;
}

function wireExportResult(root) {
  root.querySelectorAll("[data-export-open], [data-export-reveal]").forEach((b) => b.addEventListener("click", async () => {
    try {
      await postShare("/api/exports/open", { name: b.dataset.exportOpen || b.dataset.exportReveal, reveal: !!b.dataset.exportReveal });
    } catch (err) { toast(err.message, true); }
  }));
}

// ---- entry editor ----------------------------------------------------------

function finalStatusHtml(e) {
  if (!e.final) {
    return `<div class="hint" style="margin-top:0">No final draft yet. Marking one keeps a copy in this entry's Final folder, so later edits don't change what you share.</div>
      <button class="btn btn-small" id="mark-final">Mark current draft as final</button>`;
  }
  return `
    <div class="final-status"><span class="badge badge-final">Final</span> marked ${esc(shortDate(e.final.marked))}
      · ${e.final.same_as_current ? "same as the current draft" : '<span class="warn-text">the current draft has changed since</span>'}</div>
    <div class="scan-links" style="margin-top:6px">
      <button class="btn btn-small btn-ghost" id="view-final">View</button>
      ${e.final.same_as_current ? "" : '<button class="btn btn-small btn-ghost" id="mark-final">Mark current draft as final</button>'}
      <button class="btn btn-small btn-ghost" id="unmark-final" title="Moves the final copy into Archive">Unmark</button>
    </div>`;
}

function sharePanelHtml(e) {
  return `
    <div class="panel" id="share-panel">
      <h3>Share ${helpLinkHtml("share", "Manuscript how-to")}</h3>
      ${finalStatusHtml(e)}
      <div class="share-export">
        <div class="field-row">
          <label>Export as</label>
          <select id="share-format">${["pdf", "docx", "txt"].map((f) => `<option value="${f}">${FORMAT_LABELS[f]}</option>`).join("")}</select>
        </div>
        ${e.final ? `<div class="field-row">
          <label>Draft</label>
          <select id="share-which"><option value="final">Final draft</option><option value="current">Current draft</option></select>
        </div>` : ""}
        <div class="field-row" id="share-template-row">
          <label>Layout</label>
          <select id="share-template"></select>
          <div class="hint" id="share-template-note"></div>
        </div>
        <button class="btn btn-small btn-gold" id="share-export">Export</button>
        <button class="btn btn-small btn-ghost" id="share-narrate" title="Read it into an audio file">Narrate</button>
        <button class="btn btn-small btn-ghost" id="share-video" title="A video of the words, in time with a narration">Video</button>
        <div id="share-result"></div>
      </div>
    </div>`;
}

async function wireSharePanel(e) {
  const panel = document.getElementById("share-panel");
  if (!panel) return;
  const opts = await shareOptions(true);
  const fmt = document.getElementById("share-format");
  const tpl = document.getElementById("share-template");
  const fillTemplates = () => {
    const fitting = opts.templates.filter((t) => t.kind === fmt.value);
    const keep = tpl.value;
    tpl.innerHTML = `<option value="">Minerva's plain layout</option><option value="manuscript">Standard manuscript</option>` +
      fitting.map((t) => `<option value="${esc(t.id)}">${esc(t.name)}</option>`).join("");
    if ([...tpl.options].some((o) => o.value === keep)) tpl.value = keep;
    note();
  };
  const note = () => {
    const el = document.getElementById("share-template-note");
    el.innerHTML = tpl.value !== "manuscript" ? "" : opts.contact_set
      ? "Your contact details and the line count go at the top, as magazines ask."
      : `<a href="#" data-add-contact>Add your name and contact details</a> first; they go at the top of the page.`;
    const go = el.querySelector("[data-add-contact]");
    if (go) go.addEventListener("click", (ev) => {
      ev.preventDefault();
      openContactDialog(async () => { opts.contact_set = (await shareOptions()).contact_set; note(); });
    });
  };
  fmt.addEventListener("change", fillTemplates);
  tpl.addEventListener("change", note);
  fillTemplates();

  const refresh = () => renderEdit();
  const mark = document.getElementById("mark-final");
  if (mark) mark.addEventListener("click", async () => {
    try { await postShare(`/api/entries/${e.id}/final`); toast("Marked as final."); refresh(); }
    catch (err) { toast(err.message, true); }
  });
  const unmark = document.getElementById("unmark-final");
  if (unmark) unmark.addEventListener("click", async () => {
    if (!confirm("Unmark the final draft? Its copy moves into this entry's Archive.")) return;
    try { await postShare(`/api/entries/${e.id}/final/remove`); toast("Final draft moved to Archive."); refresh(); }
    catch (err) { toast(err.message, true); }
  });
  const view = document.getElementById("view-final");
  if (view) view.addEventListener("click", () => {
    const el = document.getElementById("archive-preview");
    el.innerHTML = `<div class="panel" style="margin-top:16px"><h3>Final draft</h3><div class="dup-compare-text" style="max-height:480px">${esc(e.final.text)}</div></div>`;
    el.scrollIntoView({ behavior: "smooth" });
  });
  document.getElementById("share-narrate").addEventListener("click", () => {
    const which = document.getElementById("share-which");
    openNarration({ kind: "entry", id: e.id, title: e.title, which: which ? which.value : "current" });
  });
  document.getElementById("share-video").addEventListener("click", () => openVideo({ kind: "entry", id: e.id, title: e.title }));
  document.getElementById("share-export").addEventListener("click", async (ev) => {
    ev.target.disabled = true;
    try {
      const which = document.getElementById("share-which");
      const r = await postShare(`/api/entries/${e.id}/export`, {
        format: fmt.value, which: which ? which.value : "current", template_id: tpl.value,
      });
      const out = document.getElementById("share-result");
      out.innerHTML = exportResultHtml(r);
      wireExportResult(out);
    } catch (err) { toast(err.message, true); }
    ev.target.disabled = false;
  });
}

async function markArchiveFinal(entryId, name) {
  try {
    await postShare(`/api/entries/${entryId}/final`, { archive_name: name });
    toast(`"${name}" is now the final draft.`);
    renderEdit();
  } catch (err) { toast(err.message, true); }
}

// ---- Settings: manuscript details -------------------------------------------

function manuscriptSectionHtml(c) {
  return `
    <section class="panel" id="manuscript-section">
      <h2>Manuscript details</h2>
      <p class="muted">Used by the "Standard manuscript" layout when you export: your name and contact details at the top of each piece, and your surname in the running header. Kept in Minerva's settings on this computer, not in your library.</p>
      <div class="sub-form">
        <div class="field-row wide"><label for="ms-name">Name</label><input type="text" id="ms-name" value="${esc(c.name)}" placeholder="The name you submit under"></div>
        <div class="field-row wide"><label for="ms-address">Address</label><textarea id="ms-address" rows="3" placeholder="Street&#10;City, State ZIP">${esc(c.address)}</textarea></div>
        <div class="field-row"><label for="ms-email">Email</label><input type="email" id="ms-email" value="${esc(c.email)}"></div>
        <div class="field-row"><label for="ms-phone">Phone</label><input type="text" id="ms-phone" value="${esc(c.phone)}"></div>
        <div class="field-row wide"><label for="ms-website">Website (optional)</label><input type="text" id="ms-website" value="${esc(c.website)}"></div>
      </div>
      <button class="btn" id="ms-save">Save</button>
    </section>`;
}

function wireManuscriptSection(onSaved) {
  const btn = document.getElementById("ms-save");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    const v = (id) => document.getElementById(id).value;
    try {
      await postShare("/api/settings/contact", { name: v("ms-name"), address: v("ms-address"), email: v("ms-email"),
        phone: v("ms-phone"), website: v("ms-website") });
      await shareOptions(true).catch(() => {});
      toast("Saved.");
      if (onSaved) onSaved();
    } catch (e) { toast(e.message, true); }
  });
}

// The same details from the Share panel, without leaving the entry.
async function openContactDialog(onSaved) {
  let c;
  try { c = await api("/api/settings/contact"); } catch (e) { toast(e.message, true); return; }
  const el = document.createElement("div");
  el.id = "contact-dialog";
  el.className = "modal-backdrop";
  el.innerHTML = `<div class="modal modal-wide" role="dialog" aria-modal="true">${manuscriptSectionHtml(c)}
    <div class="modal-actions"><span style="flex:1"></span><button class="btn btn-ghost" id="ms-cancel">Cancel</button></div></div>`;
  document.body.appendChild(el);
  const close = () => el.remove();
  el.querySelector("#manuscript-section").classList.remove("panel");
  document.getElementById("ms-cancel").addEventListener("click", close);
  el.addEventListener("click", (ev) => { if (ev.target === el) close(); });
  wireManuscriptSection(() => { close(); if (onSaved) onSaved(); });
  document.getElementById("ms-name").focus();
}

// ---- Settings: templates ---------------------------------------------------

function templatesSectionHtml(templates) {
  return `
    <section class="panel" id="templates-section">
      <h2>Export templates</h2>
      <p class="muted">Use your own layout when you export an entry. In a Word template, put {{title}} and {{body}} where they belong (also {{category}}, {{date}}); without {{body}}, the text goes at the end. A PDF template's first page becomes the background of every page, like letterhead.</p>
      <ul class="template-list">
        ${templates.length ? templates.map((t) => `
          <li><span><b>${esc(t.name)}</b> <span class="muted">.${esc(t.kind)} · added ${esc(t.added)}</span></span>
            <button class="btn btn-small btn-ghost" data-remove-template="${esc(t.id)}">Remove</button></li>`).join("") :
          '<li class="muted">No templates yet.</li>'}
      </ul>
      <div class="template-add">
        <input type="text" id="template-name" placeholder="Name (optional)">
        <input type="file" id="template-file" accept=".docx,.pdf">
        <button class="btn btn-small" id="template-add">Add template</button>
      </div>
    </section>`;
}

function wireTemplates(rerender) {
  document.querySelectorAll("[data-remove-template]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("Remove this template from Minerva? Your original file isn't touched.")) return;
    try { await postShare(`/api/templates/${b.dataset.removeTemplate}/delete`); rerender(); }
    catch (err) { toast(err.message, true); }
  }));
  document.getElementById("template-add").addEventListener("click", async () => {
    const file = document.getElementById("template-file").files[0];
    if (!file) { toast("Choose a .docx or .pdf file first.", true); return; }
    try {
      const t = await uploadFile("/api/templates", file, { name: document.getElementById("template-name").value });
      toast(`Added "${t.name}".`);
      shareState.options = null;
      rerender();
    } catch (err) { toast(err.message, true); }
  });
}

// ---- project page ----------------------------------------------------------

function coverHtml(p, side, has) {
  const label = side === "front" ? "Front cover" : "Back cover";
  return `
    <div class="cover-slot">
      <div class="cover-label">${label}</div>
      <div class="cover-thumb">${has ? `<img src="/api/projects/${p.id}/cover/${side}?t=${Date.now()}" alt="${label}">` : `<span>${label}</span>`}</div>
      <label class="btn btn-small btn-ghost cover-pick">${has ? "Replace" : "Add"}<input type="file" accept=".jpg,.jpeg,.png" data-cover="${side}" hidden></label>
      ${has ? `<button class="btn btn-small btn-ghost" data-cover-remove="${side}">Remove</button>` : ""}
    </div>`;
}

async function renderProjectShare(p) {
  const el = document.getElementById("project-share");
  if (!el) return;
  const [opts, s, snips] = await Promise.all([shareOptions(), api(`/api/projects/${p.id}/share`),
    loadSnippets(true).catch(() => ({ snippets: [] }))]);
  const fromSnippet = (field, kinds) => {
    const list = snips.snippets.filter((x) => kinds.includes(x.kind));
    return list.length ? `<select class="ps-snippet" data-for="${field}" aria-label="Fill from a snippet">
      <option value="">From a snippet...</option>${list.map((x) => `<option value="${esc(x.id)}">${esc(x.name)}</option>`).join("")}</select>` : "";
  };
  el.innerHTML = `
    <h3>Publish ${helpLinkHtml("publish", "How")}</h3>
    <div class="hint" style="margin-top:0">Exports the entries in the order on the left, using each entry's final draft when it has one.</div>
    <div class="field-row"><label>Page size</label>
      <select id="ps-trim">${opts.trims.map((t) => `<option value="${t.id}" ${t.id === s.trim ? "selected" : ""}>${esc(t.label)}</option>`).join("")}</select></div>
    <div class="field-row"><label>Subtitle</label><input type="text" id="ps-subtitle" value="${esc(s.subtitle)}"></div>
    <div class="field-row"><label>Author</label><input type="text" id="ps-author" value="${esc(s.author)}"></div>
    <div class="field-row"><label>Copyright</label><input type="text" id="ps-copyright" value="${esc(s.copyright)}" placeholder="© ${new Date().getFullYear()} Your Name"></div>
    <div class="field-row"><label>ISBN</label><input type="text" id="ps-isbn" value="${esc(s.isbn)}"></div>
    <div class="field-row"><label>Other details</label><textarea id="ps-extra" rows="3" placeholder="Edition, publisher, credits...">${esc(s.extra)}</textarea></div>
    <details class="ps-pages" ${s.dedication || s.epigraph || s.acknowledgments || s.about ? "open" : ""}>
      <summary>Dedication, epigraph, acknowledgments, about the author</summary>
      <div class="hint" style="margin-top:4px">Leave any of these empty to leave the page out. The dedication and epigraph come before the contents; acknowledgments and about the author come after the last piece.</div>
      <div class="field-row"><label for="ps-dedication">Dedication</label><textarea id="ps-dedication" rows="2" placeholder="for M.">${esc(s.dedication)}</textarea></div>
      <div class="field-row"><label for="ps-epigraph">Epigraph</label><textarea id="ps-epigraph" rows="3" placeholder="A quotation, and who said it">${esc(s.epigraph)}</textarea></div>
      <div class="field-row"><label for="ps-acknowledgments">Acknowledgments ${fromSnippet("acknowledgments", ["ack"])}</label><textarea id="ps-acknowledgments" rows="4" placeholder="Thanks to the editors of the magazines where these first appeared...">${esc(s.acknowledgments)}</textarea></div>
      <div class="field-row"><label for="ps-about">About the author ${fromSnippet("about", ["bio_long", "bio_short"])}</label><textarea id="ps-about" rows="4">${esc(s.about)}</textarea></div>
    </details>
    <div class="checkbox-row"><input type="checkbox" id="ps-title-page" ${s.title_page ? "checked" : ""}><label for="ps-title-page">Title page</label></div>
    <div class="checkbox-row"><input type="checkbox" id="ps-contents" ${s.contents ? "checked" : ""}><label for="ps-contents">Contents page</label></div>
    <div class="covers">${coverHtml(p, "front", s.covers.front)}${coverHtml(p, "back", s.covers.back)}</div>
    <div class="hint">Covers are sized to fit the page. The details above go on the title and copyright pages.</div>
    <div class="scan-links" style="margin-top:10px">
      <button class="btn btn-small btn-gold" data-project-export="pdf">Export PDF proof</button>
      <button class="btn btn-small btn-ghost" data-project-export="docx">Word</button>
      <button class="btn btn-small btn-ghost" data-project-export="epub" title="An ebook, with the front cover, contents and these pages">EPUB</button>
      <button class="btn btn-small btn-ghost" data-project-export="txt">Text</button>
      <button class="btn btn-small btn-ghost" id="ps-audio" title="Read the project into an audiobook">Audio</button>
      <button class="btn btn-small btn-ghost" id="ps-video" title="A video of the words, in time with a narration">Video</button>
    </div>
    <div id="project-share-result"></div>`;

  const collect = () => ({
    trim: document.getElementById("ps-trim").value,
    subtitle: document.getElementById("ps-subtitle").value,
    author: document.getElementById("ps-author").value,
    copyright: document.getElementById("ps-copyright").value,
    isbn: document.getElementById("ps-isbn").value,
    extra: document.getElementById("ps-extra").value,
    title_page: document.getElementById("ps-title-page").checked,
    contents: document.getElementById("ps-contents").checked,
    dedication: document.getElementById("ps-dedication").value,
    epigraph: document.getElementById("ps-epigraph").value,
    acknowledgments: document.getElementById("ps-acknowledgments").value,
    about: document.getElementById("ps-about").value,
  });
  let saveTimer = null;
  const save = () => postShare(`/api/projects/${p.id}/share`, collect());
  el.querySelectorAll(".ps-snippet").forEach((sel) => sel.addEventListener("change", async (ev) => {
    ev.stopPropagation();
    if (!sel.value) return;
    const box = document.getElementById(`ps-${sel.dataset.for}`);
    try {
      const r = await postJson(`/api/snippets/${encodeURIComponent(sel.value)}/fill`, { name: document.getElementById("ps-author").value.trim() });
      if (box.value.trim() && !confirm("Replace what's there with this snippet?")) { sel.value = ""; return; }
      box.value = r.text;
      sel.value = "";
      await save();
    } catch (e) { toast(e.message, true); }
  }));
  el.querySelectorAll("input:not([type=file]), select:not(.ps-snippet), textarea").forEach((input) =>
    input.addEventListener("change", () => { clearTimeout(saveTimer); saveTimer = setTimeout(() => save().catch((e) => toast(e.message, true)), 150); }));
  el.querySelectorAll("[data-cover]").forEach((input) => input.addEventListener("change", async () => {
    if (!input.files[0]) return;
    try { await save(); await uploadFile(`/api/projects/${p.id}/cover/${input.dataset.cover}`, input.files[0]); renderProjectShare(p); }
    catch (err) { toast(err.message, true); }
  }));
  el.querySelectorAll("[data-cover-remove]").forEach((b) => b.addEventListener("click", async () => {
    try { await save(); await postShare(`/api/projects/${p.id}/cover/${b.dataset.coverRemove}/delete`); renderProjectShare(p); }
    catch (err) { toast(err.message, true); }
  }));
  document.getElementById("ps-audio").addEventListener("click", async () => {
    try { await save(); } catch (err) { toast(err.message, true); return; }
    openNarration({ kind: "project", id: p.id, title: p.name, which: "final" });
  });
  document.getElementById("ps-video").addEventListener("click", async () => {
    try { await save(); } catch (err) { toast(err.message, true); return; }
    openVideo({ kind: "project", id: p.id, title: p.name });
  });
  el.querySelectorAll("[data-project-export]").forEach((b) => b.addEventListener("click", async () => {
    b.disabled = true;
    try {
      await save();
      const r = await postShare(`/api/projects/${p.id}/export`, { format: b.dataset.projectExport });
      const out = document.getElementById("project-share-result");
      out.innerHTML = exportResultHtml(r) +
        `<div class="hint">${r.finals} of ${r.entries} entries used a final draft.</div>`;
      wireExportResult(out);
    } catch (err) { toast(err.message, true); }
    b.disabled = false;
  }));
}
