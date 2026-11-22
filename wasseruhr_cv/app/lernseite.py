"""Kleine Lernseite (GET /): letztes Kamerabild ansehen, richtigen Wert eintippen, lernen."""

from __future__ import annotations

from datetime import datetime
from html import escape

from .sprache import SPRACHEN, STANDARD, fuer_browser, uebersetzen

# Gemeinsames Aussehen von Lernseite und Verwaltung. Alle Links sind relativ,
# damit beide Seiten auch hinter dem Home-Assistant-Ingress funktionieren.
BASIS_CSS = """
  :root { --bg:#f6f7f9; --karte:#fff; --text:#1c1f24; --leise:#5f6773; --rand:#d9dde3;
          --gut:#1a7f37; --schlecht:#c2410c; --knopf:#2457c5; --knopftext:#fff; --kachel:#0b0d10; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#111317; --karte:#1b1e24; --text:#e8eaed; --leise:#9aa3ae; --rand:#2e333b;
            --gut:#4ac26b; --schlecht:#f08a4b; --knopf:#5b8cff; --knopftext:#0b0d10; --kachel:#000; }
  }
  * { box-sizing:border-box; }
  [hidden] { display:none !important; }
  body { margin:0; background:var(--bg); color:var(--text);
         font:16px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
  main { max-width:760px; margin:0 auto; padding:20px 16px 40px; }
  header.kopf { display:flex; align-items:baseline; justify-content:space-between; gap:12px; margin:0 0 10px; }
  h1 { font-size:1.35rem; margin:0; }
  h2 { font-size:1.05rem; margin:0 0 8px; }
  nav.sprachen { display:flex; gap:2px; font-size:.85rem; }
  nav.sprachen a { padding:2px 8px; border-radius:6px; border:1px solid transparent; color:var(--leise); text-decoration:none; }
  nav.sprachen a[aria-current="true"] { color:var(--text); border-color:var(--rand); font-weight:600; }
  nav.tabs { display:flex; gap:4px; margin:0 0 14px; border-bottom:1px solid var(--rand); }
  nav.tabs a { padding:8px 12px; color:var(--leise); text-decoration:none;
               border-bottom:2px solid transparent; margin-bottom:-1px; }
  nav.tabs a[aria-current="page"] { color:var(--text); border-bottom-color:var(--knopf); font-weight:600; }
  .chips { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:16px; }
  .chip { border:1px solid var(--rand); border-radius:999px; padding:2px 10px; font-size:.85rem; color:var(--leise); }
  .karte { background:var(--karte); border:1px solid var(--rand); border-radius:10px; padding:14px; margin-bottom:14px; }
  .wert { font-size:1.6rem; font-weight:650; font-variant-numeric:tabular-nums; }
  .gut { color:var(--gut); } .schlecht { color:var(--schlecht); }
  .leise { color:var(--leise); font-size:.9rem; }
  img.bild { display:block; width:100%; height:auto; margin:12px 0; border-radius:6px; background:#000; }
  form { display:flex; flex-wrap:wrap; gap:8px; align-items:end; margin-top:8px; }
  label { flex:1 1 100%; font-size:.9rem; color:var(--leise); }
  input, select { flex:1 1 160px; min-width:0; font:inherit; font-size:1.05rem; padding:8px 10px; border-radius:8px;
          border:1px solid var(--rand); background:var(--bg); color:var(--text); font-variant-numeric:tabular-nums; }
  input[type=file] { font-size:.9rem; }
  button, a.knopf { font:inherit; padding:9px 14px; border-radius:8px; border:1px solid transparent; cursor:pointer;
                    background:var(--knopf); color:var(--knopftext); text-decoration:none; display:inline-block; }
  button.zweit, a.knopf.zweit { background:transparent; color:var(--knopf); border-color:var(--rand); }
  button.gefahr { background:var(--schlecht); color:#fff; border-color:transparent; }
  button:disabled { opacity:.6; cursor:progress; }
  .meldung { min-height:1.5em; margin-top:10px; }
  .zeile { display:flex; gap:8px; flex-wrap:wrap; margin-top:14px; align-items:center; }
"""

