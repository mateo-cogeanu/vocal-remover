"use strict";

const $ = (id) => document.getElementById(id);
const api = () => window.pywebview.api;

const ICON = {
  play: '<svg viewBox="0 0 16 16"><path d="M4 2.5v11l9.5-5.5z"/></svg>',
  pause: '<svg viewBox="0 0 16 16"><path d="M4 2.5h3v11H4zM9 2.5h3v11H9z"/></svg>',
  folder: '<svg viewBox="0 0 16 16"><path d="M1.5 3.5a1 1 0 0 1 1-1h3.6l1.4 1.5h6a1 1 0 0 1 1 1v7.5a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1z"/></svg>',
  x: '<svg viewBox="0 0 10 10"><path d="M1.5 1.5l7 7M8.5 1.5l-7 7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
};

const state = {
  models: [],
  tools: [],
  model: null,
  ensemble: { on: false, with: null },
  extras: [],        // enabled tool keys
  keep: {},          // modelId -> [stem names]
  format: "WAV",
  output: "",
  queue: [],         // {path, name, size, status, frac, outputs, folder, error}
  running: false,
  jobMap: [],        // job file index -> queue index
  playing: null,     // path currently loaded in the player
  mode: null,        // "separate" | "download" while the worker runs
  dl: {},            // model id -> {status, frac, error}
};

/* ------------------------------------------------------------ boot */
window.addEventListener("pywebviewready", async () => {
  const boot = await api().bootstrap();
  const s = boot.settings || {};
  applyCatalog(boot);
  state.ensemble = Object.assign({ on: false, with: null }, s.ensemble);
  state.extras = (s.extras || []).filter((k) => state.tools.some((t) => t.key === k));
  state.model = state.models.find((m) => m.id === s.model) || state.models.find((m) => m.default) || state.models[0];
  state.keep = s.keep || {};
  state.format = s.format || "WAV";
  state.output = s.output || boot.defaultOutput;
  renderSide();
  renderQueue();
});

function applyCatalog(boot) {
  state.models = boot.models;
  state.tools = boot.tools || [];
  if (state.model) state.model = state.models.find((m) => m.id === state.model.id);
}

async function refreshCatalog() {
  applyCatalog(await api().bootstrap());
  renderSide();
}

function save() {
  api().save_settings({
    model: state.model?.id, keep: state.keep, format: state.format, output: state.output,
    ensemble: state.ensemble, extras: state.extras,
  });
}

/* ------------------------------------------------------------ sidebar */
function dots(n) {
  return `<span class="dots">${[1, 2, 3, 4, 5].map((i) => `<i class="${i <= n ? "on" : ""}"></i>`).join("")}</span>`;
}

function keepFor(model) {
  const k = state.keep[model.id];
  return k && k.length ? k : model.stems.slice();
}

function renderSide() {
  const box = $("models");
  box.innerHTML = "";
  for (const m of state.models) {
    const b = document.createElement("button");
    b.className = "model";
    b.setAttribute("role", "radio");
    b.setAttribute("aria-checked", String(m.id === state.model?.id));
    b.disabled = state.mode === "separate";
    b.innerHTML = `
      <span class="model-name">${esc(m.name)}</span>
      ${m.installed ? "" : `<span class="missing">Not downloaded</span>`}
      <span class="model-tag">${esc(m.tagline)}</span>
      <span class="model-meter meters">
        <span>Quality${dots(m.quality)}</span><span>Speed${dots(m.speed)}</span>
      </span>`;
    b.onclick = () => { state.model = m; save(); renderSide(); };
    box.appendChild(b);
  }

  const stems = $("stems");
  stems.innerHTML = "";
  if (state.model) {
    const keep = keepFor(state.model);
    for (const s of state.model.stems) {
      const c = document.createElement("button");
      c.className = "chip";
      c.setAttribute("role", "checkbox");
      c.setAttribute("aria-checked", String(keep.includes(s)));
      c.textContent = s;
      c.disabled = state.mode === "separate";
      c.onclick = () => {
        let k = keepFor(state.model);
        k = k.includes(s) ? k.filter((x) => x !== s) : [...k, s];
        if (!k.length) return; // always keep at least one stem
        state.keep[state.model.id] = state.model.stems.filter((x) => k.includes(x));
        save();
        renderSide();
      };
      stems.appendChild(c);
    }
  }

  renderEnsemble();
  renderTools();

  for (const b of $("format").children) {
    b.setAttribute("role", "radio");
    b.setAttribute("aria-checked", String(b.dataset.v === state.format));
    b.disabled = state.mode === "separate";
    b.onclick = () => { state.format = b.dataset.v; save(); renderSide(); };
  }

  $("outPath").textContent = prettyPath(state.output);
  $("outBtn").title = state.output;
  $("outBtn").disabled = state.mode === "separate";
  renderSetup();
  updateBar();
}

