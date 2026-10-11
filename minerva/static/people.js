// People: everyone the transcribed journals mention, under the Entries tab.
// "Find people" sends one journal's Master to the organizing model (only when
// asked); names that are the same person can be merged, and merges hold
// through later runs.

const peopleState = { data: null, open: new Set(), filter: "", source: "", timer: null };

async function renderPeople() {
  clearTimeout(peopleState.timer);
  appEl.innerHTML = `${entryPanesHtml("people")}<div id="people-body"><div class="empty-state">Loading...</div></div>`;
  wireEntryPanes();
  try { peopleState.data = await api("/api/people"); }
  catch (e) { document.getElementById("people-body").innerHTML = `<div class="empty-state">${esc(e.message)}</div>`; return; }
  drawPeople();
  const [job] = peopleState.data.jobs;
  if (job) pollPeopleJob(job.id);
}

function sourceRunNote(s) {
  if (!s.ran_at) return "not read yet";
  return s.current ? `read ${dayDate(s.ran_at)}` : "changed since it was read";
}

function drawPeople() {
  const body = document.getElementById("people-body");
  const { people, sources } = peopleState.data;
  if (!sources.some((s) => s.name === peopleState.source)) {
    const next = sources.find((s) => !s.current) || sources[0];
    peopleState.source = next ? next.name : "";
  }
  const q = peopleState.filter.trim().toLowerCase();
  const shown = people.filter((p) => !q || [p.name, ...p.aliases].some((n) => n.toLowerCase().includes(q)));
  body.innerHTML = `
    <div class="people-find">
      ${sources.length ? `
        <label>Journal <select id="people-source">${sources.map((s) => `<option value="${esc(s.name)}" ${s.name === peopleState.source ? "selected" : ""}>${esc(s.name)} (${sourceRunNote(s)})</option>`).join("")}</select></label>
        <button class="btn btn-primary" id="people-find">Find people</button>
        <span class="hint">Sends the journal's text to your organizing model. Merges you've made are kept.</span>`
      : `<span class="hint">People are found in scanned journals once they have a Master.</span>`}
    </div>
    <div id="people-job"></div>
    ${people.length ? `
      <div class="people-tools">
        <input type="search" id="people-filter" placeholder="Search names..." value="${esc(peopleState.filter)}">
        <span class="recent-meta">${people.length} ${people.length === 1 ? "person" : "people"}</span>
        <button class="btn" id="people-merge" disabled>Merge</button>
      </div>
      <div class="table-scroll"><table class="entry-table people-table">
        <thead><tr><th></th><th>Name</th><th>Mentions</th><th>First</th><th>Last</th><th>Journals</th></tr></thead>
        <tbody>${shown.map(personRowHtml).join("")}</tbody>
      </table></div>`
    : sources.length ? `<div class="empty-state">No one found yet. Pick a journal and press Find people.</div>` : ""}`;
  wirePeople();
}

function personRowHtml(p) {
  const open = peopleState.open.has(p.id);
  return `<tr class="person-row" data-person="${p.id}">
      <td><input type="checkbox" data-pick="${p.id}" aria-label="Select ${esc(p.name)}"></td>
      <td><button class="link-btn" data-toggle="${p.id}" aria-expanded="${open}">${esc(p.name)}</button>
        ${p.aliases.length ? `<div class="recent-meta">also ${p.aliases.map(esc).join(", ")}</div>` : ""}</td>
      <td>${p.count}</td>
      <td>${p.first ? dayDate(p.first) : "—"}</td>
      <td>${p.last ? dayDate(p.last) : "—"}</td>
      <td>${p.sources.map(esc).join(", ")}</td>
    </tr>
    ${open ? `<tr class="person-detail"><td></td><td colspan="5">
      ${p.about ? `<p class="person-about">${esc(p.about)}</p>` : ""}
      <ul class="person-mentions">${p.mentions.map((m) => `
        <li><span class="recent-meta">${m.date ? esc(m.date) : "undated"}</span>
          ${esc(m.source)}, entry ${m.num}${m.title ? `: ${esc(m.title)}` : ""}
          ${m.filed ? ` <button class="link-btn" data-entry="${m.filed.id}">open ${esc(m.filed.title)}</button>` : ""}</li>`).join("")}</ul>
      <button class="btn btn-small btn-ghost" data-rename="${p.id}">Rename</button>
    </td></tr>` : ""}`;
}

