"""Kleine Lernseite (GET /): letztes Kamerabild ansehen, richtigen Wert eintippen, lernen."""

from __future__ import annotations

from datetime import datetime
from html import escape

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
  h1 { font-size:1.35rem; margin:0 0 10px; }
  h2 { font-size:1.05rem; margin:0 0 8px; }
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
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wasseruhr-CV</title>
<style>{css}</style>
</head>
<body>
<main>
  <h1>Wasseruhr-CV</h1>
  {navigation}
  <div class="chips">{chips}</div>
  {inhalt}
</main>
{skript}
</body>
</html>
"""

_SKRIPT = """<script>
  document.querySelectorAll("[data-zeit]").forEach(el => {
    el.textContent = new Date(el.dataset.zeit).toLocaleString("de-DE");
  });
  const form = document.getElementById("lernen");
  form?.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const meldung = document.getElementById("meldung");
    const knopf = form.querySelector("button");
    const wert = form.wert.value.trim().replace(",", ".");
    if (!/^\\d{1,9}(\\.\\d{1,3})?$/.test(wert)) {
      meldung.className = "meldung schlecht"; meldung.textContent = "Bitte im Format 506.388 eingeben."; return;
    }
    knopf.disabled = true; meldung.className = "meldung leise"; meldung.textContent = "Lerne …";
    try {
      const r = await fetch(`lernen?wert=${encodeURIComponent(wert)}&ablesung=${form.dataset.nr}`, {method: "POST"});
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || r.status);
      meldung.className = "meldung gut";
      meldung.textContent = `Gelernt: ${d.gespeichert} neue Vorlage(n). Bild wird neu abgelesen …`;
      setTimeout(() => location.href = "./", 900);
    } catch (e) {
      meldung.className = "meldung schlecht"; meldung.textContent = "Fehler: " + e.message; knopf.disabled = false;
    }
  });
  const kamera = document.getElementById("kamera");
  kamera?.addEventListener("click", async () => {
    const meldung = document.getElementById("kamera-meldung");
    kamera.disabled = true; meldung.className = "meldung leise"; meldung.textContent = "Hole Kamerabild …";
    try {
      const r = await fetch("kamera-ablesen", {method: "POST"});
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || r.status);
      location.href = `./?nr=${d.nr}`;
    } catch (e) {
      meldung.className = "meldung schlecht"; meldung.textContent = "Fehler: " + e.message; kamera.disabled = false;
    }
  });
</script>"""


def navigation(aktiv: str, verwaltung: bool) -> str:
    """Reiter Nachlernen / Verwaltung – entfällt, wenn die Verwaltung hier nicht erreichbar ist."""
    if not verwaltung:
        return ""
    reiter = [("./", "Nachlernen", "lernen"), ("admin", "Verwaltung", "admin")]
    aktuell = ' aria-current="page"'
    links = "".join(
        f'<a href="{href}"{aktuell if name == aktiv else ""}>{text}</a>' for href, text, name in reiter
    )
    return f'<nav class="tabs">{links}</nav>'


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
) -> str:
    chips = [
        f"Lerneffekt {'an' if lerneffekt else 'aus'}",
        f"{lernbilder} Lernbild{'er' if lernbilder != 1 else ''}",
        f"Ziffern ohne Vorlage: {', '.join(map(str, fehlende))}" if fehlende else "alle Ziffern 0–9 gelernt",
    ]
    chips_html = "".join(f'<span class="chip">{escape(c)}</span>' for c in chips)
    kamera_knopf = (
        '<button type="button" id="kamera" class="zweit">Kamera jetzt ablesen</button>' if kamera else ""
    )
    seite = dict(css=BASIS_CSS, navigation=navigation("lernen", verwaltung), chips=chips_html, skript=_SKRIPT)

    if nr is None:
        hinweis = (
            "Mit <b>Kamera jetzt ablesen</b> holt sich der Dienst selbst ein Bild." if kamera
            else "Sobald Node-RED das nächste Kamerabild an <code>/ablesen</code> schickt, erscheint es hier."
        )
        inhalt = (
            f'<div class="karte"><p>Noch kein Bild abgelesen. {hinweis}</p>'
            f'<div class="zeile">{kamera_knopf}<a class="knopf zweit" href="./">Neu laden</a></div>'
            '<div id="kamera-meldung" class="meldung leise"></div></div>'
        )
        return _SEITE.format(inhalt=inhalt, **seite)

    wert_text = "–" if wert is None else f"{wert:.3f}"
    urteil = '<span class="gut">sicher</span>' if sicher else '<span class="schlecht">unsicher</span>'
    hinweis_alt = (
        "" if ist_neueste
        else '<p class="leise">Inzwischen gibt es eine neuere Ablesung – gelernt wird trotzdem genau dieses Bild.</p>'
    )
    hinweis_aus = (
        '<p class="leise">Lerneffekt ist aus: Das Bild wird nur archiviert und beim nächsten Start '
        "mit Lerneffekt gelernt.</p>" if not lerneffekt else ""
    )
    inhalt = f"""<div class="karte">
    <div class="leise">Ablesung #{nr} · <span data-zeit="{escape(zeit.isoformat())}"></span></div>
    <div><span class="wert">{wert_text}</span> m³ · {urteil}</div>
    {hinweis_alt}
    <img class="bild" src="debug.png?nr={nr}" alt="Kamerabild mit ROIs und aufbereiteten Ziffern">
    <form id="lernen" data-nr="{nr}" autocomplete="off">
      <label for="wert">Richtiger Zählerstand auf diesem Bild (m³, 3 Nachkommastellen)</label>
      <input id="wert" name="wert" inputmode="decimal" value="{'' if wert is None else wert_text}" placeholder="506.388">
      <button type="submit">Mit diesem Bild lernen</button>
    </form>
    <div id="meldung" class="meldung leise"></div>
    {hinweis_aus}
  </div>
  <div class="zeile"><a class="knopf zweit" href="./">Neueste Ablesung</a>{kamera_knopf}</div>
  <div id="kamera-meldung" class="meldung leise"></div>"""
    return _SEITE.format(inhalt=inhalt, **seite)
