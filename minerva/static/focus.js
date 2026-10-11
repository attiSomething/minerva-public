// Focus mode: a full-screen, distraction-free editor for the open entry.
// Depends on helpers from app.js (api, esc, toast, plural, state, renderEdit).

const focusState = { open: false };

function countWords(text) {
  const t = text.trim();
  return t ? t.split(/\s+/).length : 0;
}

async function openFocus() {
  if (focusState.open) return;
  const editor = document.getElementById("editor");
  const e = state.currentEntry;
  if (!editor || !e) return;
  focusState.open = true;
  focusState.startWords = countWords(editor.value);
  focusState.savedWords = e.word_count || 0;
  focusState.savedDuringFocus = false;
  focusState.goals = await api("/api/goals").catch(() => null);

  const el = document.createElement("div");
  el.className = "focus-overlay";
  el.id = "focus-overlay";
  el.setAttribute("role", "dialog");
  el.setAttribute("aria-label", `Focus mode: ${e.title}`);
  el.innerHTML = `
    <div class="focus-top">
      <span class="focus-title">${esc(e.title)}</span>
      <span class="focus-hint">Esc to leave · Ctrl+S to save</span>
    </div>
    <textarea id="focus-editor" spellcheck="true" aria-label="Draft"></textarea>
    <div class="focus-bar">
      <span id="focus-words"></span>
      <span id="focus-session"></span>
      <span id="focus-goal"></span>
      <span class="focus-actions">
        ${readAloudAvailable() ? `<button class="btn btn-ghost btn-small" id="focus-read">Read aloud</button>` : ""}
        <button class="btn btn-ghost btn-small" id="focus-save">Save</button>
        <button class="btn btn-ghost btn-small" id="focus-leave">Leave focus</button>
      </span>
    </div>`;
  document.body.appendChild(el);
  document.body.classList.add("focus-on");
  const fe = document.getElementById("focus-editor");
  fe.value = editor.value;
  fe.selectionStart = fe.selectionEnd = Math.min(editor.selectionStart || fe.value.length, fe.value.length);
  fe.focus();
  fe.addEventListener("input", () => {
    editor.value = fe.value;  // keep the page's editor in step, so leaving keeps every change
    updateFocusCounts();
    // fade the bars while typing; they come back when the pointer moves
    el.classList.add("typing");
  });
  el.addEventListener("mousemove", () => el.classList.remove("typing"));
  document.getElementById("focus-save").addEventListener("click", saveFromFocus);
  const read = document.getElementById("focus-read");
  if (read) read.addEventListener("click", () => {
    if (readState.bar) { stopReading(); return; }
    startReading(fe, el.querySelector(".focus-top"), "focus-read-bar");
  });
  document.getElementById("focus-leave").addEventListener("click", closeFocus);
  document.addEventListener("keydown", focusKeys, true);
  if (document.documentElement.requestFullscreen) {
    document.documentElement.requestFullscreen().catch(() => { /* a window that can't go full screen still works */ });
  }
  updateFocusCounts();
}

function updateFocusCounts() {
  const words = countWords(document.getElementById("focus-editor").value);
  const session = words - focusState.startWords;
  document.getElementById("focus-words").textContent = plural(words, "word", "words");
  document.getElementById("focus-session").textContent =
    `This session: ${session < 0 ? "−" : "+"}${Math.abs(session).toLocaleString()}`;
  const g = focusState.goals;
  const goalEl = document.getElementById("focus-goal");
  if (g && g.daily.goal) {
    // saved words already count toward today; add what's typed but not saved yet
    const today = g.daily.words + (words - focusState.savedWords);
    const met = today >= g.daily.goal;
    goalEl.innerHTML = `Today ${Math.max(0, today).toLocaleString()} / ${g.daily.goal.toLocaleString()}
      <span class="focus-goal-bar ${met ? "met" : ""}"><span style="width:${Math.max(0, Math.min(100, (100 * today) / g.daily.goal))}%"></span></span>`;
  } else {
    goalEl.textContent = "";
  }
}

async function saveFromFocus() {
  const text = document.getElementById("focus-editor").value;
  try {
    await api(`/api/entries/${state.currentEntryId}/save`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: text, mode: "overwrite" }),
    });
    focusState.savedDuringFocus = true;
    focusState.goals = await api("/api/goals").catch(() => focusState.goals);
    focusState.savedWords = countWords(text);
    updateFocusCounts();
    toast("Saved.");
  } catch (err) {
    toast(err.message, true);
  }
}

function focusKeys(ev) {
  if (!focusState.open) return;
  if (ev.key === "Escape") {
    ev.preventDefault();
    closeFocus();
  } else if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "s") {
    ev.preventDefault();
    saveFromFocus();
  }
}

async function closeFocus() {
  if (!focusState.open) return;
  const text = document.getElementById("focus-editor").value;
  focusState.open = false;
  stopReading();
  document.removeEventListener("keydown", focusKeys, true);
  document.getElementById("focus-overlay").remove();
  document.body.classList.remove("focus-on");
  if (document.fullscreenElement && document.exitFullscreen) document.exitFullscreen().catch(() => {});
  if (focusState.savedDuringFocus) {
    // refresh word counts and archive details, then put back anything typed after the last save
    await renderEdit();
    const editor = document.getElementById("editor");
    if (editor) editor.value = text;
  }
  const editor = document.getElementById("editor");
  if (editor) editor.focus();
}
