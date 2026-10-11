// Venues: notes kept per place you submit to (reading periods, fee, usual
// wait, website) and the history of what you've sent there. Picking a known
// venue in the submission dialog fills in its fee and expected response.

function venueHint(v) {
  const bits = [];
  if (v.reading_periods) bits.push(`Reads: ${esc(v.reading_periods)}`);
  if (v.max_lines) bits.push(`Up to ${v.max_lines} lines a piece`);
  const st = v.stats;
  if (st.count) {
    bits.push(`${st.count} sent before` + (st.acceptance_rate === null ? "" : `, ${st.accepted} accepted`)
      + (st.median_wait !== null ? `, usually ${st.median_wait} days to reply` : ""));
  }
  if (v.website) bits.push(`<a href="#" data-venue-open>${esc(v.website)}</a>`);
  return bits.join(" · ");
}

function venueUrl(site) {
  return /^https?:\/\//i.test(site) ? site : `https://${site}`;
}

// Called by the submission dialog when the venue field changes.
async function applyVenueToDialog(name, isNew) {
  const hint = document.getElementById("sub-venue-hint");
  if (!hint) return;
  hint.innerHTML = "";
  subDialogState.venue = null;
  checkLineLimit();
  if (!name.trim()) return;
  let v;
  try { v = await api(`/api/venue?name=${encodeURIComponent(name.trim())}`); } catch (e) { return; }
  if (document.getElementById("sub-venue").value.trim().toLowerCase() !== v.name.toLowerCase()) return;
  hint.innerHTML = venueHint(v);
  subDialogState.venue = v;
  checkLineLimit();
  const link = hint.querySelector("[data-venue-open]");
  if (link) link.addEventListener("click", (ev) => { ev.preventDefault(); window.open(venueUrl(v.website), "_blank"); });
  if (!isNew) return;
  const cost = document.getElementById("sub-cost");
  const days = document.getElementById("sub-days");
  const s = v.suggested;
  if (!cost.value && s.cost !== null) cost.value = s.cost || "";
  if (s.currency && (!cost.value || Number(cost.value) === s.cost)) document.getElementById("sub-currency").value = s.currency;
  if (!days.value && s.response_days !== null) days.value = s.response_days;
}

// A new submission of an entry to a venue with a line limit warns when the
// piece runs over it.
const subDialogState = { piece: null, venue: null, lines: {} };

async function checkLineLimit() {
  const old = document.getElementById("sub-line-warn");
  if (old) old.remove();
  const { piece, venue } = subDialogState;
  if (!piece || piece.kind !== "entry" || !venue || !venue.max_lines) return;
  if (!(piece.id in subDialogState.lines)) {
    try { subDialogState.lines[piece.id] = (await api(`/api/entries/${piece.id}`)).line_count || 0; }
    catch (e) { return; }
  }
  const n = subDialogState.lines[piece.id];
  const hint = document.getElementById("sub-venue-hint");
  if (!hint || n <= venue.max_lines || subDialogState.venue !== venue || subDialogState.piece !== piece) return;
  hint.insertAdjacentHTML("afterend", `<div class="hint warn-text" id="sub-line-warn">${esc(piece.title)} is ${n} lines; ${esc(venue.name)} takes up to ${venue.max_lines}.</div>`);
}

// ---- the Venues list (a view of the Submissions tab) --------------------------

async function renderVenueList(el) {
  let list;
  try { list = await api("/api/venues"); }
  catch (e) { el.innerHTML = `<div class="empty-state">${esc(e.message)}</div>`; return; }
  if (!list.length) {
    el.innerHTML = `<div class="empty-state">No venues yet. They appear here once you add a submission, or you can start notes on one now.</div>`;
    return;
  }
  el.innerHTML = `
    <div class="table-scroll"><table class="entry-table subs-table">
      <thead><tr><th>Venue</th><th>Reading periods</th><th>Fee</th><th>Usual reply</th><th>Sent</th><th>Accepted</th></tr></thead>
      <tbody>${list.map((v, i) => `
        <tr data-venue="${i}">
          <td><b>${esc(v.name)}</b>${v.website ? `<div class="recent-meta">${esc(v.website)}</div>` : ""}</td>
          <td>${esc(v.reading_periods || "—")}</td>
          <td>${v.suggested.cost === null ? "—" : money(v.suggested.cost, v.suggested.currency)}</td>
          <td>${v.suggested.response_days === null ? "—" : `${v.suggested.response_days} days`}</td>
          <td>${v.stats.count}${v.stats.waiting ? ` <span class="muted">(${v.stats.waiting} waiting)</span>` : ""}</td>
          <td>${v.stats.acceptance_rate === null ? (v.stats.accepted || "—") : `${v.stats.accepted} <span class="muted">(${Math.round(v.stats.acceptance_rate * 100)}%)</span>`}</td>
        </tr>`).join("")}</tbody>
    </table></div>`;
  el.querySelectorAll("tr[data-venue]").forEach((tr) => tr.addEventListener("click", () =>
    openVenueDialog(list[Number(tr.dataset.venue)].name, () => renderVenueList(el))));
}