/* Ensemble: only between two Vocals + Instrumental models. */
function ensemblePartners() {
  return state.models.filter((m) => m.kind === "vocals" && m.installed && m.id !== state.model?.id);
}

function ensembleActive() {
  return state.ensemble.on && state.model?.kind === "vocals" && partner();
}

function partner() {
  const list = ensemblePartners();
  return list.find((m) => m.id === state.ensemble.with) || list[0] || null;
}

function renderEnsemble() {
  const box = $("ensemble");
  const eligible = state.model?.kind === "vocals" && ensemblePartners().length > 0;
  box.hidden = !eligible;
  if (!eligible) return;
  const on = $("ensembleOn");
  on.checked = state.ensemble.on;
  on.disabled = state.mode === "separate";
  on.onchange = () => { state.ensemble.on = on.checked; save(); renderSide(); };

  const list = $("ensembleWith");
  list.innerHTML = "";
  if (!state.ensemble.on) return;
  const lbl = document.createElement("div");
  lbl.className = "lbl";
  lbl.textContent = `Combine ${state.model.name} with`;
  list.appendChild(lbl);
  const current = partner();
  for (const m of ensemblePartners()) {
    const b = document.createElement("button");
    b.className = "pick";
    b.setAttribute("role", "radio");
    b.setAttribute("aria-checked", String(m.id === current?.id));
    b.textContent = m.name;
    b.disabled = state.mode === "separate";
    b.onclick = () => { state.ensemble.with = m.id; save(); renderSide(); };
    list.appendChild(b);
  }
}

function renderTools() {
  const sec = $("toolsSec");
  const hasVocals = state.model?.stems.includes("Vocals");
  sec.hidden = !state.tools.length || !hasVocals;
  const box = $("tools");
  box.innerHTML = "";
  const subs = {
    karaoke: "Adds Lead Vocals and Backing Vocals",
    dereverb: "Adds a dry vocal with the room sound taken out",
  };
  for (const t of state.tools) {
    const row = document.createElement("label");
    row.className = "toggle";
    row.innerHTML = `
      <span class="toggle-text">
        <span class="toggle-title">${esc(t.name)}</span>
        <span class="toggle-sub">${esc(subs[t.key] || "")}</span>
      </span>
      <input type="checkbox" role="switch">
      <span class="switch" aria-hidden="true"></span>`;
    const input = row.querySelector("input");
    input.checked = t.installed && state.extras.includes(t.key);
    input.disabled = state.mode === "separate" || !t.installed;
    if (!t.installed) row.querySelector(".toggle-sub").textContent = "Not downloaded yet";
    input.onchange = () => {
      state.extras = input.checked ? [...state.extras, t.key] : state.extras.filter((k) => k !== t.key);
      save();
    };
    box.appendChild(row);
  }
}

$("outBtn").onclick = async () => {
  const p = await api().pick_folder();
  if (p) { state.output = p; save(); renderSide(); }
};

/* ------------------------------------------------------------ queue */
function addFiles(files) {
  const have = new Set(state.queue.map((q) => q.path));
  for (const f of files) {
    if (have.has(f.path)) continue;
    state.queue.push({ ...f, status: "pending", frac: 0, outputs: [], folder: null, error: null });
  }
  hideBanner();
  renderQueue();
}

window.onFilesDropped = (files) => {
  document.body.classList.remove("dragging");
  if (state.mode === "separate") return;
  if (!files.length) return showBanner("Those files don't look like audio.");
  addFiles(files);
};

$("chooseBtn").onclick = $("addBtn").onclick = async () => addFiles(await api().pick_files());
$("clearBtn").onclick = () => {
  state.queue = [];
  stopPlayer();
  renderQueue();
};

function renderQueue() {
  const empty = state.queue.length === 0;
  $("empty").hidden = !empty;
  $("queueWrap").hidden = empty;
  const done = state.queue.filter((q) => q.status === "done").length;
  $("queueCount").textContent = `${state.queue.length} song${state.queue.length === 1 ? "" : "s"}` + (done ? ` · ${done} done` : "");
  $("addBtn").disabled = $("clearBtn").disabled = state.mode === "separate";

  const ul = $("queue");
  ul.innerHTML = "";
  state.queue.forEach((q, i) => ul.appendChild(renderItem(q, i)));
  updateBar();
}

