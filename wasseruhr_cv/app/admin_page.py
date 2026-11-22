"""Admin page (GET /admin): HTML per language, the data is fetched from
/admin/… . All paths are relative to the page <base>/admin, so everything also
works behind the Home Assistant ingress (/api/hassio_ingress/<token>/).

Texts: {{key}} in the HTML is translated when the page is built (escaped,
except keys ending in _html); the script gets its texts with t() from the
"ui." keys (see i18n.py)."""

from __future__ import annotations

import re
from functools import lru_cache
from html import escape

from .i18n import LANGUAGES, translate
from .training_page import BASE_CSS, header, script

_CSS = """
  .list { list-style:none; margin:0; padding:0; }
  .list li { display:flex; flex-wrap:wrap; gap:4px 12px; align-items:baseline; padding:7px 0; border-top:1px solid var(--border); }
  .list li:first-child { border-top:0; }
  .list a { color:var(--accent); text-decoration:none; font-weight:600; }
  .num { font-variant-numeric:tabular-nums; font-weight:600; }
  .digit-row { display:flex; gap:10px; align-items:flex-start; padding:8px 0; border-top:1px solid var(--border); }
  .digit-row:first-child { border-top:0; }
  .digit-head { flex:0 0 40px; font-size:1.4rem; font-weight:650; line-height:1; }
  .digit-head small { display:block; font-size:.75rem; font-weight:400; color:var(--muted); margin-top:4px; }
  .tiles { display:flex; flex-wrap:wrap; gap:4px; min-width:0; }
  .tiles img { width:36px; height:60px; image-rendering:pixelated; border-radius:3px; background:var(--tile); cursor:pointer; }
  .tiles .none { color:var(--bad); font-size:.9rem; }
  .training-image { padding:12px 0; border-top:1px solid var(--border); }
  .training-image:first-child { border-top:0; }
  .training-image img { display:block; width:100%; max-width:440px; height:auto; border-radius:6px; background:#000; margin-bottom:6px; }
  .training-image.marked { outline:2px solid var(--accent); outline-offset:6px; border-radius:6px; }
  .training-image input { flex:0 1 150px; }
  dl.settings { display:grid; grid-template-columns:max-content minmax(0,1fr); gap:4px 14px; margin:0; }
  dl.settings dt { color:var(--muted); font-size:.9rem; }
  dl.settings dd { margin:0; font-variant-numeric:tabular-nums; overflow-wrap:anywhere; }
  section > p.muted:first-of-type { margin-top:0; }
  #m-load:empty { display:none; }
  /* Own file button: the native one is labelled in the browser's language, not the page's */
  label.file { flex:1 1 260px; display:flex; align-items:center; gap:8px; min-width:0; cursor:pointer;
               font-size:1rem; color:var(--text); position:relative; }
  label.file input { position:absolute; width:1px; height:1px; opacity:0; }
  label.file .button { white-space:nowrap; flex:none; }
  label.file:focus-within .button { outline:2px solid var(--accent); outline-offset:2px; }
  label.file .file-name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--muted); font-size:.9rem; }
"""

