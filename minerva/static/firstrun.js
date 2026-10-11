// Getting started: the card on Home that walks one piece from a draft to a
// submission and a PDF, the sample library (made-up writing in its own
// folder, to explore safely), and the empty states that say what to do
// next. Used by home.js, onboarding.js, app.js, submissions.js, views.js.

const FIRST_RUN_STEPS = [
  { id: "draft", title: "Bring in a draft", where: "New entry and Import files are at the top of Entries, and New entry is on Home too.",
    actions: [["New entry", () => openNewEntry()], ["Import files", () => openFileImport()]] },
  { id: "edit", title: "Open it in the editor", where: "Click any title in Entries. The editor saves every version, so you can always go back.",
    actions: [["Open it", (fr) => firstRunOpenLatest(fr)]] },
  { id: "submission", title: "Add a submission", where: "Every entry's page has a Submissions panel; the Submissions tab lists them all.",
    actions: [["Add a submission", (fr) => firstRunAddSubmission(fr)]] },
  { id: "pdf", title: "Make a PDF", where: "On any entry's page, Share > Export, with a standard manuscript layout if you want one.",
    actions: [["Show me", (fr) => firstRunOpenLatest(fr, "share-panel")]] },
];

let firstRunEditMarked = false;

function markFirstRun(step) {
  if (step === "edit") {
    if (firstRunEditMarked) return;
    firstRunEditMarked = true;
  }
  postJson("/api/firstrun", { done: step }).catch(() => {});
}

async function firstRunOpenLatest(fr, scrollTo) {
  if (!fr.latest) { toast("Bring in a draft first."); return; }
  state.view = "entries";
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === "entries"));
  state.returnTo = { view: "home" };
  await openEntry(fr.latest.id);
  if (scrollTo) {
    const el = document.getElementById(scrollTo);
    if (el) { el.scrollIntoView({ behavior: "smooth", block: "center" }); el.classList.add("pulse"); setTimeout(() => el.classList.remove("pulse"), 2400); }
  }
}

function firstRunAddSubmission(fr) {
  const piece = fr.latest ? { kind: "entry", id: fr.latest.id, title: fr.latest.title } : null;
  openSubDialog({ piece, onDone: () => { if (state.view === "home") renderHome(); } });
}

function gettingStartedHtml(fr) {
  if (!fr || fr.dismissed) return "";
  const done = FIRST_RUN_STEPS.filter((s) => fr.steps[s.id]).length;
  if (done === FIRST_RUN_STEPS.length) return "";
  return `
    <section class="panel getting-started" aria-labelledby="gs-h">
      <div class="gs-head">
        <h3 id="gs-h">Getting started: one piece, start to finish</h3>
        <span class="muted">${done} of ${FIRST_RUN_STEPS.length} done</span>
        <span class="spacer"></span>
        <button class="btn btn-small btn-ghost" id="gs-hide">Hide this</button>
      </div>
      <ol class="gs-steps">${FIRST_RUN_STEPS.map((s, i) => {
        const isDone = fr.steps[s.id];
        return `<li class="gs-step ${isDone ? "done" : ""}">
          <span class="gs-num" aria-hidden="true">${isDone ? "✓" : i + 1}</span>
          <div class="gs-body">
            <div class="gs-title">${esc(s.title)}${isDone ? ` <span class="sr-only">(done)</span>` : ""}</div>
            <div class="hint">${esc(s.where)}</div>
          </div>
          ${isDone ? "" : `<div class="gs-actions">
            ${s.actions.map(([label], k) => `<button class="btn btn-small ${k === 0 ? "" : "btn-ghost"}" data-gs="${s.id}" data-gs-k="${k}">${esc(label)}</button>`).join("")}
            <button class="btn btn-small btn-ghost" data-gs-skip="${s.id}">Skip</button>
          </div>`}
        </li>`;
      }).join("")}</ol>
      <div class="hint">Want to look around first? <a href="#" data-sample-open>Explore the sample library</a>: made-up writing in a separate folder, so nothing you try there touches your own.</div>
    </section>`;
}

