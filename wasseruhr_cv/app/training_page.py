"""Small training page (GET /): look at the latest camera image, type in the
correct value, learn."""

from __future__ import annotations

from datetime import datetime
from html import escape

from .i18n import DEFAULT, LANGUAGES, QUERY, for_browser, translate

# Shared look of the training page and the admin page. All links are relative,
# so both pages also work behind the Home Assistant ingress.
BASE_CSS = """
  :root { --bg:#f6f7f9; --card:#fff; --text:#1c1f24; --muted:#5f6773; --border:#d9dde3;
          --ok:#1a7f37; --bad:#c2410c; --accent:#2457c5; --accent-text:#fff; --tile:#0b0d10; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#111317; --card:#1b1e24; --text:#e8eaed; --muted:#9aa3ae; --border:#2e333b;
            --ok:#4ac26b; --bad:#f08a4b; --accent:#5b8cff; --accent-text:#0b0d10; --tile:#000; }
  }
  * { box-sizing:border-box; }
  [hidden] { display:none !important; }
  body { margin:0; background:var(--bg); color:var(--text);
         font:16px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
  main { max-width:760px; margin:0 auto; padding:20px 16px 40px; }
  header.top { display:flex; align-items:baseline; justify-content:space-between; gap:12px; margin:0 0 10px; }
  h1 { font-size:1.35rem; margin:0; }
  h2 { font-size:1.05rem; margin:0 0 8px; }
  nav.languages { display:flex; gap:2px; font-size:.85rem; }
  nav.languages a { padding:2px 8px; border-radius:6px; border:1px solid transparent; color:var(--muted); text-decoration:none; }
  nav.languages a[aria-current="true"] { color:var(--text); border-color:var(--border); font-weight:600; }
  nav.tabs { display:flex; gap:4px; margin:0 0 14px; border-bottom:1px solid var(--border); }
  nav.tabs a { padding:8px 12px; color:var(--muted); text-decoration:none;
               border-bottom:2px solid transparent; margin-bottom:-1px; }
  nav.tabs a[aria-current="page"] { color:var(--text); border-bottom-color:var(--accent); font-weight:600; }
  .chips { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:16px; }
  .chip { border:1px solid var(--border); border-radius:999px; padding:2px 10px; font-size:.85rem; color:var(--muted); }
  .card { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:14px; margin-bottom:14px; }
  .value { font-size:1.6rem; font-weight:650; font-variant-numeric:tabular-nums; }
  .ok { color:var(--ok); } .bad { color:var(--bad); }
  .muted { color:var(--muted); font-size:.9rem; }
  img.image { display:block; width:100%; height:auto; margin:12px 0; border-radius:6px; background:#000; }
  form { display:flex; flex-wrap:wrap; gap:8px; align-items:end; margin-top:8px; }
  label { flex:1 1 100%; font-size:.9rem; color:var(--muted); }
  input, select { flex:1 1 160px; min-width:0; font:inherit; font-size:1.05rem; padding:8px 10px; border-radius:8px;
          border:1px solid var(--border); background:var(--bg); color:var(--text); font-variant-numeric:tabular-nums; }
  input[type=file] { font-size:.9rem; }
  button, .button { font:inherit; padding:9px 14px; border-radius:8px; border:1px solid transparent; cursor:pointer;
                     background:var(--accent); color:var(--accent-text); text-decoration:none; display:inline-block; }
  button.secondary, .button.secondary { background:transparent; color:var(--accent); border-color:var(--border); }
  button.danger { background:var(--bad); color:#fff; border-color:transparent; }
  button:disabled { opacity:.6; cursor:progress; }
  .message { min-height:1.5em; margin-top:10px; }
  .row { display:flex; gap:8px; flex-wrap:wrap; margin-top:14px; align-items:center; }
"""

_PAGE = """<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wasseruhr-CV</title>
<style>{css}</style>
</head>
<body>
<main>
  {header}
  <div class="chips">{chips}</div>
  {content}
</main>
{script}
</body>
</html>
"""

# Common start of the page scripts: texts of the language and t() to fill them in
_PRELUDE = r"""const LANG = "@@LANG@@", T = @@TEXTS@@;
const t = (k, v = {}) => (T[k] ?? k).replace(/\{(\w+)\}/g, (m, n) => n in v ? v[n] : m);
const LOCALE = (navigator.language || "").toLowerCase().startsWith(LANG) ? navigator.language : LANG;
"""

_SCRIPT = """
  document.querySelectorAll("[data-time]").forEach(el => {
    el.textContent = new Date(el.dataset.time).toLocaleString(LOCALE);
  });
  const form = document.getElementById("learn");
  form?.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const message = document.getElementById("message");
    const button = form.querySelector("button");
    const value = form.elements.value.value.trim().replace(",", ".");
    if (!/^\\d{1,9}(\\.\\d{1,3})?$/.test(value)) {
      message.className = "message bad"; message.textContent = t("format"); return;
    }
    button.disabled = true; message.className = "message muted"; message.textContent = t("learning");
    try {
      const r = await fetch(`learn?value=${encodeURIComponent(value)}&reading=${form.dataset.reading}`,
        {method: "POST", headers: {"Accept-Language": LANG}});
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || r.status);
      message.className = "message ok";
      message.textContent = t("learned_reading_again", {n: d.saved});
      setTimeout(() => location.href = "./", 900);
    } catch (e) {
      message.className = "message bad"; message.textContent = t("error", {text: e.message}); button.disabled = false;
    }
  });
  const camera = document.getElementById("camera");
  camera?.addEventListener("click", async () => {
    const message = document.getElementById("camera-message");
    camera.disabled = true; message.className = "message muted"; message.textContent = t("fetching_image");
    try {
      const r = await fetch("read-camera", {method: "POST", headers: {"Accept-Language": LANG}});
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || r.status);
      location.href = `./?reading=${d.reading}`;
    } catch (e) {
      message.className = "message bad"; message.textContent = t("error", {text: e.message}); camera.disabled = false;
    }
  });
"""


