// Video: a narration made into an MP4, its words shown a stanza at a time
// over the project cover, a picture or plain navy. Opened from the entry
// Share panel, the project Publish panel and a finished narration.

const vid = { target: null, opts: null, picture: null, previewUrl: null, jobId: null, timer: null, previewTimer: null };

HELP_TOPICS.video = { kind: "howto", name: "11 - Narration and Video.html", anchor: "Make a video" };

function closeVideo() {
  clearTimeout(vid.timer);
  clearTimeout(vid.previewTimer);
  if (vid.previewUrl) URL.revokeObjectURL(vid.previewUrl);
  vid.previewUrl = null;
  const el = document.getElementById("video-dialog");
  if (el) el.remove();
  document.removeEventListener("keydown", videoKeys);
}

function videoKeys(ev) {
  if (ev.key === "Escape") closeVideo();
}

// target: { kind, id, title, narration? }
async function openVideo(target) {
  closeVideo();
  vid.target = target;
  vid.picture = null;
  const el = document.createElement("div");
  el.id = "video-dialog";
  el.className = "modal-backdrop";
  el.innerHTML = `
    <div class="modal modal-wide" role="dialog" aria-modal="true" aria-labelledby="vid-h">
      <h2 id="vid-h">Make a video of ${esc(target.title)}</h2>
      <div id="vid-body"><p class="muted">Loading...</p></div>
    </div>`;
  document.body.appendChild(el);
  document.addEventListener("keydown", videoKeys);
  try { vid.opts = await api(`/api/video/options?kind=${encodeURIComponent(target.kind)}&id=${target.id}`); }
  catch (e) { toast(e.message, true); closeVideo(); return; }
  const running = vid.opts.jobs.find((j) => j.kind === "video");
  if (running) { vid.jobId = running.id; pollVideo(); return; }
  renderVideo();
}

function videoChoice(name, fallback) {
  const el = document.querySelector(`#vid-form [name=${name}]:checked`) || document.getElementById(`vid-${name}`);
  return el ? el.value : fallback;
}

