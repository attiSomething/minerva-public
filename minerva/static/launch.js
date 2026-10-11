// Launch screen: what Minerva is doing while it opens the library and loads
// Home, with a percentage. Opening the library is 0-90% (reported by the
// server), loading Home the last 10%. If a step stalls, it says which one and
// offers Try again and the logs. Errors in the page go to Minerva's log.

const LAUNCH_SLOW_MS = 15000;
const launchState = { pct: 0, label: "", changed: Date.now(), waiting: null, warned: false };

function launchEl() { return document.getElementById("launch"); }

function launchShow(pct, label) {
  if (!document.getElementById("launch-fill")) return;
  pct = Math.max(launchState.pct, Math.min(100, Math.round(pct))); // never goes backwards
  if (pct !== launchState.pct || label !== launchState.label) {
    launchState.changed = Date.now();
    launchState.warned = false;
    if (!launchState.error) document.getElementById("launch-trouble").classList.add("hidden");
  }
  launchState.pct = pct;
  launchState.label = label;
  document.getElementById("launch-fill").style.width = `${pct}%`;
  document.getElementById("launch-pct").textContent = `${pct}%`;
  document.getElementById("launch-label").textContent = label;
}

function logToMinerva(level, message) {
  fetch("/api/log", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Minerva-Token": MINERVA_TOKEN },
    body: JSON.stringify({ level, message: String(message).slice(0, 4000) }),
  }).catch(() => { /* the server is gone; nothing to tell */ });
}

window.addEventListener("error", (ev) =>
  logToMinerva("error", `${ev.message} (${(ev.filename || "").split("/").pop()}:${ev.lineno})`));
window.addEventListener("unhandledrejection", (ev) => {
  const r = ev.reason;
  logToMinerva("error", `Unhandled: ${(r && (r.stack || r.message)) || r}`);
});

function logsButtonsHtml() {
  return `<button class="btn" data-launch-retry>Try again</button>
    <button class="btn btn-ghost" data-logs-save>Save logs</button>
    <button class="btn btn-ghost" data-logs-open>Open logs folder</button>`;
}

// Save logs / Open logs folder buttons, anywhere they're shown
document.addEventListener("click", async (ev) => {
  const save = ev.target.closest("[data-logs-save]");
  const open = ev.target.closest("[data-logs-open]");
  if (!save && !open) return;
  // the window saves and shows them itself when it can, so these work even
  // while the library process is busy
  const bridge = window.pywebview && window.pywebview.api;
  try {
    if (save) {
      const r = bridge && bridge.save_logs ? await bridge.save_logs() : await api("/api/logs/save", { method: "POST" });
      if (r && r.error) throw new Error(r.error);
      toast(`Saved the logs to ${r.path}`);
    } else if (bridge && bridge.open_logs) {
      await bridge.open_logs();
    } else {
      await api("/api/logs/reveal", { method: "POST" });
    }
  } catch (e) { toast(e.message, true); }
});

function launchTrouble(html, onRetry) {
  let box = document.getElementById("launch-trouble");
  if (!box) { // the launch screen is gone: put a plain one back
    appEl.innerHTML = `<div class="launch" id="launch"><img src="/static/owl.svg" alt="" class="launch-owl"><h1>Minerva</h1><div id="launch-trouble" class="launch-trouble"></div></div>`;
    box = document.getElementById("launch-trouble");
  }
  box.innerHTML = `${html}<div class="launch-actions">${logsButtonsHtml()}</div>`;
  box.classList.remove("hidden");
  box.querySelector("[data-launch-retry]").addEventListener("click", onRetry || (() => location.reload()));
}

// Something failed outright during start-up.
function launchFailed(message) {
  launchState.error = message;
  logToMinerva("error", `Start-up failed: ${message}`);
  launchTrouble(`<p><strong>Minerva couldn't finish starting.</strong> ${esc(message)}</p>`);
}