_SEITE = """<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wasseruhr-CV</title>
<style>{css}</style>
</head>
<body>
<main>
  {kopf}
  <div class="chips">{chips}</div>
  {inhalt}
</main>
{skript}
</body>
</html>
"""

# Gemeinsamer Anfang der Seitenskripte: Texte der Sprache und t() zum Einsetzen
_VORSPANN = r"""const LANG = "@@LANG@@", T = @@TEXTE@@;
const t = (k, w = {}) => (T[k] ?? k).replace(/\{(\w+)\}/g, (m, n) => n in w ? w[n] : m);
const LOCALE = (navigator.language || "").toLowerCase().startsWith(LANG) ? navigator.language : LANG;
"""

_SKRIPT = """
  document.querySelectorAll("[data-zeit]").forEach(el => {
    el.textContent = new Date(el.dataset.zeit).toLocaleString(LOCALE);
  });
  const form = document.getElementById("lernen");
  form?.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const meldung = document.getElementById("meldung");
    const knopf = form.querySelector("button");
    const wert = form.wert.value.trim().replace(",", ".");
    if (!/^\\d{1,9}(\\.\\d{1,3})?$/.test(wert)) {
      meldung.className = "meldung schlecht"; meldung.textContent = t("format"); return;
    }
    knopf.disabled = true; meldung.className = "meldung leise"; meldung.textContent = t("lerne");
    try {
      const r = await fetch(`lernen?wert=${encodeURIComponent(wert)}&ablesung=${form.dataset.nr}`,
        {method: "POST", headers: {"Accept-Language": LANG}});
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || r.status);
      meldung.className = "meldung gut";
      meldung.textContent = t("gelernt_neu_ablesen", {n: d.gespeichert});
      setTimeout(() => location.href = "./", 900);
    } catch (e) {
      meldung.className = "meldung schlecht"; meldung.textContent = t("fehler", {text: e.message}); knopf.disabled = false;
    }
  });
  const kamera = document.getElementById("kamera");
  kamera?.addEventListener("click", async () => {
    const meldung = document.getElementById("kamera-meldung");
    kamera.disabled = true; meldung.className = "meldung leise"; meldung.textContent = t("hole_bild");
    try {
      const r = await fetch("kamera-ablesen", {method: "POST", headers: {"Accept-Language": LANG}});
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || r.status);
      location.href = `./?nr=${d.nr}`;
    } catch (e) {
      meldung.className = "meldung schlecht"; meldung.textContent = t("fehler", {text: e.message}); kamera.disabled = false;
    }
  });
"""


def skript(sprache: str, code: str) -> str:
    """<script> mit den Texten der Sprache, t() und LOCALE vor dem eigentlichen Code."""
    vorspann = _VORSPANN.replace("@@LANG@@", sprache).replace("@@TEXTE@@", fuer_browser(sprache))
    return f"<script>\n{vorspann}{code}</script>"


def _aktuell(ja: bool, wert: str) -> str:
    return f' aria-current="{wert}"' if ja else ""


def kopf(aktiv: str, verwaltung: bool, sprache: str, abfrage: str = "") -> str:
    """Überschrift mit Sprachumschalter, darunter die Reiter Nachlernen / Verwaltung.
    Die Reiter entfallen, wenn die Verwaltung hier nicht erreichbar ist. `abfrage`
    bleibt beim Umschalten erhalten (z. B. "nr=5&")."""
    umschalter = "".join(
        f'<a href="?{abfrage}sprache={s}" hreflang="{s}" lang="{s}"{_aktuell(s == sprache, "true")}>{s.upper()}</a>'
        for s in SPRACHEN
    )
    html = (
        '<header class="kopf"><h1>Wasseruhr-CV</h1>'
        f'<nav class="sprachen" aria-label="{escape(uebersetzen("seite.sprache", sprache))}">{umschalter}</nav>'
        "</header>"
    )
    if verwaltung:
        reiter = [("./", "seite.nav.lernen", "lernen"), ("admin", "seite.nav.verwaltung", "admin")]
        links = "".join(
            f'<a href="{href}"{_aktuell(name == aktiv, "page")}>{escape(uebersetzen(text, sprache))}</a>'
            for href, text, name in reiter
        )
        html += f'<nav class="tabs">{links}</nav>'
    return html