def script(language: str, code: str) -> str:
    """<script> with the texts of the language, t() and LOCALE before the actual code."""
    prelude = _PRELUDE.replace("@@LANG@@", language).replace("@@TEXTS@@", for_browser(language))
    return f"<script>\n{prelude}{code}</script>"


def _current(yes: bool, value: str) -> str:
    return f' aria-current="{value}"' if yes else ""


def header(active: str, admin: bool, language: str, query: str = "") -> str:
    """Title with the language switch, below it the tabs Training / Admin. The
    tabs are left out if the admin page cannot be reached here. `query` is kept
    when switching (e.g. "reading=5&")."""
    switch = "".join(
        f'<a href="?{query}{QUERY}={code}" hreflang="{code}" lang="{code}"{_current(code == language, "true")}>'
        f"{code.upper()}</a>"
        for code in LANGUAGES
    )
    html = (
        '<header class="top"><h1>Wasseruhr-CV</h1>'
        f'<nav class="languages" aria-label="{escape(translate("page.language", language))}">{switch}</nav>'
        "</header>"
    )
    if admin:
        tabs = [("./", "page.tab.training", "training"), ("admin", "page.tab.admin", "admin")]
        links = "".join(
            f'<a href="{href}"{_current(name == active, "page")}>{escape(translate(key, language))}</a>'
            for href, key, name in tabs
        )
        html += f'<nav class="tabs">{links}</nav>'
    return html


def render(
    *,
    learning: bool,
    training_images: int,
    missing: list[int],
    reading: int | None,
    time: datetime | None,
    value: float | None,
    certain: bool,
    is_latest: bool,
    camera: bool = False,
    admin: bool = True,
    interval: int | None = None,
    meter_reading: float | None = None,
    language: str = DEFAULT,
) -> str:
    def tr(key: str, **values) -> str:
        return translate(key, language, **values)

    chips = [
        tr("ui.chip.meter_reading", value=f"{meter_reading:.3f}") if meter_reading is not None else tr("ui.chip.no_meter_reading"),
        tr("ui.chip.auto_on", n=interval) if interval else tr("ui.chip.auto_off"),
        tr("ui.chip.learning_on" if learning else "ui.chip.learning_off"),
        tr("ui.chip.images_one" if training_images == 1 else "ui.chip.images_other", n=training_images),
        tr("ui.chip.missing", digits=", ".join(map(str, missing))) if missing else tr("ui.chip.all_learned"),
    ]
    chips_html = "".join(f'<span class="chip">{escape(c)}</span>' for c in chips)
    camera_button = (
        f'<button type="button" id="camera" class="secondary">{escape(tr("ui.read_camera"))}</button>' if camera else ""
    )
    page = dict(
        lang=language, css=BASE_CSS, chips=chips_html, script=script(language, _SCRIPT),
        header=header("training", admin, language, f"reading={reading}&" if reading is not None else ""),
    )

    if reading is None:
        hint = (
            tr("training.hint.auto_html", n=interval) if interval
            else tr("training.hint.camera_html") if camera
            else tr("training.hint.no_camera_html") if admin
            else escape(tr("training.hint.no_camera_option"))
        )
        content = (
            f'<div class="card"><p>{escape(tr("training.empty"))} {hint}</p>'
            f'<div class="row">{camera_button}<a class="button secondary" href="./">{escape(tr("training.reload"))}</a></div>'
            '<div id="camera-message" class="message muted"></div></div>'
        )
        return _PAGE.format(content=content, **page)

    value_text = "–" if value is None else f"{value:.3f}"
    verdict = (
        f'<span class="ok">{escape(tr("ui.certain"))}</span>' if certain
        else f'<span class="bad">{escape(tr("ui.uncertain"))}</span>'
    )
    newer_hint = "" if is_latest else f'<p class="muted">{escape(tr("training.newer"))}</p>'
    off_hint = "" if learning else f'<p class="muted">{escape(tr("training.learning_off"))}</p>'
    content = f"""<div class="card">
    <div class="muted">{escape(tr("training.reading", n=reading))} · <span data-time="{escape(time.isoformat())}"></span></div>
    <div><span class="value">{value_text}</span> m³ · {verdict}</div>
    {newer_hint}
    <img class="image" src="debug.png?reading={reading}" alt="{escape(tr("training.image_alt"))}">
    <form id="learn" data-reading="{reading}" autocomplete="off">
      <label for="value">{escape(tr("training.label"))}</label>
      <input id="value" name="value" inputmode="decimal" value="{'' if value is None else value_text}" placeholder="506.388">
      <button type="submit">{escape(tr("training.learn"))}</button>
    </form>
    <div id="message" class="message muted"></div>
    {off_hint}
  </div>
  <div class="row"><a class="button secondary" href="./">{escape(tr("training.latest"))}</a>{camera_button}</div>
  <div id="camera-message" class="message muted"></div>"""
    return _PAGE.format(content=content, **page)
