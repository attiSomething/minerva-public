// "How this works" links: each screen points at the part of Help that
// explains it, a task how-to where there is one and otherwise the matching
// section of the reference guide. Used by most screens; the click handler
// below is shared.

const GUIDE = "2 - How Minerva Works.txt";
const BASICS = "1 - Getting Started.txt";
const HELP_TOPICS = {
  home: { kind: "doc", name: GUIDE, anchor: "Home" },
  entries: { kind: "doc", name: GUIDE, anchor: "Entries" },
  intake: { kind: "howto", name: "5 - Bringing In Old Drafts.html" },
  notesapps: { kind: "howto", name: "5 - Bringing In Old Drafts.html", anchor: "From notes apps" },
  edit: { kind: "howto", name: "3 - Managing Drafts.html" },
  people: { kind: "doc", name: GUIDE, anchor: "People (under Entries)" },
  images: { kind: "doc", name: GUIDE, anchor: "Images (under Entries)" },
  duplicates: { kind: "doc", name: GUIDE, anchor: "Duplicates (under Entries)" },
  projects: { kind: "howto", name: "6 - Putting a Chapbook Together.html" },
  submissions: { kind: "howto", name: "7 - Tracking Where a Poem Is Out.html" },
  venues: { kind: "howto", name: "7 - Tracking Where a Poem Is Out.html", anchor: "Keep notes on venues" },
  "sub-import": { kind: "howto", name: "7 - Tracking Where a Poem Is Out.html", anchor: "From Submittable or The Grinder" },
  views: { kind: "doc", name: GUIDE, anchor: "Views" },
  scans: { kind: "howto", name: "1 - Scanning and Sorting.html" },
  settings: { kind: "doc", name: GUIDE, anchor: "Settings" },
  backups: { kind: "doc", name: BASICS, anchor: "Backups" },
  checks: { kind: "doc", name: BASICS, anchor: "Library check" },
  share: { kind: "howto", name: "8 - Making a Standard Manuscript.html" },
  publish: { kind: "howto", name: "6 - Putting a Chapbook Together.html", anchor: "Print a proof" },
  sample: { kind: "doc", name: BASICS, anchor: "The sample library" },
  sync: { kind: "doc", name: BASICS, anchor: "Synced folders (Obsidian and other notes)" },
};

function helpLinkHtml(topic, label = "How this works") {
  if (!HELP_TOPICS[topic]) return "";
  return `<a href="#" class="help-link" data-help="${topic}"><span aria-hidden="true">?</span> ${esc(label)}</a>`;
}

function openHelp(topic) {
  const t = HELP_TOPICS[topic];
  if (!t) return;
  state.openDoc = { kind: t.kind, name: t.name, anchor: t.anchor || "" };
  setView("docs");
}

document.addEventListener("click", (ev) => {
  const a = ev.target.closest && ev.target.closest("[data-help]");
  if (!a) return;
  ev.preventDefault();
  // a link inside a dialog closes the dialog first
  // during first-run setup there's no Help tab yet, so read it in place
  if (document.querySelector(".wizard")) { openHelpModal(a.dataset.help); return; }
  const modal = a.closest(".modal-backdrop");
  if (modal) modal.remove();
  openHelp(a.dataset.help);
});

async function openHelpModal(topic) {
  const t = HELP_TOPICS[topic];
  if (!t) return;
  let body;
  try {
    body = t.kind === "howto"
      ? (await api(`/api/howtos/${encodeURIComponent(t.name)}`)).html
      : `<div class="docs-text">${esc((await api(`/api/docs/${encodeURIComponent(t.name)}`)).content)}</div>`;
  } catch (e) { toast(e.message, true); return; }
  const el = document.createElement("div");
  el.className = "modal-backdrop help-modal";
  el.innerHTML = `<div class="modal modal-wide" role="dialog" aria-modal="true" aria-label="Help">
    <div class="help-modal-body docs-content">${body}</div>
    <div class="modal-actions"><span style="flex:1"></span><button class="btn btn-gold" data-help-close>Back to setup</button></div>
  </div>`;
  document.body.appendChild(el);
  const close = () => { el.remove(); document.removeEventListener("keydown", keys); };
  const keys = (ev) => { if (ev.key === "Escape") close(); };
  document.addEventListener("keydown", keys);
  el.querySelector("[data-help-close]").addEventListener("click", close);
  scrollHelpTo(el.querySelector(".help-modal-body"), t.kind, t.anchor);
}

