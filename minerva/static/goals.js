// Word goals on Home and the project page.
// Depends on helpers from app.js (api, esc, toast, plural) and onboarding.js (jsonPost).

function signedWords(n) {
  return `${n < 0 ? "−" : ""}${Math.abs(n).toLocaleString()}`;
}

function goalBarHtml(label, words, goal, extra) {
  const pct = goal > 0 ? Math.max(0, Math.min(100, (100 * words) / goal)) : 0;
  const met = goal > 0 && words >= goal;
  return `<div class="goal-row ${met ? "met" : ""}">
    <div class="goal-label"><span>${label}</span>
      <span class="goal-num">${signedWords(words)} / ${goal.toLocaleString()} words${met ? ` <span class="goal-check" aria-label="goal met">✓</span>` : ""}</span></div>
    <div class="goal-bar" role="progressbar" aria-valuemin="0" aria-valuemax="${goal}" aria-valuenow="${Math.max(0, words)}"><span style="width:${pct}%"></span></div>
    ${extra || ""}
  </div>`;
}

function goalsPanelHtml(g) {
  const any = g.daily.goal || g.weekly.goal || g.projects.length;
  if (!any) {
    return `<section class="goals-strip" id="goals-panel">
      <span class="muted">Set a daily or weekly word goal to track it here. Today: ${signedWords(g.daily.words)} ${Math.abs(g.daily.words) === 1 ? "word" : "words"} added.</span>
      <button class="btn btn-ghost btn-small" data-goals-edit>Set goals</button>
      ${goalsFormHtml(g)}
    </section>`;
  }
  return `<section class="panel goals-panel" id="goals-panel">
    <div class="panel-head-row"><h3>Goals</h3><button class="btn btn-ghost btn-small" data-goals-edit>Edit goals</button></div>
    ${goalsFormHtml(g)}
    <div class="goal-grid">
      ${g.daily.goal ? goalBarHtml("Today", g.daily.words, g.daily.goal) : ""}
      ${g.weekly.goal ? goalBarHtml("This week", g.weekly.words, g.weekly.goal) : ""}
      ${g.projects.map((p) => goalBarHtml(`<a href="#" data-goal-project="${p.id}">${esc(p.name)}</a>`, p.words, p.target)).join("")}
    </div>
    <div class="hint">Words added are counted across your whole library, so cutting words counts too. Set a target length for a project on its page.</div>
  </section>`;
}

function goalsFormHtml(g) {
  return `<div class="goals-form hidden" id="goals-form">
    <label>Daily goal <input type="number" min="0" step="50" id="goal-daily" value="${g.daily.goal || ""}" placeholder="e.g. 500"> words</label>
    <label>Weekly goal <input type="number" min="0" step="100" id="goal-weekly" value="${g.weekly.goal || ""}" placeholder="e.g. 3000"> words</label>
    <button class="btn btn-small" id="goals-save">Save</button>
    <span class="hint">Leave empty for no goal.</span>
  </div>`;
}

function wireGoalsPanel(root, rerender) {
  const form = root.querySelector("#goals-form");
  if (!form) return;
  root.querySelectorAll("[data-goals-edit]").forEach((b) => b.addEventListener("click", () => {
    form.classList.toggle("hidden");
    if (!form.classList.contains("hidden")) form.querySelector("input").focus();
  }));
  const save = async () => {
    try {
      await jsonPost("/api/goals", {
        daily_words: document.getElementById("goal-daily").value,
        weekly_words: document.getElementById("goal-weekly").value,
      });
      toast("Goals saved.");
      rerender();
    } catch (e) { toast(e.message, true); }
  };
  document.getElementById("goals-save").addEventListener("click", save);
  form.querySelectorAll("input").forEach((i) => i.addEventListener("keydown", (ev) => { if (ev.key === "Enter") save(); }));
  root.querySelectorAll("[data-goal-project]").forEach((a) => a.addEventListener("click", (ev) => {
    ev.preventDefault();
    state.view = "projects";
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === "projects"));
    openProject(Number(a.dataset.goalProject));
  }));
}

function projectTargetHtml(p) {
  return `<div class="project-target">
    ${p.target_words ? goalBarHtml("Target length", p.word_count, p.target_words) : ""}
    <label class="target-edit">${p.target_words ? "Change target" : "Target length"} <input type="number" min="0" step="1000" id="proj-target" value="${p.target_words || ""}" placeholder="none"> words
      <button class="btn btn-ghost btn-small" id="proj-target-save">Set</button></label>
  </div>`;
}

function wireProjectTarget(after) {
  const input = document.getElementById("proj-target");
  const save = async () => {
    try {
      await projectPost("", { target_words: input.value });
      toast(input.value ? "Target saved." : "Target cleared.");
      after();
    } catch (e) { toast(e.message, true); }
  };
  document.getElementById("proj-target-save").addEventListener("click", save);
  input.addEventListener("keydown", (ev) => { if (ev.key === "Enter") save(); });
}