async function openVenueDialog(name, onDone) {
  let v = null;
  if (name) {
    try { v = await api(`/api/venue?name=${encodeURIComponent(name)}`); } catch (e) { toast(e.message, true); return; }
  }
  const val = v || { name: "", history: [], stats: { count: 0 } };
  closeSubDialog();
  const el = document.createElement("div");
  el.id = "sub-dialog";
  el.className = "modal-backdrop";
  el.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="venue-dialog-title">
      <h2 id="venue-dialog-title">${v ? esc(v.name) : "New venue"}</h2>
      <div class="sub-form">
        ${v ? "" : `<div class="field-row wide"><label for="venue-name">Name</label><input type="text" id="venue-name" placeholder="Magazine, press, contest..."></div>`}
        <div class="field-row wide"><label for="venue-website">Website</label>
          <input type="text" id="venue-website" value="${esc(val.website || "")}" placeholder="e.g. harborreview.org"></div>
        <div class="field-row wide"><label for="venue-periods">Reading periods</label>
          <input type="text" id="venue-periods" value="${esc(val.reading_periods || "")}" placeholder="e.g. September to November, all year"></div>
        <div class="field-row"><label for="venue-cost">Typical fee</label>
          <div class="sub-cost"><input type="text" id="venue-currency" value="${esc(val.currency || "$")}" aria-label="Currency" maxlength="4">
          <input type="number" id="venue-cost" min="0" step="0.01" value="${val.cost ?? ""}" placeholder="${v && v.stats.last_fee ? `last: ${money(v.stats.last_fee.cost, v.stats.last_fee.currency)}` : "0"}"></div></div>
        <div class="field-row"><label for="venue-days">Typical response (days)</label>
          <input type="number" id="venue-days" min="0" step="1" value="${val.response_days ?? ""}" placeholder="${v && v.stats.median_wait !== null ? `usually ${v.stats.median_wait}` : "e.g. 90"}"></div>
        <div class="field-row"><label for="venue-lines">Line limit per piece</label>
          <input type="number" id="venue-lines" min="1" step="1" value="${val.max_lines ?? ""}" placeholder="none"></div>
        <div class="field-row wide"><label for="venue-notes">Notes</label>
          <textarea id="venue-notes" rows="3" placeholder="Editors, what they like, how to submit...">${esc(val.notes || "")}</textarea></div>
      </div>
      ${v && v.history.length ? `
        <h3 class="venue-history-head">Sent here</h3>
        <ul class="sub-mini">${v.history.map((s) => `
          <li><div class="sub-mini-row"><span class="sub-mini-venue">${esc(s.title)}</span>${statusBadge(s)}
            <span class="sub-mini-date">${s.submitted_on ? shortDate(s.submitted_on) : s.deadline ? `due ${shortDate(s.deadline)}` : ""}</span></div></li>`).join("")}</ul>` : ""}
      <div class="modal-actions">
        <span style="flex:1"></span>
        <button class="btn btn-ghost" id="venue-cancel">Cancel</button>
        <button class="btn btn-gold" id="venue-save">Save notes</button>
      </div>
    </div>`;
  document.body.appendChild(el);
  document.addEventListener("keydown", subDialogKeys);
  el.addEventListener("click", (ev) => { if (ev.target === el) closeSubDialog(); });
  document.getElementById("venue-cancel").addEventListener("click", closeSubDialog);
  document.getElementById("venue-save").addEventListener("click", async () => {
    const get = (id) => document.getElementById(id).value;
    try {
      await postJson("/api/venue", {
        name: v ? v.name : get("venue-name"), website: get("venue-website"), reading_periods: get("venue-periods"),
        cost: get("venue-cost"), currency: get("venue-currency"), response_days: get("venue-days"), notes: get("venue-notes"),
        max_lines: get("venue-lines"),
      });
      closeSubDialog();
      toast("Saved.");
      subOptions(true).catch(() => {});
      if (onDone) onDone();
    } catch (e) { toast(e.message, true); }
  });
  document.getElementById(v ? "venue-website" : "venue-name").focus();
}