// A step that hasn't moved for a while says what it's waiting on.
setInterval(() => {
  if (!launchEl() || launchState.error || launchState.warned || Date.now() - launchState.changed < LAUNCH_SLOW_MS) return;
  launchState.warned = true;
  const waiting = launchState.waiting && launchState.waiting.size ? ` Still waiting for ${[...launchState.waiting].join(", ")}.` : "";
  launchTrouble(`<p>This is taking longer than usual. Minerva has been on <strong>${esc(launchState.label)}</strong> for over ${LAUNCH_SLOW_MS / 1000} seconds.${esc(waiting)}</p>
    <p class="muted">A large library, or one that's still syncing from OneDrive, can be slow. If it doesn't move, try again, and save the logs so the cause can be found.</p>`);
  logToMinerva("warning", `Launch screen stuck on "${launchState.label}" at ${launchState.pct}%.${waiting}`);
}, 1000);

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

// Wait for the server to finish opening the library.
async function waitForLaunch() {
  let failures = 0;
  for (;;) {
    let s;
    try {
      s = await api("/api/launch");
      failures = 0;
    } catch (e) {
      if (++failures === 10) launchFailed(`Minerva's server isn't answering (${e.message}).`);
      await sleep(500);
      continue;
    }
    if (s.error) {
      if (!launchState.error) {
        launchState.error = s.error;
        launchTrouble(`<p><strong>Minerva couldn't open your library.</strong> ${esc(s.error)}</p>`, async () => {
          launchState.error = null;
          document.getElementById("launch-trouble").classList.add("hidden");
          try { await api("/api/launch/retry", { method: "POST" }); } catch (e) { toast(e.message, true); }
        });
      }
      await sleep(1000);
      continue;
    }
    launchShow(s.percent * 0.9, s.label);
    if (s.done) return;
    await sleep(150);
  }
}

// Launch is over (Home or first-time setup is up): tell the server, once.
function launchReady() {
  if (launchReady.sent) return;
  launchReady.sent = true;
  fetch("/api/launch/ready", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Minerva-Token": MINERVA_TOKEN },
    body: JSON.stringify({ seconds: performance.now() / 1000 }),
  }).catch(() => {});
}

// Home's first load: each request moves the bar from 90% to 100%, and one
// that hangs is named. Returns the promises unchanged otherwise.
function launchTrack(named) {
  if (!launchEl()) return named.map(([, p]) => p);
  launchState.waiting = new Set(named.map(([name]) => name));
  let done = 0;
  launchShow(90, "Loading Home");
  const tracked = named.map(([name, p]) => p.finally(() => {
    done += 1;
    launchState.waiting.delete(name);
    launchShow(90 + (10 * done) / named.length, "Loading Home");
  }));
  Promise.allSettled(tracked).then(launchReady);
  return tracked;
}

// ---- Settings > Logs --------------------------------------------------------

function logsSectionHtml() {
  return `
    <section class="panel" id="logs-settings">
      <h2>Logs</h2>
      <p class="muted">Minerva keeps a log on this computer of how each launch went, anything slow or stuck, and any errors. It never holds your writing, though an error can name a file. Nothing is sent anywhere; Save logs makes a .zip in your Downloads folder that you can share when something goes wrong.</p>
      <div class="profile-row">
        <button class="btn" data-logs-save>Save logs</button>
        <button class="btn btn-ghost" data-logs-open>Open logs folder</button>
        <button class="btn btn-ghost" id="logs-show">Show recent log</button>
      </div>
      <pre id="logs-recent" class="logs-recent hidden"></pre>
    </section>`;
}

function wireLogsSection() {
  const btn = document.getElementById("logs-show");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    const pre = document.getElementById("logs-recent");
    if (!pre.classList.contains("hidden")) { pre.classList.add("hidden"); btn.textContent = "Show recent log"; return; }
    try {
      const r = await api("/api/logs");
      pre.textContent = r.recent || "The log is empty.";
      pre.classList.remove("hidden");
      pre.scrollTop = pre.scrollHeight;
      btn.textContent = "Hide recent log";
    } catch (e) { toast(e.message, true); }
  });
}