function renderVideo() {
  const o = vid.opts;
  const body = document.getElementById("vid-body");
  const mine = o.narrations.filter((n) => n.mine);
  if (!mine.length) {
    body.innerHTML = `
      <p>A video is made from a narration, so its words can follow the voice. There's no narration of ${esc(vid.target.title)} yet.</p>
      ${o.narrations.length ? `<p class="hint">Other narrations in Exports can be used too; pick one below after making this one, or now.</p>` : ""}
      <div class="modal-actions">
        ${helpLinkHtml("video", "How videos work")}
        <span style="flex:1"></span>
        ${o.narrations.length ? `<button class="btn btn-ghost" id="vid-other">Use another narration</button>` : ""}
        <button class="btn btn-gold" id="vid-narrate">Narrate it first</button>
      </div>`;
    document.getElementById("vid-narrate").addEventListener("click", () => { const t = vid.target; closeVideo(); openNarration(t); });
    const other = document.getElementById("vid-other");
    if (other) other.addEventListener("click", () => { o.narrations.forEach((n) => { n.mine = true; }); renderVideo(); });
    return;
  }
  const pick = mine.some((n) => n.name === vid.target.narration) ? vid.target.narration : mine[0].name;
  const sel = mine.find((n) => n.name === pick);
  const size = videoChoice("size", "square");
  const bg = videoChoice("bg", sel.has_cover ? "cover" : "plain");
  const mins = (s) => (s < 90 ? `${s} s` : `${Math.round(s / 60)} min`);
  body.innerHTML = `
    <div class="vid-layout" id="vid-form">
      <div>
        <div class="field-row"><label for="vid-narration">Narration</label>
          <select id="vid-narration">${mine.map((n) => `<option value="${esc(n.name)}" ${n.name === pick ? "selected" : ""}>${esc(n.name)} (${mins(n.seconds)})</option>`).join("")}</select></div>
        <div class="vid-group"><div class="vid-group-h">Shape</div>
          <div class="vid-sizes" role="radiogroup" aria-label="Shape">${Object.entries(o.sizes).map(([k, v]) => `
            <label class="vid-size ${k === size ? "on" : ""}"><input type="radio" name="size" value="${k}" ${k === size ? "checked" : ""}>
              <span class="vid-shape" style="aspect-ratio:${v.width}/${v.height}"></span>
              <strong>${esc(v.label)}</strong><span class="muted">${esc(v.for)}</span></label>`).join("")}</div></div>
        <div class="vid-group"><div class="vid-group-h">Background</div>
          <div class="vid-bgs" role="radiogroup" aria-label="Background">
            ${sel.has_cover ? `<label><input type="radio" name="bg" value="cover" ${bg === "cover" ? "checked" : ""}> The project's front cover</label>` : ""}
            <label><input type="radio" name="bg" value="plain" ${bg === "plain" || (bg === "cover" && !sel.has_cover) ? "checked" : ""}> Plain</label>
            <label><input type="radio" name="bg" value="image" ${bg === "image" ? "checked" : ""}> A picture:
              <input type="file" id="vid-picture" accept="image/png,image/jpeg,image/webp"></label>
          </div></div>
        <div id="vid-tool"></div>
        <p class="hint">Made on this computer; nothing is uploaded. The video is as long as the narration, and goes into Exports.</p>
      </div>
      <div class="vid-preview"><img id="vid-preview" alt="A screen from the video"><div class="muted" id="vid-preview-note">Drawing a preview...</div></div>
    </div>
    <div class="modal-actions">
      ${helpLinkHtml("video", "How videos work")}
      <span style="flex:1"></span>
      <button class="btn btn-ghost" id="vid-cancel">Cancel</button>
      <button class="btn btn-gold" id="vid-go">Make video</button>
    </div>`;
  document.getElementById("vid-cancel").addEventListener("click", closeVideo);
  document.getElementById("vid-go").addEventListener("click", startVideo);
  document.getElementById("vid-narration").addEventListener("change", (ev) => { vid.target.narration = ev.target.value; renderVideo(); });
  body.querySelectorAll("input[name=size]").forEach((r) => r.addEventListener("change", renderVideo));
  body.querySelectorAll("input[name=bg]").forEach((r) => r.addEventListener("change", () => { if (r.value === "image" && !vid.picture) document.getElementById("vid-picture").click(); updatePreview(); }));
  document.getElementById("vid-picture").addEventListener("change", (ev) => {
    vid.picture = ev.target.files[0] || null;
    if (vid.picture) body.querySelector("input[name=bg][value=image]").checked = true;
    updatePreview();
  });
  mediaToolBox(document.getElementById("vid-tool"), o.tools, "Videos", (tools) => { o.tools = tools; renderVideo(); });
  updatePreview();
}

function videoForm() {
  const form = new FormData();
  form.append("name", document.getElementById("vid-narration").value);
  form.append("size", videoChoice("size", "square"));
  const bg = videoChoice("bg", "plain");
  form.append("background", bg);
  if (bg === "image" && vid.picture) form.append("image", vid.picture);
  return form;
}

function updatePreview() {
  clearTimeout(vid.previewTimer);
  vid.previewTimer = setTimeout(async () => {
    const img = document.getElementById("vid-preview");
    const note = document.getElementById("vid-preview-note");
    if (!img) return;
    if (videoChoice("bg", "plain") === "image" && !vid.picture) { note.textContent = "Choose a picture."; return; }
    note.textContent = "Drawing a preview...";
    try {
      const resp = await fetch("/api/video/preview", { method: "POST", body: videoForm(), headers: { "X-Minerva-Token": MINERVA_TOKEN } });
      if (!resp.ok) throw new Error((await resp.json()).error || "Couldn't draw a preview.");
      if (vid.previewUrl) URL.revokeObjectURL(vid.previewUrl);
      vid.previewUrl = URL.createObjectURL(await resp.blob());
      img.src = vid.previewUrl;
      note.textContent = "";
    } catch (e) { note.textContent = e.message; }
  }, 150);
}

async function startVideo() {
  if (!vid.opts.tools.ffmpeg) { toast("Set up the audio and video tool first.", true); return; }
  if (videoChoice("bg", "plain") === "image" && !vid.picture) { toast("Choose a picture, or another background.", true); return; }
  let j;
  try { j = await api("/api/video/start", { method: "POST", body: videoForm() }); } catch (e) { toast(e.message, true); return; }
  vid.jobId = j.id;
  renderVideoProgress(j);
  pollVideo();
}

function renderVideoProgress(j) {
  const body = document.getElementById("vid-body");
  if (!body) return;
  const pct = j.total ? Math.round((100 * j.done) / j.total) : null;
  body.innerHTML = `
    <p>Making the video of ${esc(j.label)}. You can close this and keep writing; it carries on.</p>
    <div class="progress ${pct == null ? "indeterminate" : ""}"><div style="width:${pct == null ? 100 : pct}%"></div></div>
    <p class="muted">${esc(j.message || "Starting...")}</p>
    <div class="modal-actions"><span style="flex:1"></span>
      <button class="btn btn-ghost" id="vid-stop">Stop</button>
      <button class="btn btn-gold" id="vid-hide">Close</button></div>`;
  document.getElementById("vid-hide").addEventListener("click", closeVideo);
  document.getElementById("vid-stop").addEventListener("click", async (ev) => {
    ev.target.disabled = true;
    try { await postJson(`/api/jobs/${vid.jobId}/cancel`); } catch (e) { toast(e.message, true); }
  });
}

async function pollVideo() {
  clearTimeout(vid.timer);
  if (!vid.jobId) return;
  let j;
  try { j = await api(`/api/jobs/${vid.jobId}`); } catch (e) { return; }
  if (j.status === "running") {
    renderVideoProgress(j);
    vid.timer = setTimeout(pollVideo, 1000);
    return;
  }
  vid.jobId = null;
  const body = document.getElementById("vid-body");
  if (!body) {
    if (j.status === "done") toast(`Video saved: ${j.result.name}`);
    else if (j.status === "failed") toast(`The video stopped: ${j.error}`, true);
    return;
  }
  if (j.status !== "done") {
    body.innerHTML = `<p class="${j.status === "failed" ? "warn-text" : ""}">${j.status === "failed" ? esc(j.error) : "Stopped."}</p>
      <div class="modal-actions"><span style="flex:1"></span><button class="btn" id="vid-back">Back</button></div>`;
    document.getElementById("vid-back").addEventListener("click", renderVideo);
    return;
  }
  body.innerHTML = exportResultHtml(j.result) + `
    <div class="modal-actions"><span style="flex:1"></span><button class="btn btn-gold" id="vid-done">Done</button></div>`;
  wireExportResult(body);
  document.getElementById("vid-done").addEventListener("click", closeVideo);
}
