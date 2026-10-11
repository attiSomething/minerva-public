// Home: what's happening in the library, plus the how-to guides.

function greeting() {
  const h = new Date().getHours();
  const name = typeof currentUsername === "function" ? currentUsername() : "";
  return (h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening") + (name ? `, ${name}` : "");
}

function longDate(iso) {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
}

function weekLabel(iso) {
  return new Date(iso + "T00:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function compareLine(now, before, unit) {
  if (now === before) return `Same as ${unit}`;
  const diff = now - before;
  return `${diff > 0 ? "▲" : "▼"} ${Math.abs(diff).toLocaleString()} ${diff > 0 ? "more" : "fewer"} than ${unit}`;
}

function encouragement(s) {
  if (s.streak.current >= 2) return `You've saved drafts ${s.streak.current} days running. Keep the streak going.`;
  if (s.streak.current === 1) return "You've written today or yesterday. One more day starts a streak.";
  if (s.week.saves > 0) return `${plural(s.week.saves, "draft", "drafts")} saved so far this week.`;
  if (s.totals.to_edit) return `${plural(s.totals.to_edit, "entry is", "entries are")} flagged To Edit. A good place to start.`;
  return "Pick up a draft, or bring in something new from your scans.";
}

function tile(label, value, sub, cls) {
  return `<div class="stat-tile ${cls || ""}">
    <div class="stat-label">${label}</div>
    <div class="stat-value">${value}</div>
    ${sub ? `<div class="stat-sub">${sub}</div>` : ""}
  </div>`;
}

function weeksChartHtml(weeks) {
  const W = 600, H = 190, left = 34, bottom = 26, top = 12;
  const max = Math.max(4, ...weeks.map((w) => w.saves));
  const step = Math.pow(10, Math.floor(Math.log10(max / 4)));
  const tick = [1, 2, 5, 10].map((m) => m * step).find((t) => max / t <= 4);
  const yMax = Math.ceil(max / tick) * tick;
  const right = 14, plotH = H - top - bottom, colW = (W - left - right) / weeks.length, barW = Math.min(28, colW * 0.56);
  const y = (v) => top + plotH - (v / yMax) * plotH;
  let grid = "";
  for (let v = 0; v <= yMax; v += tick) {
    grid += `<line class="chart-grid" x1="${left}" x2="${W - right}" y1="${y(v)}" y2="${y(v)}"/>`
      + `<text class="chart-axis" x="${left - 8}" y="${y(v) + 4}" text-anchor="end">${v}</text>`;
  }
  const bars = weeks.map((w, i) => {
    const cx = left + colW * i + colW / 2;
    const h = Math.max(0, y(0) - y(w.saves));
    const last = i === weeks.length - 1;
    const r = Math.min(4, h);
    const x0 = cx - barW / 2, yTop = y(w.saves);
    const path = h > 0
      ? `M${x0} ${y(0)} V${yTop + r} Q${x0} ${yTop} ${x0 + r} ${yTop} H${x0 + barW - r} Q${x0 + barW} ${yTop} ${x0 + barW} ${yTop + r} V${y(0)}Z`
      : "";
    const label = (i % 2 === (weeks.length - 1) % 2) ? `<text class="chart-axis" x="${cx}" y="${H - 8}" text-anchor="middle">${last ? "This week" : weekLabel(w.start)}</text>` : "";
    return `<g class="chart-col" data-i="${i}">
      <rect class="chart-hit" x="${left + colW * i}" y="${top}" width="${colW}" height="${plotH}"/>
      ${path ? `<path class="chart-bar ${last ? "current" : ""}" d="${path}"/>` : ""}
      ${label}
    </g>`;
  }).join("");
  return `<div class="chart-wrap">
    <svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Drafts saved per week for the last ${weeks.length} weeks">${grid}${bars}</svg>
    <div class="chart-tip hidden"></div>
  </div>`;
}

function wireWeeksChart(root, weeks) {
  const wrap = root.querySelector(".chart-wrap");
  if (!wrap) return;
  const tip = wrap.querySelector(".chart-tip");
  wrap.querySelectorAll(".chart-col").forEach((g) => {
    g.addEventListener("mouseenter", () => {
      const w = weeks[Number(g.dataset.i)];
      tip.innerHTML = `<strong>Week of ${weekLabel(w.start)}</strong><br>${plural(w.saves, "draft saved", "drafts saved")}`
        + (w.started ? `<br>${plural(w.started, "entry started", "entries started")}` : "");
      const box = g.querySelector(".chart-hit").getBoundingClientRect(), outer = wrap.getBoundingClientRect();
      tip.style.left = `${Math.min(outer.width - 150, Math.max(0, box.left - outer.left + box.width / 2 - 75))}px`;
      tip.classList.remove("hidden");
      g.classList.add("hover");
    });
    g.addEventListener("mouseleave", () => { tip.classList.add("hidden"); g.classList.remove("hover"); });
  });
}

function categoriesHtml(cats) {
  if (!cats.some((c) => c.words)) return `<div class="hint" style="margin-top:0">Each category's words show here once you've written some.</div>`;
  const max = Math.max(1, ...cats.map((c) => c.words));
  return `<div class="cat-bars">${cats.map((c) => `
    <div class="cat-row" title="${esc(c.name)}: ${plural(c.entries, "entry", "entries")}, ${plural(c.words, "word", "words")}">
      <div class="cat-name">${esc(c.name)}</div>
      <div class="cat-track"><div class="cat-fill" style="width:${(c.words / max) * 100}%"></div></div>
      <div class="cat-num">${c.words.toLocaleString()}</div>
    </div>`).join("")}</div>`;
}

function milestoneHtml(s) {
  if (!s.milestone || !s.totals.words) return "";
  const pct = Math.min(100, (s.totals.words / s.milestone.words) * 100);
  return `<div class="milestone">
    <div class="milestone-text"><strong>${s.milestone.to_go.toLocaleString()}</strong> words to ${s.milestone.words.toLocaleString()}</div>
    <div class="milestone-track" role="progressbar" aria-valuenow="${Math.round(pct)}" aria-valuemin="0" aria-valuemax="100"><div class="milestone-fill" style="width:${pct}%"></div></div>
  </div>`;
}

function historyHtml(history) {
  if (history.length < 2) {
    return `<div class="hint">Minerva notes your library's size each day it opens. A trend line appears here from the second day.</div>`;
  }
  const W = 600, H = 70, pad = 6;
  const vals = history.map((h) => h.words);
  const lo = Math.min(...vals), hi = Math.max(...vals), span = Math.max(1, hi - lo);
  const t0 = new Date(history[0].day).getTime(), t1 = new Date(history[history.length - 1].day).getTime();
  const pts = history.map((h) => {
    const x = pad + ((new Date(h.day).getTime() - t0) / Math.max(1, t1 - t0)) * (W - 2 * pad);
    const yy = H - pad - ((h.words - lo) / span) * (H - 2 * pad);
    return [x, yy];
  });
  const first = history[0], last = history[history.length - 1];
  const diff = last.words - first.words;
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" role="img" aria-label="Total words from ${first.day} to ${last.day}">
      <path class="spark-line" d="M${pts.map((p) => p.map((v) => v.toFixed(1)).join(" ")).join(" L")}"/>
      <circle class="spark-dot" cx="${pts[pts.length - 1][0]}" cy="${pts[pts.length - 1][1]}" r="4"/>
    </svg>
    <div class="hint">${diff >= 0 ? "+" : "−"}${Math.abs(diff).toLocaleString()} words since ${weekLabel(first.day)}</div>`;
}

function recentHtml(recent) {
  if (!recent.length) return `<div class="hint">Nothing yet. Open an entry from Entries to start.</div>`;
  return `<ul class="recent-list">${recent.map((r) => `
    <li><a href="#" data-home-open="${r.id}">${esc(r.title)}</a>
      <span class="recent-meta">${esc(r.category)} · ${plural(r.words, "word", "words")} · ${shortDate(r.day)}</span></li>`).join("")}</ul>`;
}

function howtoCardsHtml(howtos) {
  return `<div class="howto-cards">${howtos.map((h) => `
    <button class="howto-card" data-howto="${esc(h.name)}">
      <div class="howto-card-art">${h.cover}</div>
      <div class="howto-card-body">
        <div class="howto-card-title">${esc(h.title)}</div>
        <div class="howto-card-summary">${esc(h.summary)}</div>
      </div>
    </button>`).join("")}</div>`;
}

async function renderHome() {
  // the first time, the launch screen stays up and counts these off
  if (!launchEl()) appEl.innerHTML = `<div class="empty-state">Loading...</div>`;
  let s, howtos, bk, checks, fr, setup, sync;
  try {
    [s, howtos, bk, checks, fr, setup, sync] = await Promise.all(launchTrack([
      ["your statistics", api("/api/stats")],
      ["the how-tos", api("/api/howtos").catch(() => [])],
      ["backups", api("/api/backup").catch(() => null)],
      ["the library check", api("/api/library/check").catch(() => ({ issues: [] }))],
      ["getting started", api("/api/firstrun").catch(() => null)],
      ["setup", api("/api/setup/status").catch(() => null)],
      ["synced folders", api("/api/sync/pending").catch(() => null)],
    ]));
  } catch (err) {
    if (launchEl()) { launchFailed(`Couldn't load Home: ${err.message}`); return; }
    appEl.innerHTML = `<div class="empty-state">Could not load the home page: ${esc(err.message)}</div>`;
    return;
  }
  if (state.view !== "home") return;
  const t = s.totals;
  const monthWords = s.month.words_added;
  appEl.innerHTML = `
    <div class="home">
      ${sampleBannerHtml(setup)}
      <section class="home-hero">
        <div>
          <h1>${esc(greeting())}</h1>
          <div class="home-date">${longDate(s.today)}</div>
        </div>
        <div class="home-hero-side">
          <p class="home-nudge">${esc(encouragement(s))}</p>
          <button class="btn btn-gold" data-new-entry>New entry</button>
        </div>
      </section>

      <div id="update-notice"></div>
      ${gettingStartedHtml(fr)}
      ${syncStripHtml(sync)}
      ${bk ? backupStripHtml(bk) : ""}
      ${libraryCheckStripHtml([...checks.issues, ...(checks.lost_notes || [])])}

      <section class="stat-tiles">
        ${tile("Entries", t.entries.toLocaleString(), `${plural(s.categories.length, "category", "categories")}`)}
        ${tile("Words", t.words.toLocaleString(), monthWords === null ? "" : `${monthWords >= 0 ? "+" : "−"}${Math.abs(monthWords).toLocaleString()} this month`)}
        ${tile("This week", plural(s.week.saves, "save", "saves"), compareLine(s.week.saves, s.week.last, "last week"))}
        ${tile("This month", plural(s.month.saves, "save", "saves"), compareLine(s.month.saves, s.month.last, "last month"))}
        ${tile("Streak", plural(s.streak.current, "day", "days"), `Longest: ${plural(s.streak.longest, "day", "days")}`, s.streak.current ? "gold" : "")}
        ${tile("Finished", plural(t.finals, "final", "finals"), `${t.published.toLocaleString()} published · ${t.projects.toLocaleString()} ${t.projects === 1 ? "project" : "projects"}`)}
      </section>

      ${goalsPanelHtml(s.goals)}
      <div id="coming-up"></div>

      <section class="home-grid">
        <div class="panel home-chart">
          <h3>Drafts saved per week</h3>
          <div class="hint" style="margin-top:0">Every save counts, including older drafts kept in Archive. Started this month: ${s.month.started.toLocaleString()} (last month ${s.month.started_last.toLocaleString()}).</div>
          ${weeksChartHtml(s.weeks)}
        </div>
        <div class="panel">
          <h3>Words by category</h3>
          ${categoriesHtml(s.categories)}
          ${milestoneHtml(s)}
        </div>
        <div class="panel">
          <h3>Recently worked on</h3>
          ${recentHtml(s.recent)}
        </div>
        <div class="panel">
          <h3>Library size</h3>
          ${historyHtml(s.history)}
          <div class="home-flags">
            <span>${plural(t.to_edit, "entry", "entries")} to edit</span>
            <span>${plural(t.to_record, "entry", "entries")} to record</span>
            <a href="#" data-goto-subs>${plural(s.submissions.waiting, "submission", "submissions")} waiting${s.submissions.overdue ? ` (${s.submissions.overdue} overdue)` : ""}</a>
          </div>
        </div>
      </section>

      ${howtos.length ? `<section class="home-howtos">
        <h2>How-tos ${helpLinkHtml("home", "How Home works")}</h2>
        ${howtoCardsHtml(howtos)}
      </section>` : ""}
    </div>`;

  wireWeeksChart(appEl, s.weeks);
  wireSampleBanner(appEl);
  wireSyncStrip(appEl, () => { if (state.view === "home") renderHome(); });
  wireGettingStarted(appEl, fr, () => { if (state.view === "home") renderHome(); });
  wireLibraryCheckStrip(appEl);
  wireGoalsPanel(appEl, () => { if (state.view === "home") renderHome(); });
  loadUpdateNotice(document.getElementById("update-notice"));
  loadComingUp(appEl, () => { if (state.view === "home") renderHome(); });
  if (bk) {
    const refresh = () => { if (state.view === "home") renderHome(); };
    wireBackupStrip(appEl, refresh);
    resumeBackupPolling(bk, refresh);
  }
  appEl.querySelectorAll("[data-new-entry]").forEach((b) => b.addEventListener("click", () => openNewEntry()));
  appEl.querySelectorAll("[data-home-open]").forEach((a) => a.addEventListener("click", (ev) => {
    ev.preventDefault();
    state.view = "entries";
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === "entries"));
    state.returnTo = { view: "home" };
    openEntry(Number(a.dataset.homeOpen));
  }));
  appEl.querySelectorAll("[data-goto-subs]").forEach((a) => a.addEventListener("click", (ev) => {
    ev.preventDefault();
    subState.filters = { open: true };
    setView("submissions");
  }));
  appEl.querySelectorAll("[data-howto]").forEach((b) => b.addEventListener("click", () => openHowto(b.dataset.howto)));
}

function openHowto(name) {
  state.openDoc = { kind: "howto", name };
  setView("docs");
}