_SCRIPT = r"""
const $ = (selector) => document.querySelector(selector);
const VALUE_PATTERN = /^\d{1,9}([.,]\d{1,3})?$/;
const PAGE_SIZE = 30;
let info = null, allImages = [], showAll = false;

function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) e.setAttribute(k, v === true ? "" : v);
  }
  for (const child of children) if (child != null) e.append(child);
  return e;
}
async function api(path, options = {}) {
  options.headers = {"Accept-Language": LANG, ...(options.headers || {})};
  const r = await fetch(path, options);
  const d = (r.headers.get("content-type") || "").includes("json") ? await r.json() : null;
  if (!r.ok) throw new Error((d && d.detail) || `HTTP ${r.status}`);
  return d;
}
function report(id, text, kind = "muted") {
  const m = document.getElementById(id); m.className = `message ${kind}`; m.textContent = text;
}
const failed = (e) => t("error", {text: e.message});
const when = (iso) => new Date(iso).toLocaleString(LOCALE, {dateStyle: "medium", timeStyle: "short"});
const m3 = (v) => v == null ? "–" : Number(v).toFixed(3);
const dot = (v) => v.trim().replace(",", ".");
const onOff = (b) => t(b ? "on" : "off");
const plural = (key, n) => t(`${key}_${n === 1 ? "one" : "other"}`, {n});
const statusText = (l) => `${t("status." + l.status)}${l.reason ? " – " + l.reason : ""}`;
function stampTime(stamp) {
  const m = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})/.exec(stamp);
  return m ? new Date(Date.UTC(+m[1], m[2] - 1, +m[3], +m[4], +m[5], +m[6])).toISOString() : null;
}
// Two-click confirmation without a browser dialog (also works inside the HA frame)
function confirmed(button, question) {
  if (button.dataset.armed) { clearTimeout(button._t); disarm(button); return true; }
  button.dataset.armed = "1"; button.dataset.text = button.textContent; button.dataset.cls = button.className;
  button.textContent = question; button.className = "danger";
  button._t = setTimeout(() => disarm(button), 4000);
  return false;
}
function disarm(button) {
  if (!button.dataset.armed) return;
  delete button.dataset.armed; button.textContent = button.dataset.text; button.className = button.dataset.cls;
}
document.querySelectorAll("label.file input").forEach(input => {
  const name = input.parentElement.querySelector(".file-name");
  const show = () => { name.textContent = input.files[0] ? input.files[0].name : t("file.none"); };
  input.addEventListener("change", show);
  input.form.addEventListener("reset", () => setTimeout(show));
});
async function loadAll() {
  await Promise.all([loadInfo(), loadReadings(), loadTemplates(), loadImages()]);
}

// ---- Overview & settings -------------------------------------------------------
async function loadInfo() {
  info = await api("admin/info");
  const templates = Object.values(info.templates_per_digit).reduce((a, b) => a + b, 0);
  const chips = [
    t("chip.version", {version: info.version}),
    t(info.learning ? "chip.learning_on" : "chip.learning_off"),
    plural("chip.images", info.training_images),
    plural("chip.templates", templates),
    info.missing_templates.length ? t("chip.missing", {digits: info.missing_templates.join(", ")}) : t("chip.all_learned"),
  ];
  const bundled = info.bundled_model;
  if (bundled && bundled.installed) chips.push(t("chip.bundled_model", {time: when(bundled.time)}));
  $("#chips").replaceChildren(...chips.map(c => el("span", {class: "chip", text: c})));
  $("#empty-hint").hidden = info.training_images > 0 || templates > 0;

  $("#camera").hidden = !info.camera_ready;
  $("#camera-hint").textContent = info.camera_ready ? ""
    : info.camera ? t("camera.no_ha", {camera: info.camera}) : t("camera.tip");

  const s = info.settings;
  const rows = [
    [t("s.learning"), info.learning ? t("on") : t("s.frozen")],
    [t("s.min_score"), s.MIN_SCORE],
    [t("s.min_margin"), s.MIN_MARGIN],
    [t("s.max_templates"), t("s.at_most", {n: s.MAX_TEMPLATES_PER_DIGIT})],
    [t("s.shift"), `±${s.SHIFT} px`],
    [t("s.camera"), info.camera || "–"],
    [t("s.admin"), t(s.ADMIN_INGRESS_ONLY ? "s.ha_only" : "s.network")],
    [t("s.http"), onOff(s.HTTP)],
    [t("s.https"), onOff(s.HTTPS)],
    [t("s.language"), t("s.language_" + s.LANGUAGE)],
    ["ROIs", el("code", {text: JSON.stringify(s.ROIS)})],
  ];
  showAutoReading(info.auto_reading);
  loadCameras();
  $("#settings").replaceChildren(...rows.flatMap(([k, v]) => [el("dt", {text: k}), el("dd", {}, typeof v === "object" ? v : String(v))]));
  $("#settings-hint").textContent = t(info.addon ? "s.hint_addon" : "s.hint_docker");
}

// ---- Auto-reading --------------------------------------------------------------
function showAutoReading(a) {
  const l = a.last;
  const helper = a.input_number ? a.input_number + (a.input_number_missing ? t("a.helper_missing") : "") : null;
  const targets = [a.sensor, helper].filter(Boolean).join(", ") || t("a.no_targets");
  const status = a.active ? t("a.reads_every", {n: a.interval_minutes})
    : a.interval_minutes === 0 ? t("a.off_interval") : !a.camera ? t("a.off_camera") : t("a.off_ha");
  const rows = [
    [t("a.status"), status],
    [t("s.camera"), a.camera || "–"],
    [t("a.targets"), targets],
    [t("a.meter_reading"), a.meter_reading == null ? t("a.no_meter_reading")
      : t("a.meter_reading_value", {value: m3(a.meter_reading), time: when(a.meter_reading_time)})],
    [t("a.last_check"), l ? `${when(l.time)}: ${statusText(l)}` : t("a.no_check")],
  ];
  if (l && l.sent && l.sent !== "ok") rows.push([t("a.sending"), t("a.failed", {text: l.sent})]);
  $("#auto-reading").replaceChildren(...rows.flatMap(([k, v]) => [el("dt", {text: k}), el("dd", {text: v})]));
  $("#run-now").hidden = !a.camera;
}
let camerasLoaded = false;
async function loadCameras() {
  if (camerasLoaded || !info || !info.camera_ready && !info.ha_access) return;
  camerasLoaded = true;
  let d;
  try { d = await api("admin/cameras"); }
  catch (e) { report("m-auto", t("cameras_failed", {text: e.message}), "bad"); return; }
  const list = $("#camera-list");
  list.replaceChildren(
    el("option", {value: "", text: d.cameras.length ? t("camera.choose") : t("camera.none")}),
    ...d.cameras.map(c => el("option", {value: c.entity_id, selected: c.entity_id === d.current,
      text: `${c.name} (${c.entity_id})${c.state === "unavailable" ? t("camera.unavailable") : ""}`})));
  $("#camera-choice").hidden = false;
  $("#camera-choice").dataset.canSave = d.can_save ? "1" : "";
  if (d.current) showPreview(d.current);
}
function showPreview(entity) {
  const image = $("#camera-preview");
  if (!entity) { image.hidden = true; return; }
  image.onerror = () => { image.hidden = true; report("m-auto", t("camera.no_image", {entity}), "bad"); };
  image.onload = () => { image.hidden = false; };
  image.src = `admin/cameras/${encodeURIComponent(entity)}/image?t=${Date.now()}`;
}
$("#camera-list").addEventListener("change", (ev) => showPreview(ev.currentTarget.value));
$("#camera-choice").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.currentTarget, button = f.querySelector("button"), entity = f.elements.camera.value;
  if (!entity) { report("m-auto", t("camera.please_choose"), "bad"); return; }
  if (!f.dataset.canSave) { report("m-auto", t("camera.variable", {entity}), "bad"); return; }
  button.disabled = true; report("m-auto", t("camera.saving"));
  try {
    await api(`admin/camera?entity_id=${encodeURIComponent(entity)}`, {method: "POST"});
    await new Promise(r => setTimeout(r, 4000));
    for (let i = 0; i < 45; i++) {  // wait until the add-on answers again
      try { const now = await api("admin/info"); if (now.camera === entity) { location.reload(); return; } } catch (_) {}
      await new Promise(r => setTimeout(r, 2000));
    }
    report("m-auto", t("camera.saved"), "ok");
  } catch (e) { report("m-auto", failed(e), "bad"); button.disabled = false; }
});

$("#run-now").addEventListener("click", async (ev) => {
  const button = ev.currentTarget;
  button.disabled = true; report("m-auto", t("reading_and_checking"));
  try {
    const a = await api("admin/auto-reading/run", {method: "POST"});
    const l = a.last;
    report("m-auto", statusText(l), l.status === "error" || l.status === "rejected" ? "bad" : "ok");
    await Promise.all([loadInfo(), loadReadings()]);
  } catch (e) { report("m-auto", failed(e), "bad"); }
  button.disabled = false;
});
$("#meter-reading").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.currentTarget, button = f.querySelector("button"), value = f.elements.value.value;
  if (!VALUE_PATTERN.test(value.trim())) { report("m-auto", t("format"), "bad"); return; }
  if (!confirmed(button, t("really_set"))) return;
  button.disabled = true;
  try {
    await api(`admin/auto-reading/meter-reading?value=${encodeURIComponent(dot(value))}`, {method: "POST"});
    report("m-auto", t("meter_reading_set", {value: m3(dot(value))}), "ok"); f.reset();
    await loadInfo();
  } catch (e) { report("m-auto", failed(e), "bad"); }
  button.disabled = false;
});

// ---- Recent readings -----------------------------------------------------------
async function loadReadings() {
  const readings = await api("admin/readings");
  $("#readings").replaceChildren(...(readings.length ? readings.map(r => el("li", {},
    el("a", {href: `./?reading=${r.number}`, text: `#${r.number}`}),
    el("span", {class: "num", text: `${m3(r.value)} m³`}),
    el("span", {class: r.certain ? "ok" : "bad", text: t(r.certain ? "certain" : "uncertain")}),
    el("span", {class: "muted", text: when(r.time)}),
  )) : [el("li", {class: "muted", text: t("no_readings")})]));
}

// ---- Templates -----------------------------------------------------------------
async function loadTemplates() {
  const data = await api("admin/templates");
  $("#templates").replaceChildren(...Object.entries(data).map(([digit, templates]) =>
    el("div", {class: "digit-row"},
      el("div", {class: "digit-head"}, digit, el("small", {text: `${templates.length}×`})),
      el("div", {class: "tiles"}, ...(templates.length ? templates.map(tpl => {
        const [stamp, wheel] = tpl.name.replace(/\.png$/, "").split("_r");
        const time = stampTime(stamp);
        return el("img", {
          src: `data:image/png;base64,${tpl.png}`, alt: t("template.alt", {digit}),
          title: t("template.title", {wheel, from: time ? t("template.from", {time: when(time)}) : ""}),
          onclick: () => showImage(stamp),
        });
      }) : [el("span", {class: "none", text: t("template.none")})]))
    )));
}
function showImage(timestamp) {
  const i = allImages.findIndex(img => img.timestamp === timestamp);
  if (i < 0) { report("m-templates", t("template.no_image"), "bad"); return; }
  if (i >= PAGE_SIZE && !showAll) { showAll = true; renderImages(); }
  const card = document.getElementById(`img-${timestamp}`);
  card.scrollIntoView({behavior: "smooth", block: "center"});
  card.classList.add("marked");
  setTimeout(() => card.classList.remove("marked"), 2500);
}
$("#rebuild").addEventListener("click", async (ev) => {
  const button = ev.currentTarget;
  if (!info.learning && !confirmed(button, t("rebuild.anyway"))) return;
  button.disabled = true; report("m-templates", t("rebuild.running"));
  try {
    await api("admin/rebuild", {method: "POST"});
    report("m-templates", t("rebuild.done"), "ok");
    await Promise.all([loadInfo(), loadTemplates()]);
  } catch (e) { report("m-templates", failed(e), "bad"); }
  button.disabled = false;
});

// ---- Training images -----------------------------------------------------------
async function loadImages() {
  allImages = await api("admin/images");
  renderImages();
}
function renderImages() {
  const visible = showAll ? allImages : allImages.slice(0, PAGE_SIZE);
  $("#image-count").textContent = `(${allImages.length})`;
  const more = $("#more");
  more.hidden = showAll || allImages.length <= PAGE_SIZE;
  more.textContent = t("images.show_all", {n: allImages.length});
  $("#images").replaceChildren(...(visible.length ? visible.map(imageCard)
    : [el("p", {class: "muted", text: t("images.none")})]));
}
function imageCard(img) {
  const path = `admin/images/${encodeURIComponent(img.name)}`;
  const input = el("input", {name: "value", inputmode: "decimal", value: m3(img.value), "aria-label": t("meter_reading_m3")});
  const save = el("button", {type: "submit", class: "secondary", text: t("images.save")});
  const remove = el("button", {type: "button", class: "secondary", text: t("images.delete")});
  const message = el("div", {class: "message muted"});
  const fail = (e, button) => { message.className = "message bad"; message.textContent = failed(e); button.disabled = false; };
  const form = el("form", {autocomplete: "off"}, input, save, remove);
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!VALUE_PATTERN.test(input.value.trim())) { fail(new Error(t("format")), save); return; }
    save.disabled = true;
    try {
      const d = await api(`${path}/value?value=${encodeURIComponent(dot(input.value))}`, {method: "POST"});
      await afterChange(d, t("images.changed", {value: m3(dot(input.value))}));
    } catch (e) { fail(e, save); }
  });
  remove.addEventListener("click", async () => {
    if (!confirmed(remove, t("images.really_delete"))) return;
    remove.disabled = true;
    try { await afterChange(await api(`${path}/delete`, {method: "POST"}), t("images.deleted")); }
    catch (e) { fail(e, remove); }
  });
  return el("div", {class: "training-image", id: `img-${img.timestamp}`},
    el("a", {href: path, target: "_blank", rel: "noopener", title: t("images.open")},
      el("img", {src: `${path}?counter=1`, alt: t("images.alt", {value: m3(img.value)}), loading: "lazy"})),
    el("div", {}, el("span", {class: "num", text: `${m3(img.value)} m³`}), el("span", {class: "muted", text: ` · ${when(img.time)}`})),
    form, message);
}
async function afterChange(d, text) {
  const extra = t(d.templates_rebuilt ? "rebuild.done" : "images.unchanged");
  report("m-images", `${text}. ${extra}`, "ok");
  await Promise.all([loadInfo(), loadTemplates(), loadImages()]);
}
$("#more").addEventListener("click", () => { showAll = true; renderImages(); });

// ---- Training ------------------------------------------------------------------
$("#camera").addEventListener("click", async (ev) => {
  const button = ev.currentTarget;
  button.disabled = true; report("m-training", t("fetching_image"));
  try { const d = await api("read-camera", {method: "POST"}); location.href = `./?reading=${d.reading}`; }
  catch (e) { report("m-training", failed(e), "bad"); button.disabled = false; }
});
$("#upload").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.currentTarget, button = f.querySelector("button"), file = f.elements.file.files[0], value = f.elements.value.value;
  if (!file) { report("m-training", t("upload.no_image"), "bad"); return; }
  if (!VALUE_PATTERN.test(value.trim())) { report("m-training", t("upload.format"), "bad"); return; }
  button.disabled = true; report("m-training", t("learning"));
  try {
    const d = await api(`learn?value=${encodeURIComponent(dot(value))}`,
      {method: "POST", headers: {"Content-Type": file.type || "image/jpeg"}, body: file});
    report("m-training", t("upload.learned", {n: d.saved}), "ok");
    f.reset();
    await Promise.all([loadInfo(), loadTemplates(), loadImages()]);
  } catch (e) { report("m-training", failed(e), "bad"); }
  button.disabled = false;
});

// ---- Export & import -----------------------------------------------------------
$("#import").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.currentTarget, button = f.querySelector("button"), file = f.elements.file.files[0], mode = f.elements.mode.value;
  if (!file) { report("m-import", t("import.no_zip"), "bad"); return; }
  if (mode === "replace" && !confirmed(button, t("import.really"))) return;
  button.disabled = true; report("m-import", t("import.running"));
  try {
    const d = await api(`admin/import?mode=${mode}`,
      {method: "POST", headers: {"Content-Type": "application/zip"}, body: file});
    const parts = [t(mode === "replace" ? "import.taken" : "import.new", {n: d.new_images})];
    if (d.skipped) parts.push(t("import.skipped", {n: d.skipped}));
    parts.push(t(d.templates_rebuilt ? "import.templates_rebuilt"
      : mode === "replace" ? "import.templates_from_zip" : "import.templates_unchanged"));
    report("m-import", parts.join(" · "), "ok");
    f.reset();
    await loadAll();
  } catch (e) { report("m-import", failed(e), "bad"); }
  button.disabled = false;
});

$("#reset").addEventListener("click", async (ev) => {
  const button = ev.currentTarget;
  if (!confirmed(button, t("reset.really"))) return;
  button.disabled = true;
  try {
    await api("admin/reset", {method: "POST"});
    report("m-import", t("reset.done"), "ok");
    await loadAll();
  } catch (e) { report("m-import", failed(e), "bad"); }
  button.disabled = false;
});

loadAll().catch(e => report("m-load", t("load_failed", {text: e.message}), "bad"));
"""