function wireGettingStarted(root, fr, refresh) {
  const box = root.querySelector(".getting-started");
  if (!box) return;
  box.querySelector("#gs-hide").addEventListener("click", async () => {
    await postJson("/api/firstrun", { dismissed: true }).catch(() => {});
    toast("Hidden. Help has the same steps whenever you want them.");
    refresh();
  });
  box.querySelectorAll("[data-gs]").forEach((b) => b.addEventListener("click", () => {
    const step = FIRST_RUN_STEPS.find((s) => s.id === b.dataset.gs);
    step.actions[Number(b.dataset.gsK)][1](fr);
  }));
  box.querySelectorAll("[data-gs-skip]").forEach((b) => b.addEventListener("click", async () => {
    await postJson("/api/firstrun", { done: b.dataset.gsSkip }).catch(() => {});
    refresh();
  }));
  wireSampleLinks(box);
}

// ---- sample library ---------------------------------------------------------

async function openSampleLibrary(startOver) {
  try {
    const r = await postJson("/api/setup/sample", { start_over: !!startOver });
    toast(`Opened the sample library (${plural(r.total_entries, "entry", "entries")}). Everything in it is made up.`);
    state.categories = null;
    state.projectsCache = [];
    await setView("home");
    if (typeof refreshAlertsBadge === "function") refreshAlertsBadge();
    return r;
  } catch (e) {
    toast(e.message, true);
    return null;
  }
}

async function leaveSampleLibrary() {
  try {
    const r = await postJson("/api/setup/sample/leave", {});
    toast(`Back in ${r.library_root}.`);
    state.categories = null;
    state.projectsCache = [];
    await setView("home");
    if (typeof refreshAlertsBadge === "function") refreshAlertsBadge();
  } catch (e) {
    toast(e.message, true);
  }
}

function wireSampleLinks(root) {
  root.querySelectorAll("[data-sample-open]").forEach((a) => a.addEventListener("click", (ev) => {
    ev.preventDefault();
    openSampleLibrary(false);
  }));
}

function sampleBannerHtml(status) {
  if (!status || !status.is_sample) return "";
  return `<div class="sample-banner" role="status">
    <span><strong>You're in the sample library.</strong> Every piece, magazine and submission here is made up, and it lives in its own folder, so try anything.</span>
    <span class="spacer"></span>
    ${status.library_before_sample ? `<button class="btn btn-small btn-gold" id="sample-leave">Back to my library</button>` : `<button class="btn btn-small btn-gold" id="sample-own">Open my own library</button>`}
    <button class="btn btn-small btn-ghost" id="sample-reset" title="Put the sample back the way it started">Start the sample over</button>
  </div>`;
}

function wireSampleBanner(root) {
  const leave = root.querySelector("#sample-leave");
  if (leave) leave.addEventListener("click", leaveSampleLibrary);
  const own = root.querySelector("#sample-own");
  if (own) own.addEventListener("click", async () => {
    await setView("settings");
    const b = document.getElementById("switch-lib");
    if (b) { b.click(); b.scrollIntoView({ block: "start" }); }
  });
  const reset = root.querySelector("#sample-reset");
  if (reset) reset.addEventListener("click", () => {
    if (confirm("Start the sample library over? Changes you made in the sample are lost. Your own library isn't affected.")) openSampleLibrary(true);
  });
}

// ---- empty states -------------------------------------------------------------

function emptyLibraryHtml() {
  return `<div class="empty-state empty-action">
    <p>No entries yet. Write or paste one, or bring drafts in from Word, Google Docs, Markdown and other files.</p>
    <div class="scan-links">
      <button class="btn btn-gold btn-small" data-empty-new>New entry</button>
      <button class="btn btn-ghost btn-small" data-empty-import>Import files</button>
      <button class="btn btn-ghost btn-small" data-empty-scans>Transcribe scans</button>
    </div>
    <p class="hint">Or <a href="#" data-sample-open>explore the sample library</a> first.</p>
  </div>`;
}

function wireEmptyActions(root) {
  root.querySelectorAll("[data-empty-new]").forEach((b) => b.addEventListener("click", () => openNewEntry()));
  root.querySelectorAll("[data-empty-import]").forEach((b) => b.addEventListener("click", () => openFileImport()));
  root.querySelectorAll("[data-empty-scans]").forEach((b) => b.addEventListener("click", () => setView("scans")));
  wireSampleLinks(root);
}