function renderItem(q, i) {
  const li = document.createElement("li");
  li.className = "item";
  let meta = fmtSize(q.size);
  let metaClass = "";
  if (q.status === "working") meta = q.loading ? "Loading model…" : `${Math.round(q.frac * 100)}%`;
  if (q.status === "queued") meta = "Waiting";
  if (q.status === "done") { meta = "Done"; metaClass = "ok"; }
  if (q.status === "error") { meta = "Failed"; metaClass = "err"; }

  li.innerHTML = `
    <div class="item-row">
      <span class="item-name" title="${esc(q.path)}">${esc(q.name)}</span>
      <span class="item-meta ${metaClass}">${meta}</span>
      ${state.mode === "separate" ? "" : `<button class="x" aria-label="Remove">${ICON.x}</button>`}
    </div>`;
  const x = li.querySelector(".x");
  if (x) x.onclick = () => { state.queue.splice(i, 1); renderQueue(); };

  if (q.status === "working") {
    const p = document.createElement("div");
    p.className = "progress" + (q.frac === 0 ? " indeterminate" : "");
    p.innerHTML = `<div style="width:${q.frac * 100}%"></div>`;
    li.appendChild(p);
  }
  if (q.status === "error" && q.error) {
    const e = document.createElement("div");
    e.className = "item-meta err";
    e.style.marginTop = "6px";
    e.textContent = q.error;
    li.appendChild(e);
  }
  if (q.status === "done") {
    const s = document.createElement("div");
    s.className = "stems";
    for (const o of q.outputs) {
      const b = document.createElement("button");
      const on = state.playing === o.path && !$("audio").paused;
      b.className = "stem" + (on ? " playing" : "");
      b.innerHTML = (on ? ICON.pause : ICON.play) + esc(o.stem);
      b.onclick = () => togglePlay(o, q);
      s.appendChild(b);
    }
    const r = document.createElement("button");
    r.className = "stem reveal";
    r.innerHTML = ICON.folder + "Show in Finder";
    r.onclick = () => api().open_folder(q.folder);
    s.appendChild(r);
    li.appendChild(s);
  }
  return li;
}

/* ------------------------------------------------------------ run */
function updateBar() {
  const pending = state.queue.filter((q) => q.status !== "done").length;
  const go = $("goBtn");
  if (state.mode === "download") {
    go.className = "btn primary";
    go.textContent = "Separate";
    go.disabled = true;
  } else if (state.running) {
    go.textContent = "Cancel";
    go.className = "btn danger";
    go.disabled = false;
  } else {
    go.className = "btn primary";
    go.textContent = pending > 1 ? `Separate ${pending} songs` : "Separate";
    go.disabled = pending === 0 || !state.model?.installed;
  }
}

$("goBtn").onclick = async () => {
  if (state.running) {
    await api().cancel();
    return;
  }
  const idx = state.queue.map((q, i) => (q.status !== "done" ? i : -1)).filter((i) => i >= 0);
  if (!idx.length) return;
  state.jobMap = idx;
  idx.forEach((i) => Object.assign(state.queue[i], { status: "queued", frac: 0, error: null }));
  hideBanner();
  const ens = ensembleActive();
  const res = await api().start({
    models: ens ? [state.model.id, partner().id] : [state.model.id],
    tools: state.model.stems.includes("Vocals")
      ? state.extras.filter((k) => state.tools.find((t) => t.key === k)?.installed) : [],
    stems: keepFor(state.model),
    format: state.format,
    output_root: state.output,
    files: idx.map((i) => state.queue[i].path),
  });
  if (!res.ok) return showBanner(res.error);
  state.running = true;
  state.mode = "separate";
  setStatus(ens ? `${state.model.name} + ${partner().name}` : state.model.name);
  renderSide();
  renderQueue();
};