_HTML = """<!doctype html>
<html lang="@@LANG@@">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{admin.title}}</title>
<style>@@CSS@@</style>
</head>
<body>
<main>
  @@HEADER@@
  <div class="chips" id="chips"></div>
  <div id="m-load" class="message"></div>

  <section class="card" id="empty-hint" hidden>
    <h2>{{admin.empty.title}}</h2>
    <p class="muted">{{admin.empty.text}}</p>
    <div class="row"><a class="button" href="#backup">{{admin.empty.import}}</a>
      <a class="button secondary" href="./">{{admin.empty.training}}</a></div>
  </section>

  <section class="card">
    <h2>{{admin.auto.title}}</h2>
    <p class="muted">{{admin.auto.text}}</p>
    <dl class="settings" id="auto-reading"></dl>
    <form id="camera-choice" autocomplete="off" hidden>
      <label for="camera-list">{{admin.auto.camera_label}}</label>
      <select id="camera-list" name="camera"></select>
      <button type="submit">{{admin.auto.apply}}</button>
    </form>
    <img id="camera-preview" class="image" alt="{{admin.auto.preview}}" hidden>
    <div class="row"><button type="button" id="run-now" hidden>{{admin.auto.run_now}}</button></div>
    <form id="meter-reading" autocomplete="off">
      <label>{{admin.auto.set_label}}</label>
      <input name="value" inputmode="decimal" placeholder="506.388" aria-label="{{ui.meter_reading_m3}}">
      <button type="submit" class="secondary">{{admin.auto.set}}</button>
    </form>
    <div id="m-auto" class="message"></div>
  </section>

  <section class="card">
    <h2>{{admin.training.title}}</h2>
    <div class="row" style="margin-top:0">
      <button type="button" id="camera" hidden>{{ui.read_camera}}</button>
      <a class="button secondary" href="./">{{admin.training.check}}</a>
    </div>
    <p class="muted" id="camera-hint"></p>
    <form id="upload" autocomplete="off">
      <label>{{admin.training.upload_label}}</label>
      <label class="file"><input type="file" name="file" accept="image/jpeg,image/png">
        <span class="button secondary">{{admin.file.choose}}</span><span class="file-name">{{ui.file.none}}</span></label>
      <input name="value" inputmode="decimal" placeholder="506.388" aria-label="{{ui.meter_reading_m3}}">
      <button type="submit">{{admin.training.learn}}</button>
    </form>
    <div id="m-training" class="message"></div>
  </section>

  <section class="card">
    <h2>{{admin.readings.title}}</h2>
    <p class="muted">{{admin.readings.text}}</p>
    <ul class="list" id="readings"></ul>
  </section>

  <section class="card">
    <h2>{{admin.templates.title}}</h2>
    <p class="muted">{{admin.templates.text}}</p>
    <div id="templates"></div>
    <div class="row"><button type="button" class="secondary" id="rebuild">{{admin.templates.rebuild}}</button></div>
    <div id="m-templates" class="message"></div>
  </section>

  <section class="card">
    <h2>{{admin.images.title}} <span id="image-count" class="muted"></span></h2>
    <p class="muted">{{admin.images.text}}</p>
    <div id="m-images" class="message"></div>
    <div id="images"></div>
    <div class="row"><button type="button" class="secondary" id="more" hidden></button></div>
  </section>

  <section class="card" id="backup">
    <h2>{{admin.backup.title}}</h2>
    <p class="muted">{{admin.backup.text}}</p>
    <div class="row" style="margin-top:0"><a class="button" href="admin/export.zip" download>{{admin.backup.export}}</a></div>
    <form id="import" autocomplete="off">
      <label>{{admin.backup.import_label}}</label>
      <label class="file"><input type="file" name="file" accept=".zip,application/zip">
        <span class="button secondary">{{admin.file.choose}}</span><span class="file-name">{{ui.file.none}}</span></label>
      <select name="mode" aria-label="{{admin.backup.mode}}">
        <option value="merge">{{admin.backup.merge}}</option>
        <option value="replace">{{admin.backup.replace}}</option>
      </select>
      <button type="submit">{{admin.backup.import}}</button>
    </form>
    <div class="row"><button type="button" id="reset" class="secondary">{{admin.backup.reset}}</button></div>
    <div id="m-import" class="message"></div>
  </section>

  <section class="card">
    <h2>{{admin.settings.title}}</h2>
    <dl class="settings" id="settings"></dl>
    <p class="muted" id="settings-hint"></p>
  </section>
</main>
@@SCRIPT@@
</body>
</html>
"""

_MARKER = re.compile(r"\{\{([\w.]+)\}\}")


@lru_cache(maxsize=len(LANGUAGES))
def page(language: str) -> str:
    """The admin page in one language (built once, then served from the cache)."""

    def text(m: re.Match) -> str:
        key = m.group(1)
        value = translate(key, language)
        return value if key.endswith("_html") else escape(value)

    return (
        _MARKER.sub(text, _HTML)
        .replace("@@LANG@@", language)
        .replace("@@CSS@@", BASE_CSS + _CSS)
        .replace("@@HEADER@@", header("admin", True, language))
        .replace("@@SCRIPT@@", script(language, _SCRIPT))
    )
