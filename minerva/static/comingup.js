// "Coming up" on Home: planned submissions with a deadline soon, venues
// whose reading period opens or closes soon, submissions past the date a
// reply was expected, and pieces with a final draft that aren't out
// anywhere. Loaded after the rest of Home so it never holds it up.

function monthDay(iso) {
  return new Date(`${iso.slice(0, 10)}T00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function inDays(n) {
  return n === 0 ? "today" : n === 1 ? "tomorrow" : `in ${n} days`;
}

function comingUpHtml(c) {
  const groups = [];
  if (c.deadlines.length) {
    groups.push(`<div class="cu-group"><h4>Deadlines</h4><ul>${c.deadlines.map((d, i) => `
      <li><a href="#" data-cu-sub="d${i}"><strong>${esc(d.sub.title)}</strong> to ${esc(d.sub.venue)}</a>
        <span class="${d.days <= 3 ? "warn-text" : "muted"}">due ${inDays(d.days)}, ${monthDay(d.on)}</span></li>`).join("")}</ul></div>`);
  }
  if (c.overdue.length) {
    groups.push(`<div class="cu-group"><h4>Past the expected reply</h4><ul>${c.overdue.map((o, i) => `
      <li><a href="#" data-cu-sub="o${i}"><strong>${esc(o.sub.title)}</strong> at ${esc(o.sub.venue)}</a>
        <span class="muted">reply expected ${plural(o.days, "day", "days")} ago</span></li>`).join("")}</ul></div>`);
  }
  if (c.reading.length) {
    groups.push(`<div class="cu-group"><h4>Reading periods</h4><ul>${c.reading.map((r) => `
      <li><a href="#" data-cu-venue="${esc(r.venue)}"><strong>${esc(r.venue)}</strong></a>
        <span class="${r.event === "closes" ? "warn-text" : "muted"}">${r.event} ${inDays(r.days)}, ${monthDay(r.on)}</span></li>`).join("")}</ul></div>`);
  }
  if (c.ready.length) {
    groups.push(`<div class="cu-group"><h4>Ready to send</h4>
      <p class="hint" style="margin-top:0">These have a final draft and aren't out anywhere.</p>
      <div class="cu-ready">${c.ready.map((r) => `<a href="#" class="tag-chip" data-home-open="${r.id}">${esc(r.title)}</a>`).join("")}
      ${c.ready_total > c.ready.length ? `<span class="muted">and ${c.ready_total - c.ready.length} more</span>` : ""}</div></div>`);
  }
  if (!groups.length) return "";
  return `<section class="panel coming-up">
    <h3>Coming up <span class="muted">· the next ${c.window_days} days</span></h3>
    <div class="cu-groups">${groups.join("")}</div>
  </section>`;
}

async function loadComingUp(root, refresh) {
  const box = root.querySelector("#coming-up");
  if (!box) return;
  let c;
  try { c = await api("/api/home/coming-up"); } catch (e) { return; }
  if (!document.body.contains(box)) return;
  box.innerHTML = comingUpHtml(c);
  box.querySelectorAll("[data-cu-sub]").forEach((a) => a.addEventListener("click", (ev) => {
    ev.preventDefault();
    const key = a.dataset.cuSub;
    const item = (key[0] === "d" ? c.deadlines : c.overdue)[Number(key.slice(1))];
    openSubDialog({ sub: item.sub, onDone: refresh });
  }));
  box.querySelectorAll("[data-cu-venue]").forEach((a) => a.addEventListener("click", (ev) => {
    ev.preventDefault();
    openVenueDialog(a.dataset.cuVenue, refresh);
  }));
  box.querySelectorAll("[data-home-open]").forEach((a) => a.addEventListener("click", (ev) => {
    ev.preventDefault();
    state.view = "entries";
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === "entries"));
    state.returnTo = { view: "home" };
    openEntry(Number(a.dataset.homeOpen));
  }));
}