// Scroll the open help page to a heading: an <h2> in a how-to (ignoring its
// "3." number) or a heading line in a text guide.
function scrollHelpTo(el, kind, anchor) {
  if (!anchor) return;
  let target = null;
  if (kind === "howto") {
    target = [...el.querySelectorAll("h2")].find((h) => h.textContent.replace(/^\d+\.\s*/, "").trim() === anchor);
  } else {
    const text = el.textContent;
    const m = new RegExp(`(^|\\n)${anchor.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\n`).exec(text);
    if (m) {
      const at = m.index + m[1].length;
      el.innerHTML = `${esc(text.slice(0, at))}<span class="doc-anchor" id="doc-anchor">${esc(anchor)}</span>${esc(text.slice(at + anchor.length))}`;
      target = document.getElementById("doc-anchor");
    }
  }
  if (target) {
    target.classList.add("doc-anchor");
    target.scrollIntoView({ block: "start" });
  }
}

// ---- AI cost and privacy -------------------------------------------------------
// Every cost estimate carries these links, and using an AI feature while it's
// off opens a short panel explaining the two ways to turn it on.

HELP_TOPICS["ai-local"] = { kind: "howto", name: "9 - Running AI on Your Computer.html" };
HELP_TOPICS["ai-service"] = { kind: "howto", name: "10 - Using an AI Service.html" };

function aiCostLinksHtml() {
  return `<span class="ai-cost-links">What does this cost, and is it private?
    <a href="#" data-help="ai-service">Using an AI service</a> ·
    <a href="#" data-help="ai-local">Running AI on your computer</a></span>`;
}

// A confirm() that can carry the cost-and-privacy links. Resolves true or false.
function aiConfirm(message, okLabel = "Go ahead") {
  return new Promise((resolve) => {
    const old = document.getElementById("ai-confirm");
    if (old) old.remove();
    const el = document.createElement("div");
    el.id = "ai-confirm";
    el.className = "modal-backdrop";
    el.innerHTML = `
      <div class="modal" role="alertdialog" aria-modal="true" aria-labelledby="aic-msg">
        <p id="aic-msg" class="aic-msg">${esc(message)}</p>
        <p class="hint">${aiCostLinksHtml()}</p>
        <div class="modal-actions">
          <span style="flex:1"></span>
          <button class="btn btn-ghost" id="aic-no">Cancel</button>
          <button class="btn btn-gold" id="aic-yes">${esc(okLabel)}</button>
        </div>
      </div>`;
    document.body.appendChild(el);
    const done = (v) => { el.remove(); document.removeEventListener("keydown", keys); resolve(v); };
    const keys = (ev) => { if (ev.key === "Escape") done(false); };
    document.addEventListener("keydown", keys);
    el.querySelector("#aic-no").addEventListener("click", () => done(false));
    el.querySelector("#aic-yes").addEventListener("click", () => done(true));
    // following a help link counts as not now
    el.querySelectorAll("[data-help]").forEach((a) => a.addEventListener("click", () => resolve(false)));
    el.querySelector("#aic-yes").focus();
  });
}

const AI_FEATURE_NAMES = { scanning: "AI-assisted scanning", organizing: "AI-assisted organizing and editing" };

function aiOffPanelOpen() {
  return !!document.getElementById("ai-off");
}

function showAiOffPanel(feature, reason) {
  if (aiOffPanelOpen()) return;
  const el = document.createElement("div");
  el.id = "ai-off";
  el.className = "modal-backdrop";
  const name = AI_FEATURE_NAMES[feature] || "This AI feature";
  el.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="ai-off-h">
      <h2 id="ai-off-h">${esc(name)} isn't set up</h2>
      <p>${esc(reason || "")} It needs an AI model, and there are two ways to get one:</p>
      <div class="ai-off-choices">
        <a href="#" class="ai-off-choice" data-help="ai-local">
          <strong>Run one on your computer</strong>
          <span>Free and private: nothing leaves this computer. Needs a free program and a few GB of disk; slower, and weaker on handwriting.</span>
        </a>
        <a href="#" class="ai-off-choice" data-help="ai-service">
          <strong>Use an AI service</strong>
          <span>Anthropic, OpenAI or Google, with your own key. Usually pennies per use; the best at handwriting. Paid use isn't used for training.</span>
        </a>
      </div>
      <div class="modal-actions">
        <span style="flex:1"></span>
        <button class="btn btn-ghost" id="ai-off-close">Not now</button>
        <button class="btn btn-ghost" data-localai>Set up free local AI</button>
        <button class="btn btn-gold" id="ai-off-settings">Open Settings</button>
      </div>
    </div>`;
  document.body.appendChild(el);
  const close = () => { el.remove(); document.removeEventListener("keydown", keys); };
  const keys = (ev) => { if (ev.key === "Escape") close(); };
  document.addEventListener("keydown", keys);
  el.querySelector("#ai-off-close").addEventListener("click", close);
  el.querySelector("#ai-off-settings").addEventListener("click", () => { close(); setView("settings"); });
  el.querySelector("#ai-off-settings").focus();
}