window.onWorker = (ev) => {
  if (state.mode === "download") return onDownload(ev);
  const q = ev.file !== undefined ? state.queue[state.jobMap[ev.file]] : null;
  switch (ev.type) {
    case "stage":
      if (q) {
        if (ev.stage === "loading") q.loading = true;
        else { q.loading = false; if (q.status !== "working") { q.status = "working"; q.frac = 0; } }
        q.step = ev.text;
      }
      setStatus(state.jobMap.length > 1 ? `${ev.file + 1} of ${state.jobMap.length} · ${ev.text}` : ev.text);
      break;
    case "progress":
      if (q) {
        q.frac = ev.frac;
        // cheap in-place update instead of a full re-render
        const li = $("queue").children[state.jobMap[ev.file]];
        const bar = li && li.querySelector(".progress");
        if (bar) {
          bar.classList.remove("indeterminate");
          bar.firstElementChild.style.width = `${ev.frac * 100}%`;
          q.loading = false;
          li.querySelector(".item-meta").textContent = `${Math.round(ev.frac * 100)}%`;
          return;
        }
      }
      break;
    case "file_done":
      Object.assign(q, { status: "done", frac: 1, outputs: ev.outputs, folder: ev.folder });
      break;
    case "file_error":
      Object.assign(q, { status: "error", error: ev.error });
      break;
    case "fatal":
      finish();
      showBanner(ev.error);
      break;
    case "exit":
      finish();
      if (ev.code === -15 || ev.code === 143) setStatus("Cancelled");
      else showBanner(`Separation stopped unexpectedly (code ${ev.code}).\n${ev.log || ""}`);
      break;
    case "done": {
      finish();
      const ok = state.queue.filter((x) => x.status === "done").length;
      setStatus(ok ? `Finished · saved to ${prettyPath(state.output)}` : "");
      break;
    }
  }
  renderQueue();
};

function finish() {
  state.running = false;
  state.mode = null;
  for (const q of state.queue) {
    if (["queued", "working"].includes(q.status)) Object.assign(q, { status: "pending", frac: 0, loading: false });
  }
  renderSide();
}

function setStatus(t) { $("status").textContent = t; }
function showBanner(t) { $("banner").textContent = t; $("banner").hidden = false; }
function hideBanner() { $("banner").hidden = true; }

/* ------------------------------------------------------------ model download */
function allModels() {
  return [...state.models, ...state.tools];
}

function fmtGB(mb) {
  return mb >= 1000 ? `${(mb / 1000).toFixed(1)} GB` : `${mb} MB`;
}

function renderSetup() {
  const missing = allModels().filter((m) => !m.installed);
  const downloading = state.mode === "download";
  $("setup").hidden = !missing.length && !downloading;
  if ($("setup").hidden) return;

  const mb = missing.reduce((a, m) => a + m.mb, 0);
  $("setupSub").textContent = downloading
    ? "Downloading and preparing models. You can keep using the app."
    : `${missing.length} model${missing.length === 1 ? "" : "s"} · ${fmtGB(mb)}. ` +
      "Needed once, then everything runs offline.";
  const btn = $("dlBtn");
  btn.textContent = downloading ? "Cancel" : missing.length === allModels().length ? "Download all" : "Download the rest";
  btn.className = downloading ? "btn danger" : "btn primary";
  btn.disabled = state.running && !downloading;

  const list = $("dlList");
  list.hidden = !Object.keys(state.dl).length;
  list.innerHTML = "";
  for (const m of allModels()) {
    const d = state.dl[m.id];
    if (!d) continue;
    const li = document.createElement("li");
    li.className = "dl-row";
    li.dataset.id = m.id;
    let meta = "Waiting", cls = "";
    if (d.status === "active") meta = d.stage === "Downloading" && d.frac ? `${Math.round(d.frac * 100)}%` : d.stage || "Starting";
    if (d.status === "done") { meta = "Ready"; cls = "ok"; }
    if (d.status === "error") { meta = "Failed"; cls = "err"; }
    li.innerHTML = `<span class="dl-name">${esc(m.name)}</span><span class="dl-meta ${cls}">${meta}</span>`;
    if (d.status === "active") {
      const p = document.createElement("div");
      p.className = "progress" + (d.frac ? "" : " indeterminate");
      p.innerHTML = `<div style="width:${(d.frac || 0) * 100}%"></div>`;
      li.appendChild(p);
    }
    if (d.status === "error") li.title = d.error;
    list.appendChild(li);
  }
}

$("dlBtn").onclick = async () => {
  if (state.mode === "download") return api().cancel();
  state.dl = {};
  for (const m of allModels()) if (!m.installed) state.dl[m.id] = { status: "waiting", frac: 0 };
  hideBanner();
  const res = await api().download_models();
  if (!res.ok) return showBanner(res.error);
  state.running = true;
  state.mode = "download";
  renderSide();
  renderQueue();
};