function wirePeople() {
  const body = document.getElementById("people-body");
  const src = document.getElementById("people-source");
  if (src) src.addEventListener("change", () => { peopleState.source = src.value; });
  const find = document.getElementById("people-find");
  if (find) find.addEventListener("click", findPeople);
  const filter = document.getElementById("people-filter");
  if (filter) filter.addEventListener("input", () => {
    peopleState.filter = filter.value;
    drawPeople();
    const f = document.getElementById("people-filter");
    f.focus(); f.setSelectionRange(f.value.length, f.value.length);
  });
  body.querySelectorAll("[data-toggle]").forEach((b) => b.addEventListener("click", () => {
    const id = Number(b.dataset.toggle);
    if (peopleState.open.has(id)) peopleState.open.delete(id); else peopleState.open.add(id);
    drawPeople();
  }));
  body.querySelectorAll("[data-entry]").forEach((b) => b.addEventListener("click", () => {
    state.returnTo = { view: "people" };
    openEntry(Number(b.dataset.entry));
  }));
  body.querySelectorAll("[data-rename]").forEach((b) => b.addEventListener("click", () => renamePerson(Number(b.dataset.rename))));
  const merge = document.getElementById("people-merge");
  const picks = () => [...body.querySelectorAll("[data-pick]:checked")].map((c) => Number(c.dataset.pick));
  body.querySelectorAll("[data-pick]").forEach((c) => c.addEventListener("change", () => {
    const n = picks().length;
    merge.disabled = n < 2;
    merge.textContent = n >= 2 ? `Merge ${n} people` : "Merge";
  }));
  if (merge) merge.addEventListener("click", () => openMergeDialog(picks()));
}

async function findPeople() {
  const source = peopleState.source;
  let est;
  try { est = await postJson("/api/people/estimate", { source }); } catch (e) { toast(e.message, true); return; }
  const price = est.cost === null ? "" : est.cost < 0.01 ? ", under 1 cent at list price" : `, about $${est.cost.toFixed(2)} at list price`;
  const calls = est.calls > 1 ? ` in ${est.calls} parts` : "";
  if (!await aiConfirm(`Read ${est.entries} entries from ${source}${calls}? That's about ${est.input_tokens.toLocaleString()} tokens${price}.`)) return;
  try {
    const job = await postJson("/api/people/find", { source });
    pollPeopleJob(job.id);
  } catch (e) {
    toast(e.message, true);
  }
}

async function pollPeopleJob(id) {
  clearTimeout(peopleState.timer);
  const box = document.getElementById("people-job");
  if (!box) return;
  let j;
  try { j = await api(`/api/jobs/${id}`); } catch (e) { return; }
  const btn = document.getElementById("people-find");
  if (btn) btn.disabled = j.status === "running";
  if (j.status === "running") {
    box.innerHTML = `<div class="job-box"><div class="job-head"><b>Finding people</b> ${esc(j.label)}</div>
      <div class="progress"><div style="width:${j.total ? Math.round((100 * j.done) / j.total) : 5}%"></div></div>
      <div class="hint">${esc(j.message || "Waiting for the model...")}</div></div>`;
    peopleState.timer = setTimeout(() => pollPeopleJob(id), 1500);
    return;
  }
  if (j.status === "done" && j.result) toast(`Found ${j.result.people} ${j.result.people === 1 ? "person" : "people"} in ${j.result.source}.`);
  else if (j.status === "failed") toast(j.error || "Finding people stopped with an error.", true);
  await renderPeople();
}

async function renamePerson(id) {
  const p = peopleState.data.people.find((x) => x.id === id);
  const name = prompt("Name", p.name);
  if (name === null || !name.trim() || name.trim() === p.name) return;
  try {
    peopleState.data.people = (await postJson(`/api/people/${id}/rename`, { name })).people;
    drawPeople();
  } catch (e) { toast(e.message, true); }
}

function openMergeDialog(ids) {
  const chosen = peopleState.data.people.filter((p) => ids.includes(p.id));
  const el = document.createElement("div");
  el.className = "modal-backdrop";
  el.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="merge-title">
      <h2 id="merge-title">Merge ${chosen.length} people</h2>
      <p class="hint">They become one person. Every name here will point to them, including on later runs.</p>
      <div class="field-row wide"><label for="merge-keep">Keep the name</label>
        <select id="merge-keep">${chosen.map((p) => `<option value="${p.id}">${esc(p.name)} (${p.count})</option>`).join("")}</select></div>
      <div class="modal-actions"><span style="flex:1"></span>
        <button class="btn btn-ghost" id="merge-cancel">Cancel</button>
        <button class="btn btn-gold" id="merge-ok">Merge</button></div>
    </div>`;
  document.body.appendChild(el);
  const close = () => el.remove();
  el.addEventListener("click", (ev) => { if (ev.target === el) close(); });
  el.querySelector("#merge-cancel").addEventListener("click", close);
  el.querySelector("#merge-ok").addEventListener("click", async () => {
    const keep = Number(el.querySelector("#merge-keep").value);
    try {
      peopleState.data.people = (await postJson("/api/people/merge", { keep, others: ids.filter((i) => i !== keep) })).people;
      peopleState.open.add(keep);
      close();
      drawPeople();
    } catch (e) { toast(e.message, true); }
  });
}