def rendern(
    *,
    lerneffekt: bool,
    lernbilder: int,
    fehlende: list[int],
    nr: int | None,
    zeit: datetime | None,
    wert: float | None,
    sicher: bool,
    ist_neueste: bool,
    kamera: bool = False,
    verwaltung: bool = True,
    automatik_intervall: int | None = None,
    zaehlerstand: float | None = None,
    sprache: str = STANDARD,
) -> str:
    def tx(schluessel: str, **werte) -> str:
        return uebersetzen(schluessel, sprache, **werte)

    chips = [
        tx("ui.chip.stand", wert=f"{zaehlerstand:.3f}") if zaehlerstand is not None else tx("ui.chip.kein_stand"),
        tx("ui.chip.automatik", n=automatik_intervall) if automatik_intervall else tx("ui.chip.automatik_aus"),
        tx("ui.chip.lerneffekt_an" if lerneffekt else "ui.chip.lerneffekt_aus"),
        tx("ui.chip.lernbilder_1" if lernbilder == 1 else "ui.chip.lernbilder_n", n=lernbilder),
        tx("ui.chip.fehlend", liste=", ".join(map(str, fehlende))) if fehlende else tx("ui.chip.alle"),
    ]
    chips_html = "".join(f'<span class="chip">{escape(c)}</span>' for c in chips)
    kamera_knopf = (
        f'<button type="button" id="kamera" class="zweit">{escape(tx("ui.kamera_jetzt"))}</button>' if kamera else ""
    )
    seite = dict(
        lang=sprache, css=BASIS_CSS, chips=chips_html, skript=skript(sprache, _SKRIPT),
        kopf=kopf("lernen", verwaltung, sprache, f"nr={nr}&" if nr is not None else ""),
    )

    if nr is None:
        hinweis = (
            tx("lern.hinweis.automatik_html", n=automatik_intervall) if automatik_intervall
            else tx("lern.hinweis.kamera_html") if kamera
            else tx("lern.hinweis.keine_kamera_html") if verwaltung
            else escape(tx("lern.hinweis.keine_kamera_option"))
        )
        inhalt = (
            f'<div class="karte"><p>{escape(tx("lern.leer"))} {hinweis}</p>'
            f'<div class="zeile">{kamera_knopf}<a class="knopf zweit" href="./">{escape(tx("lern.neu_laden"))}</a></div>'
            '<div id="kamera-meldung" class="meldung leise"></div></div>'
        )
        return _SEITE.format(inhalt=inhalt, **seite)

    wert_text = "–" if wert is None else f"{wert:.3f}"
    urteil = (
        f'<span class="gut">{escape(tx("ui.sicher"))}</span>' if sicher
        else f'<span class="schlecht">{escape(tx("ui.unsicher"))}</span>'
    )
    hinweis_alt = "" if ist_neueste else f'<p class="leise">{escape(tx("lern.neuere"))}</p>'
    hinweis_aus = "" if lerneffekt else f'<p class="leise">{escape(tx("lern.lerneffekt_aus"))}</p>'
    inhalt = f"""<div class="karte">
    <div class="leise">{escape(tx("lern.ablesung", nr=nr))} · <span data-zeit="{escape(zeit.isoformat())}"></span></div>
    <div><span class="wert">{wert_text}</span> m³ · {urteil}</div>
    {hinweis_alt}
    <img class="bild" src="debug.png?nr={nr}" alt="{escape(tx("lern.bild_alt"))}">
    <form id="lernen" data-nr="{nr}" autocomplete="off">
      <label for="wert">{escape(tx("lern.label"))}</label>
      <input id="wert" name="wert" inputmode="decimal" value="{'' if wert is None else wert_text}" placeholder="506.388">
      <button type="submit">{escape(tx("lern.knopf"))}</button>
    </form>
    <div id="meldung" class="meldung leise"></div>
    {hinweis_aus}
  </div>
  <div class="zeile"><a class="knopf zweit" href="./">{escape(tx("lern.neueste"))}</a>{kamera_knopf}</div>
  <div id="kamera-meldung" class="meldung leise"></div>"""
    return _SEITE.format(inhalt=inhalt, **seite)