function onDownload(ev) {
  const d = ev.id && state.dl[ev.id];
  switch (ev.type) {
    case "dl_start":
      if (d) Object.assign(d, { status: "active", frac: 0, stage: "Starting" });
      break;
    case "dl_stage":
      if (d) d.stage = ev.text;
      break;
    case "dl_progress":
      if (d) {
        d.frac = ev.done / ev.total;
        // converting begins as soon as the checkpoint is in
        if (d.frac >= 1) { d.stage = "Preparing"; d.frac = 0; }
        else d.stage = "Downloading";
        const row = $("dlList").querySelector(`[data-id="${CSS.escape(ev.id)}"]`);
        const bar = row && row.querySelector(".progress");
        if (bar && d.frac) {
          bar.classList.remove("indeterminate");
          bar.firstElementChild.style.width = `${d.frac * 100}%`;
          row.querySelector(".dl-meta").textContent = `${Math.round(d.frac * 100)}%`;
          return;
        }
      }
      break;
    case "dl_done":
      if (d) Object.assign(d, { status: "done", frac: 1 });
      refreshCatalog(); // the model is usable right away
      break;
    case "dl_error":
      if (d) Object.assign(d, { status: "error", error: ev.error });
      showBanner(`Couldn't download ${allModels().find((m) => m.id === ev.id)?.name}: ${ev.error}`);
      break;
    case "fatal":
      showBanner(ev.error);
      return endDownload();
    case "exit":
      if (!(ev.code === -15 || ev.code === 143)) showBanner(`Download stopped unexpectedly (code ${ev.code}).\n${ev.log || ""}`);
      return endDownload();
    case "done":
      return endDownload();
  }
  renderSetup();
}

async function endDownload() {
  state.running = false;
  state.mode = null;
  for (const id in state.dl) if (state.dl[id].status !== "done" && state.dl[id].status !== "error") delete state.dl[id];
  await refreshCatalog();
  if (allModels().every((m) => m.installed)) {
    state.dl = {};
    setStatus("All models ready");
  }
  renderSide();
  renderQueue();
}

/* ------------------------------------------------------------ player */
const audio = $("audio");

async function togglePlay(o, q) {
  if (state.playing === o.path) {
    audio.paused ? audio.play() : audio.pause();
    return;
  }
  const t = audio.paused ? 0 : audio.currentTime; // keep position when switching stems of a song
  audio.src = await api().media_url(o.path);
  state.playing = o.path;
  $("playerTitle").textContent = `${o.stem} — ${q.name.replace(/\.[^.]+$/, "")}`;
  $("player").hidden = false;
  audio.addEventListener("loadedmetadata", () => { if (t < audio.duration) audio.currentTime = t; }, { once: true });
  audio.play();
}

function stopPlayer() {
  audio.pause();
  audio.removeAttribute("src");
  state.playing = null;
  $("player").hidden = true;
}

$("playBtn").onclick = () => (audio.paused ? audio.play() : audio.pause());
audio.onplay = audio.onpause = () => {
  $("player").classList.toggle("is-playing", !audio.paused);
  renderQueue();
};
audio.ontimeupdate = () => {
  if (!audio.duration) return;
  const p = audio.currentTime / audio.duration;
  if (!seeking) $("seek").value = Math.round(p * 1000);
  $("seek").style.setProperty("--p", `${p * 100}%`);
  $("playerTime").textContent = fmtTime(audio.currentTime);
};
let seeking = false;
$("seek").oninput = () => {
  seeking = true;
  $("seek").style.setProperty("--p", `${$("seek").value / 10}%`);
};
$("seek").onchange = () => {
  if (audio.duration) audio.currentTime = ($("seek").value / 1000) * audio.duration;
  seeking = false;
};

document.addEventListener("keydown", (e) => {
  if (e.code === "Space" && state.playing && e.target.tagName !== "INPUT") {
    e.preventDefault();
    audio.paused ? audio.play() : audio.pause();
  }
});

/* ------------------------------------------------------------ drag highlight */
let dragDepth = 0;
document.addEventListener("dragenter", (e) => { e.preventDefault(); if (state.mode !== "separate" && ++dragDepth === 1) document.body.classList.add("dragging"); });
document.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; document.body.classList.remove("dragging"); } });
document.addEventListener("dragover", (e) => e.preventDefault());
document.addEventListener("drop", () => { dragDepth = 0; document.body.classList.remove("dragging"); });

/* ------------------------------------------------------------ utils */
function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function fmtSize(b) {
  if (!b) return "";
  return b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.round(b / 1e3)} KB`;
}
function fmtTime(s) {
  const m = Math.floor(s / 60);
  return `${m}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}
function prettyPath(p) {
  return (p || "").replace(/^\/Users\/[^/]+/, "~");
}
