// Minerva first-run setup and the Settings tab.
// Depends on helpers from app.js: api, esc, toast, startMinerva, setView.

const FEATURE_COPY = {
  scanning: {
    title: "AI-assisted scanning",
    lead: "Let an AI model read photos and scans of handwritten pages and turn them into text you can proofread.",
    toggle: "Turn on AI-assisted scanning",
  },
  organizing: {
    title: "AI-assisted organizing and editing",
    lead: "Let an AI model suggest categories, projects and titles, spot duplicates, and help with edits. You confirm every change.",
    toggle: "Turn on AI-assisted organizing and editing",
  },
};

const onboarding = { step: 0, library: null, ai: null };

function jsonPost(path, body, method) {
  return api(path, {
    method: method || "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
}

function hasNativeBridge() {
  return !!(window.pywebview && window.pywebview.api && window.pywebview.api.pick_folder);
}

async function pickFolder(inputEl) {
  if (hasNativeBridge()) {
    const path = await window.pywebview.api.pick_folder();
    if (path) inputEl.value = path;
    inputEl.dispatchEvent(new Event("change"));
  } else {
    inputEl.focus();
    toast("Paste the folder's full path into the box.");
  }
}

// -------------------------------------------------------------------------
// AI settings form (shared by onboarding and Settings)
// -------------------------------------------------------------------------

function aiFormHtml(feature, settings, providers) {
  const copy = FEATURE_COPY[feature];
  const prov = providers.find((p) => p.id === settings.provider) || providers[0];
  const options = providers
    .map((p) => `<option value="${p.id}" ${p.id === prov.id ? "selected" : ""}>${esc(p.label)}</option>`)
    .join("");
  return `
    <div class="ai-form" data-feature="${feature}">
      <label class="switch-row">
        <input type="checkbox" class="ai-enabled" ${settings.enabled ? "checked" : ""}>
        <span>${esc(copy.toggle)}</span>
      </label>
      <div class="ai-fields ${settings.enabled ? "" : "hidden"}">
        <div class="field">
          <label>Provider</label>
          <select class="ai-provider">${options}</select>
        </div>
        <div class="field ai-key-field ${prov.needs_key ? "" : "hidden"}">
          <label>API key <span class="ai-key-status muted">${settings.has_key ? "· a key is saved" : ""}</span></label>
          <input type="password" class="ai-key" placeholder="${settings.has_key ? "Leave blank to keep the saved key" : "Paste your key"}" autocomplete="off">
          <div class="hint ai-key-hint">${esc(prov.key_hint)}</div>
        </div>
        <div class="field">
          <label>Model</label>
          <input type="text" class="ai-model" list="models-${feature}" value="${esc(settings.model || prov.default_model)}" placeholder="Test the connection to see your models">
          <datalist id="models-${feature}">${prov.models.map((m) => `<option value="${esc(m)}">`).join("")}</datalist>
        </div>
        <div class="ai-actions">
          <button class="btn btn-ghost ai-test" type="button">Test connection</button>
          <span class="ai-test-result muted"></span>
        </div>
        <p class="hint">Your key is stored in Windows Credential Manager on this computer. It never goes into your library or anywhere else.</p>
      </div>
    </div>`;
}

function wireAiForm(root, providers) {
  const enabled = root.querySelector(".ai-enabled");
  const fields = root.querySelector(".ai-fields");
  const providerSel = root.querySelector(".ai-provider");
  const keyField = root.querySelector(".ai-key-field");
  const keyHint = root.querySelector(".ai-key-hint");
  const model = root.querySelector(".ai-model");
  const datalist = root.querySelector("datalist");
  const result = root.querySelector(".ai-test-result");

  enabled.addEventListener("change", () => fields.classList.toggle("hidden", !enabled.checked));
  providerSel.addEventListener("change", () => {
    const p = providers.find((x) => x.id === providerSel.value);
    keyField.classList.toggle("hidden", !p.needs_key);
    keyHint.textContent = p.key_hint;
    model.value = p.default_model;
    datalist.innerHTML = p.models.map((m) => `<option value="${esc(m)}">`).join("");
    result.textContent = "";
  });
  root.querySelector(".ai-test").addEventListener("click", async () => {
    result.className = "ai-test-result muted";
    result.textContent = "Checking...";
    try {
      const r = await jsonPost("/api/settings/ai/test", {
        provider: providerSel.value,
        api_key: root.querySelector(".ai-key").value,
      });
      if (r.ok) {
        result.className = "ai-test-result ok";
        result.textContent = `Connected. ${r.models.length} model${r.models.length === 1 ? "" : "s"} available.`;
        datalist.innerHTML = r.models.map((m) => `<option value="${esc(m)}">`).join("");
        if (!model.value && r.models.length) model.value = r.models[0];
      } else {
        result.className = "ai-test-result err";
        result.textContent = r.error;
      }
    } catch (e) {
      result.className = "ai-test-result err";
      result.textContent = e.message;
    }
  });
}

function readAiForm(root) {
  return {
    feature: root.dataset.feature,
    enabled: root.querySelector(".ai-enabled").checked,
    provider: root.querySelector(".ai-provider").value,
    model: root.querySelector(".ai-model").value,
    api_key: root.querySelector(".ai-key").value,
  };
}

async function saveAiForm(root) {
  const body = readAiForm(root);
  const p = onboarding.ai.providers.find((x) => x.id === body.provider);
  if (body.enabled && p.needs_key && !body.api_key && !onboarding.ai.features[body.feature].has_key
      && !(await providerHasKey(body.provider))) {
    throw new Error("Paste an API key, or turn this off for now.");
  }
  onboarding.ai = await jsonPost("/api/settings/ai", body);
  return onboarding.ai;
}

async function providerHasKey(provider) {
  const s = await api("/api/settings/ai");
  return Object.values(s.features).some((f) => f.provider === provider && f.has_key);
}

// -------------------------------------------------------------------------
// Library chooser (shared by onboarding and Settings)
// -------------------------------------------------------------------------

function libraryChooserHtml() {
  return `
    <div class="choice-grid">
      <div class="choice-card" data-mode="open">
        <h3>Open a folder I already have</h3>
        <p>Point Minerva at the folder that holds your writing. Nothing in it is moved or deleted.</p>
        <div class="path-row">
          <input type="text" id="lib-open-path" placeholder="C:\\Users\\you\\Documents\\My Writing">
          <button class="btn btn-ghost" type="button" id="lib-open-pick">Choose folder…</button>
        </div>
        <div id="lib-open-info" class="hint"></div>
      </div>
      <div class="choice-card" data-mode="create">
        <h3>Start a new library</h3>
        <p>Minerva makes a folder with Fiction, Nonfiction, Poetry and Misc, plus Sources for scans, images and documents you want to work from.</p>
        <div class="path-row">
          <input type="text" id="lib-create-parent" placeholder="Where to put it">
          <button class="btn btn-ghost" type="button" id="lib-create-pick">Choose folder…</button>
        </div>
        <div class="path-row"><input type="text" id="lib-create-name" value="My Writing" placeholder="Library name"></div>
      </div>
    </div>`;
}

function wireLibraryChooser(root, onSelect) {
  const openPath = root.querySelector("#lib-open-path");
  const info = root.querySelector("#lib-open-info");
  const cards = root.querySelectorAll(".choice-card");
  let mode = null;
  const select = (m) => {
    mode = m;
    cards.forEach((c) => c.classList.toggle("selected", c.dataset.mode === m));
    onSelect(m);
  };
  cards.forEach((c) => {
    c.addEventListener("click", () => select(c.dataset.mode));
    // typing or tabbing into a card's box chooses that card too
    c.querySelectorAll("input").forEach((i) => i.addEventListener("focus", () => { if (mode !== c.dataset.mode) select(c.dataset.mode); }));
  });
  root.querySelector("#lib-open-pick").addEventListener("click", (e) => { e.stopPropagation(); select("open"); pickFolder(openPath); });
  root.querySelector("#lib-create-pick").addEventListener("click", (e) => { e.stopPropagation(); select("create"); pickFolder(root.querySelector("#lib-create-parent")); });
  openPath.addEventListener("change", async () => {
    info.textContent = "";
    if (!openPath.value.trim()) return;
    try {
      const r = await jsonPost("/api/setup/inspect", { path: openPath.value.trim() });
      const bits = [];
      bits.push(r.categories_present.length
        ? `Found ${r.categories_present.join(", ")}.`
        : "No Fiction, Nonfiction, Poetry or Misc folders yet; Minerva will add them.");
      if (r.earlier_minerva_found && !r.has_minerva_data) bits.push("An earlier Minerva setup was found here, so your flags, projects and duplicate reviews will come along.");
      if (r.has_minerva_data) bits.push("This folder has been opened in Minerva before.");
      info.textContent = bits.join(" ");
    } catch (e) {
      info.textContent = e.message;
    }
  });
  return {
    mode: () => mode,
    submit: async () => {
      if (mode === "open") {
        return jsonPost("/api/setup/library", { mode: "open", path: openPath.value.trim() });
      }
      if (mode === "create") {
        return jsonPost("/api/setup/library", {
          mode: "create",
          parent: root.querySelector("#lib-create-parent").value.trim(),
          name: root.querySelector("#lib-create-name").value.trim(),
        });
      }
      throw new Error("Choose one of the two options first.");
    },
  };
}

// -------------------------------------------------------------------------
// Onboarding wizard
// -------------------------------------------------------------------------

const STEPS = ["welcome", "library", "scanning", "organizing", "done"];

function stepDots() {
  return `<div class="step-dots">${STEPS.map((s, i) =>
    `<span class="dot ${i === onboarding.step ? "active" : ""} ${i < onboarding.step ? "done" : ""}"></span>`).join("")}</div>`;
}

function renderOnboarding() {
  const step = STEPS[onboarding.step];
  let body = "";
  if (step === "welcome") {
    body = `
      <img src="/static/owl.svg" alt="" class="hero-owl">
      <h1>Minerva</h1>
      <p class="tagline">A writer's best friend.</p>
      <p class="lead">Review, categorize and manage your writing, keep every draft, organize it into projects, and keep the original scans one click away.</p>
      <div class="wizard-actions"><button class="btn btn-gold" id="ob-next">Get started</button></div>`;
  } else if (step === "library") {
    body = `
      <h2>Where does your writing live?</h2>
      <p class="lead">Minerva works directly with the files in one folder, your library. It reads them, saves your edits back to them, and keeps older drafts in each entry's Archive folder.</p>
      ${libraryChooserHtml()}
      <p class="hint ob-sample">Not ready to point Minerva at your own writing? <a href="#" id="ob-sample">Explore a sample library first</a>. It's made-up writing in a folder of its own, and you can open your library from Settings whenever you like.</p>
      <div class="wizard-actions">
        <button class="btn btn-ghost" id="ob-back">Back</button>
        <button class="btn btn-gold" id="ob-next" disabled>Continue</button>
      </div>`;
  } else if (step === "scanning" || step === "organizing") {
    body = `
      <h2>${esc(FEATURE_COPY[step].title)} <span class="optional">optional</span></h2>
      <p class="lead">${esc(FEATURE_COPY[step].lead)} You bring your own model, and you can change this later in Settings.</p>
      <p class="hint">Two ways to do it: <a href="#" data-help="ai-local">run a model on your computer</a>, free and private, or <a href="#" data-help="ai-service">use an AI service</a>, usually pennies per use. Each guide covers cost and privacy.</p>
      ${onboarding.ai.features[step].enabled && onboarding.ai.features[step].provider === "ollama" ? "" : localAiCardHtml()}
      ${aiFormHtml(step, onboarding.ai.features[step], onboarding.ai.providers)}
      <div class="wizard-actions">
        <button class="btn btn-ghost" id="ob-back">Back</button>
        <button class="btn btn-ghost" id="ob-skip">Skip for now</button>
        <button class="btn btn-gold" id="ob-next">Continue</button>
      </div>`;
  } else {
    const lib = onboarding.library;
    body = `
      <img src="/static/owl.svg" alt="" class="hero-owl small">
      <h2>You're all set</h2>
      <p class="lead">${lib && lib.is_sample ? `The sample library is open, with <strong>${lib.total_entries}</strong> made-up entries to try things on. When you're ready, Home has a button to open your own.` : lib && lib.total_entries == null ? `Your library is open at <code>${esc(lib.library_root)}</code>.` : lib ? `Minerva found <strong>${lib.total_entries}</strong> entr${lib.total_entries === 1 ? "y" : "ies"} in <code>${esc(lib.library_root)}</code>.` : ""}
      ${lib && lib.imported_from ? " Your earlier flags, projects and duplicate reviews came along." : ""}</p>
      <div class="wizard-actions">
        <button class="btn btn-ghost" id="ob-back">Back</button>
        <button class="btn btn-gold" id="ob-next">${lib && lib.is_sample ? "Open the sample" : "Open my library"}</button>
      </div>`;
  }

  appEl.innerHTML = `<div class="wizard"><div class="wizard-card">${stepDots()}${body}</div></div>`;

  const next = document.getElementById("ob-next");
  const back = document.getElementById("ob-back");
  if (back) back.addEventListener("click", () => { onboarding.step -= 1; renderOnboarding(); });

  if (step === "library") {
    const chooser = wireLibraryChooser(appEl, () => { next.disabled = false; });
    document.getElementById("ob-sample").addEventListener("click", async (ev) => {
      ev.preventDefault();
      try {
        onboarding.library = await jsonPost("/api/setup/sample", {});
        onboarding.step += 1;
        renderOnboarding();
      } catch (e) {
        toast(e.message, true);
      }
    });
    next.addEventListener("click", async () => {
      next.disabled = true;
      next.textContent = "Opening your library...";
      try {
        onboarding.library = await chooser.submit();
        onboarding.step += 1;
        renderOnboarding();
      } catch (e) {
        toast(e.message, true);
        next.disabled = false;
        next.textContent = "Continue";
      }
    });
    return;
  }

  if (step === "scanning" || step === "organizing") {
    const form = appEl.querySelector(".ai-form");
    wireAiForm(form, onboarding.ai.providers);
    document.getElementById("ob-skip").addEventListener("click", async () => {
      const body = readAiForm(form);
      try {
        onboarding.ai = await jsonPost("/api/settings/ai", { ...body, enabled: false, api_key: "" });
      } catch (e) {
        toast(e.message, true);
        return;
      }
      onboarding.step += 1;
      renderOnboarding();
    });
    next.addEventListener("click", async () => {
      try {
        await saveAiForm(form);
        onboarding.step += 1;
        renderOnboarding();
      } catch (e) {
        toast(e.message, true);
      }
    });
    return;
  }

  if (step === "done") {
    next.addEventListener("click", async () => {
      await jsonPost("/api/setup/complete");
      await startMinerva();
    });
    return;
  }

  next.addEventListener("click", () => { onboarding.step += 1; renderOnboarding(); });
}

// -------------------------------------------------------------------------
// Settings tab
// -------------------------------------------------------------------------

const THEMES = {
  "athena": { name: "Athena", desc: "Regal blues and gold. The original.", sw: ["#f3f5fa", "#2f5bb7", "#c99a1e", "#ffffff", "#1f3f88"] },
  "dark-athena": { name: "Dark Athena", desc: "Athena by lamplight.", sw: ["#0d1322", "#4a78d6", "#efc65a", "#1a2540", "#bcd0f7"] },
  "tarofied": { name: "Tarofied", desc: "Android-UI greys, square and spare.", sw: ["#cbc6ae", "#57544a", "#8c3f2b", "#dad4bc", "#3a3831"] },
  "fifth-impact": { name: "Fifth Impact", desc: "Command-centre reds and orange.", sw: ["#090605", "#d8321a", "#ff8b2b", "#1b0f0b", "#ffb877"] },
  "liched-up": { name: "Liched Up", desc: "Purple, black and glowing circuits.", sw: ["#0c0813", "#8a5cf0", "#4fe3a8", "#1d142e", "#c9adff"] },
};

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
}

function currentUsername() {
  return document.querySelector('meta[name="minerva-username"]').content;
}

function customizationHtml(profile) {
  return `
    <section class="panel" id="customization">
      <h2>Customization</h2>
      <label for="username-input">Your name</label>
      <div class="profile-row">
        <input type="text" id="username-input" maxlength="40" placeholder="What should Minerva call you?" value="${esc(profile.username)}">
        <button class="btn" id="username-save">Save</button>
      </div>
      <div class="hint">Only used to greet you. Minerva has no accounts; this stays on this computer.</div>
      <label style="margin-top:14px;display:block">Style</label>
      <div class="theme-grid" role="radiogroup" aria-label="Style">
        ${profile.themes.map((t) => {
          const th = THEMES[t] || { name: t, desc: "", sw: [] };
          return `<button class="theme-card ${t === profile.theme ? "selected" : ""}" role="radio" aria-checked="${t === profile.theme}" data-theme-pick="${t}">
            <div class="theme-swatch">${th.sw.map((c) => `<span style="background:${c}"></span>`).join("")}</div>
            <div class="theme-name">${esc(th.name)}</div>
            <div class="theme-desc">${esc(th.desc)}</div>
          </button>`;
        }).join("")}
      </div>
    </section>`;
}

function wireCustomization() {
  const save = async (body) => api("/api/settings/profile", { method: "POST", body: JSON.stringify(body) });
  document.getElementById("username-save").addEventListener("click", async () => {
    try {
      const r = await save({ username: document.getElementById("username-input").value });
      document.querySelector('meta[name="minerva-username"]').content = r.username;
      document.getElementById("username-input").value = r.username;
      toast(r.username ? `Saved. Hello, ${r.username}.` : "Saved.");
    } catch (e) { toast(e.message, true); }
  });
  document.getElementById("username-input").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") document.getElementById("username-save").click();
  });
  appEl.querySelectorAll("[data-theme-pick]").forEach((b) => b.addEventListener("click", async () => {
    const before = document.documentElement.dataset.theme;
    applyTheme(b.dataset.themePick);
    appEl.querySelectorAll("[data-theme-pick]").forEach((x) => {
      x.classList.toggle("selected", x === b);
      x.setAttribute("aria-checked", x === b);
    });
    try {
      await save({ theme: b.dataset.themePick });
    } catch (e) {
      applyTheme(before);
      toast(e.message, true);
    }
  }));
}

async function renderSettings() {
  const status = await api("/api/setup/status");
  const profile = await api("/api/settings/profile");
  onboarding.ai = await api("/api/settings/ai");
  const share = await shareOptions(true).catch(() => null);
  const bk = await api("/api/backup").catch(() => null);
  const cats = await api("/api/categories/details").catch(() => null);
  const tagList = await loadTags();
  const contact = await api("/api/settings/contact").catch(() => null);
  const syncSources = await api("/api/sync/sources").catch(() => null);
  const ocr = await api("/api/settings/ocr").catch(() => null);
  await loadCategories().catch(() => null);
  const version = document.querySelector('meta[name="minerva-version"]').content;
  appEl.innerHTML = `
    <div class="settings">
      ${customizationHtml(profile)}
      <section class="panel">
        <h2>Library ${helpLinkHtml("settings", "How Settings work")}</h2>
        <p>Minerva is working with <code>${esc(status.library_root)}</code>${status.is_sample ? ", the sample library (made-up writing in its own folder)" : ""}.</p>
        <button class="btn btn-ghost" id="switch-lib">Open a different library…</button>
        <button class="btn btn-ghost" id="check-lib">Check library</button>
        ${status.is_sample
          ? (status.library_before_sample ? `<button class="btn btn-ghost" id="sample-leave">Back to my library</button>` : "")
            + `<button class="btn btn-ghost" id="sample-reset">Start the sample over</button>`
          : `<button class="btn btn-ghost" id="sample-try" title="Made-up writing in a separate folder; your library isn't touched">Explore the sample library</button>`}
        <div id="switch-lib-area" class="hidden"></div>
      </section>
      ${syncSources ? syncSectionHtml(syncSources) : ""}
      ${cats ? categoriesSectionHtml(cats) : ""}
      ${tagsSectionHtml(tagList)}
      ${bk ? backupSectionHtml(bk) : ""}
      <section class="panel" id="export-all-settings"></section>
      <section class="panel" id="local-ai">
        <h2>Free and private AI ${helpLinkHtml("ai-local", "Running AI on your computer")}</h2>
        <p class="muted">A model that runs on this computer, through the free Ollama program. Nothing you write leaves the computer; it's slower than an AI service and weaker on handwriting.</p>
        ${localAiCardHtml()}
      </section>
      <section class="panel" id="grammar-settings"></section>
      ${["scanning", "organizing"].map((f) => `
        <section class="panel">
          <h2>${esc(FEATURE_COPY[f].title)}</h2>
          <p class="muted">${esc(FEATURE_COPY[f].lead)}</p>
          <p class="hint">${aiCostLinksHtml()}</p>
          ${f === "scanning" && ocr && ocr.available ? `
          <label class="switch-row">
            <input type="checkbox" id="builtin-ocr" ${ocr.enabled ? "checked" : ""}>
            <span>Read typed pages free with Windows' built-in text recognition first <span class="muted">(offline; works even with AI off)</span></span>
          </label>` : ""}
          ${aiFormHtml(f, onboarding.ai.features[f], onboarding.ai.providers)}
          <button class="btn save-ai" data-feature="${f}">Save</button>
        </section>`).join("")}
      ${contact ? manuscriptSectionHtml(contact) : ""}
      ${share ? templatesSectionHtml(share.templates) : ""}
      <section class="panel" id="update-settings"></section>
      ${logsSectionHtml()}
      <p class="muted">Minerva ${esc(version)}. Your writing stays on this computer.</p>
    </div>`;

  wireCustomization();
  renderGrammarSettings();
  renderUpdateSettings();
  renderExportAllSettings();
  wireLogsSection();
  wireCategoriesSection(() => { if (state.view === "settings") renderSettings(); });
  wireTagsSection(() => { if (state.view === "settings") renderSettings(); });
  wireManuscriptSection();
  wireSyncSection(async () => { if (state.view === "settings") { state.scrollTo = "synced-folders"; await renderSettings(); } });
  if (bk) {
    const refresh = () => { if (state.view === "settings") renderSettings(); };
    wireBackupSection(refresh);
    resumeBackupPolling(bk, refresh);
  }
  if (state.scrollTo) {
    const target = document.getElementById(state.scrollTo);
    state.scrollTo = null;
    if (target) target.scrollIntoView({ block: "start" });
  }
  appEl.querySelectorAll(".ai-form").forEach((form) => wireAiForm(form, onboarding.ai.providers));
  const ocrBox = document.getElementById("builtin-ocr");
  if (ocrBox) ocrBox.addEventListener("change", async () => {
    try {
      await jsonPost("/api/settings/ocr", { enabled: ocrBox.checked });
      toast(ocrBox.checked ? "Typed pages will be read free first." : "Every page goes to your AI model.");
    } catch (e) { toast(e.message, true); }
  });
  if (share) wireTemplates(renderSettings);
  appEl.querySelectorAll(".save-ai").forEach((btn) => btn.addEventListener("click", async () => {
    try {
      await saveAiForm(appEl.querySelector(`.ai-form[data-feature="${btn.dataset.feature}"]`));
      toast("Saved.");
      renderSettings();
    } catch (e) {
      toast(e.message, true);
    }
  }));

  document.getElementById("check-lib").addEventListener("click", () => setView("checks"));
  wireSampleBanner(appEl);
  const tryIt = document.getElementById("sample-try");
  if (tryIt) tryIt.addEventListener("click", () => openSampleLibrary(false));
  document.getElementById("switch-lib").addEventListener("click", () => {
    const area = document.getElementById("switch-lib-area");
    area.classList.remove("hidden");
    area.innerHTML = `${libraryChooserHtml()}<button class="btn btn-gold" id="switch-go" disabled>Open this library</button>`;
    const go = document.getElementById("switch-go");
    const chooser = wireLibraryChooser(area, () => { go.disabled = false; });
    go.addEventListener("click", async () => {
      try {
        const r = await chooser.submit();
        toast(`Opened ${r.library_root} (${r.total_entries} entries).`);
        await setView("home");
        refreshAlertsBadge();
      } catch (e) {
        toast(e.message, true);
      }
    });
  });
}

// -------------------------------------------------------------------------
// boot
// -------------------------------------------------------------------------

(async function boot() {
  let status;
  try {
    await waitForLaunch();
    status = await api("/api/setup/status");
    if (status.onboarded) {
      await startMinerva();
      return;
    }
    onboarding.ai = await api("/api/settings/ai");
  } catch (e) {
    launchFailed(e.message);
    return;
  }
  // closed partway through: the library is already open, so carry on
  // from the AI steps instead of asking for it again
  if (status.library_root) {
    onboarding.library = { library_root: status.library_root, is_sample: status.is_sample, total_entries: null };
    onboarding.step = STEPS.indexOf("scanning");
  }
  renderOnboarding();
  launchReady();
})();
