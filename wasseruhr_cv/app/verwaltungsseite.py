"""Verwaltungsseite (GET /admin): statisches HTML, die Daten kommen per fetch
aus /admin/… . Alle Pfade sind relativ zur Seite <basis>/admin, damit alles
auch hinter dem Home-Assistant-Ingress (/api/hassio_ingress/<token>/) läuft."""

from __future__ import annotations

from .lernseite import BASIS_CSS, navigation

_CSS = """
  .liste { list-style:none; margin:0; padding:0; }
  .liste li { display:flex; flex-wrap:wrap; gap:4px 12px; align-items:baseline; padding:7px 0; border-top:1px solid var(--rand); }
  .liste li:first-child { border-top:0; }
  .liste a { color:var(--knopf); text-decoration:none; font-weight:600; }
  .num { font-variant-numeric:tabular-nums; font-weight:600; }
  .ziffer-zeile { display:flex; gap:10px; align-items:flex-start; padding:8px 0; border-top:1px solid var(--rand); }
  .ziffer-zeile:first-child { border-top:0; }
  .ziffer-kopf { flex:0 0 40px; font-size:1.4rem; font-weight:650; line-height:1; }
  .ziffer-kopf small { display:block; font-size:.75rem; font-weight:400; color:var(--leise); margin-top:4px; }
  .kacheln { display:flex; flex-wrap:wrap; gap:4px; min-width:0; }
  .kacheln img { width:36px; height:60px; image-rendering:pixelated; border-radius:3px; background:var(--kachel); cursor:pointer; }
  .kacheln .leer { color:var(--schlecht); font-size:.9rem; }
  .lernbild { padding:12px 0; border-top:1px solid var(--rand); }
  .lernbild:first-child { border-top:0; }
  .lernbild img { display:block; width:100%; max-width:440px; height:auto; border-radius:6px; background:#000; margin-bottom:6px; }
  .lernbild.markiert { outline:2px solid var(--knopf); outline-offset:6px; border-radius:6px; }
  .lernbild input { flex:0 1 150px; }
  dl.einstellungen { display:grid; grid-template-columns:max-content minmax(0,1fr); gap:4px 14px; margin:0; }
  dl.einstellungen dt { color:var(--leise); font-size:.9rem; }
  dl.einstellungen dd { margin:0; font-variant-numeric:tabular-nums; overflow-wrap:anywhere; }
  section > p.leise:first-of-type { margin-top:0; }
  #m-laden:empty { display:none; }
"""

_SKRIPT = r"""<script>
const $ = (sel) => document.querySelector(sel);
const WERT_MUSTER = /^\d{1,9}([.,]\d{1,3})?$/;
const SEITE_GROESSE = 30;
let info = null, alleLernbilder = [], zeigeAlle = false;

function el(tag, attrs = {}, ...kinder) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) e.setAttribute(k, v === true ? "" : v);
  }
  for (const kind of kinder) if (kind != null) e.append(kind);
  return e;
}
async function api(pfad, optionen = {}) {
  const r = await fetch(pfad, optionen);
  const d = (r.headers.get("content-type") || "").includes("json") ? await r.json() : null;
  if (!r.ok) throw new Error((d && d.detail) || `HTTP ${r.status}`);
  return d;
}
function melden(id, text, art = "leise") {
  const m = document.getElementById(id); m.className = `meldung ${art}`; m.textContent = text;
}
const zeit = (iso) => new Date(iso).toLocaleString("de-DE", {dateStyle: "medium", timeStyle: "short"});
const m3 = (w) => w == null ? "–" : Number(w).toFixed(3);
const punkt = (w) => w.trim().replace(",", ".");
function stempelZeit(zs) {
  const m = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})/.exec(zs);
  return m ? new Date(Date.UTC(+m[1], m[2] - 1, +m[3], +m[4], +m[5], +m[6])).toISOString() : null;
}
// Zwei-Klick-Bestätigung ohne Browser-Dialog (funktioniert auch im HA-Rahmen)
function bestaetigt(knopf, frage) {
  if (knopf.dataset.scharf) { clearTimeout(knopf._t); entschaerfen(knopf); return true; }
  knopf.dataset.scharf = "1"; knopf.dataset.text = knopf.textContent; knopf.dataset.klasse = knopf.className;
  knopf.textContent = frage; knopf.className = "gefahr";
  knopf._t = setTimeout(() => entschaerfen(knopf), 4000);
  return false;
}
function entschaerfen(knopf) {
  if (!knopf.dataset.scharf) return;
  delete knopf.dataset.scharf; knopf.textContent = knopf.dataset.text; knopf.className = knopf.dataset.klasse;
}
async function allesLaden() {
  await Promise.all([ladeInfo(), ladeAblesungen(), ladeVorlagen(), ladeLernbilder()]);
}

// ---- Übersicht & Einstellungen ------------------------------------------------
async function ladeInfo() {
  info = await api("admin/info");
  const vorlagen = Object.values(info.vorlagen_pro_ziffer).reduce((a, b) => a + b, 0);
  const chips = [
    `Version ${info.version}`,
    `Lerneffekt ${info.lerneffekt ? "an" : "aus"}`,
    `${info.lernbilder} Lernbild${info.lernbilder === 1 ? "" : "er"}`,
    `${vorlagen} Vorlagen`,
    info.fehlende_vorlagen.length ? `Ziffern ohne Vorlage: ${info.fehlende_vorlagen.join(", ")}` : "alle Ziffern 0–9 gelernt",
  ];
  const e = info.erstausstattung;
  if (e && e.uebernommen) chips.push(`mitgeliefertes Modell übernommen am ${zeit(e.zeit)}`);
  $("#chips").replaceChildren(...chips.map(c => el("span", {class: "chip", text: c})));
  $("#leer-hinweis").hidden = info.lernbilder > 0 || vorlagen > 0;

  $("#kamera").hidden = !info.kamera_bereit;
  $("#kamera-hinweis").textContent = info.kamera_bereit ? "" : info.kamera
    ? `Kamera ${info.kamera} ist eingestellt, aber es gibt keinen Zugang zu Home Assistant (HA_URL/HA_TOKEN).`
    : "Tipp: Mit eingestellter Kamera-Entität (Option kamera) gibt es hier „Kamera jetzt ablesen“.";

  const s = info.einstellungen;
  const zeilen = [
    ["Lerneffekt", info.lerneffekt ? "an" : "aus (Vorlagen eingefroren)"],
    ["Mindest-Score", s.MIN_SCORE],
    ["Mindestabstand", s.MIN_ABSTAND],
    ["Vorlagen je Ziffer", `höchstens ${s.MAX_VORLAGEN_PRO_ZIFFER}`],
    ["Verschiebung", `±${s.VERSCHIEBUNG} px`],
    ["Kamera", info.kamera || "–"],
    ["Verwaltung", s.ADMIN_NUR_INGRESS ? "nur über Home Assistant" : "im ganzen Heimnetz"],
    ["ROIs", el("code", {text: JSON.stringify(s.ROIS)})],
  ];
  $("#einstellungen").replaceChildren(...zeilen.flatMap(([k, v]) => [el("dt", {text: k}), el("dd", {}, typeof v === "object" ? v : String(v))]));
  $("#einstellungen-hinweis").textContent = info.addon
    ? "Ändern unter Einstellungen → Add-ons → Wasseruhr-CV → Konfiguration. Beim Speichern startet das Add-on neu."
    : "Ändern über die Umgebungsvariablen in docker-compose.yml, danach docker compose up -d.";
}

// ---- Letzte Ablesungen --------------------------------------------------------
async function ladeAblesungen() {
  const liste = await api("admin/ablesungen");
  $("#ablesungen").replaceChildren(...(liste.length ? liste.map(a => el("li", {},
    el("a", {href: `./?nr=${a.nr}`, text: `#${a.nr}`}),
    el("span", {class: "num", text: `${m3(a.wert)} m³`}),
    el("span", {class: a.sicher ? "gut" : "schlecht", text: a.sicher ? "sicher" : "unsicher"}),
    el("span", {class: "leise", text: zeit(a.zeit)}),
  )) : [el("li", {class: "leise", text: "Seit dem Start noch keine Ablesung."})]));
}

// ---- Vorlagen -----------------------------------------------------------------
async function ladeVorlagen() {
  const daten = await api("admin/vorlagen");
  $("#vorlagen").replaceChildren(...Object.entries(daten).map(([ziffer, liste]) =>
    el("div", {class: "ziffer-zeile"},
      el("div", {class: "ziffer-kopf"}, ziffer, el("small", {text: `${liste.length}×`})),
      el("div", {class: "kacheln"}, ...(liste.length ? liste.map(v => {
        const [zs, rolle] = v.name.replace(/\.png$/, "").split("_r");
        const wann = stempelZeit(zs);
        return el("img", {
          src: `data:image/png;base64,${v.png}`, alt: `Vorlage ${ziffer}`,
          title: `Rolle ${rolle}${wann ? ` · Lernbild vom ${zeit(wann)}` : ""} – antippen zeigt das Lernbild`,
          onclick: () => zeigeLernbild(zs),
        });
      }) : [el("span", {class: "leer", text: "keine Vorlage – diese Ziffer nachlernen"})]))
    )));
}
function zeigeLernbild(zeitstempel) {
  const i = alleLernbilder.findIndex(lb => lb.zeitstempel === zeitstempel);
  if (i < 0) { melden("m-vorlagen", "Zu dieser Vorlage gibt es kein Lernbild mehr.", "schlecht"); return; }
  if (i >= SEITE_GROESSE && !zeigeAlle) { zeigeAlle = true; renderLernbilder(); }
  const karte = document.getElementById(`lb-${zeitstempel}`);
  karte.scrollIntoView({behavior: "smooth", block: "center"});
  karte.classList.add("markiert");
  setTimeout(() => karte.classList.remove("markiert"), 2500);
}
$("#neu-aufbauen").addEventListener("click", async (ev) => {
  const knopf = ev.currentTarget;
  if (!info.lerneffekt && !bestaetigt(knopf, "Lerneffekt ist aus – trotzdem neu aufbauen?")) return;
  knopf.disabled = true; melden("m-vorlagen", "Baue Vorlagen aus allen Lernbildern neu auf …");
  try {
    await api("admin/neu-aufbauen", {method: "POST"});
    melden("m-vorlagen", "Vorlagen neu aufgebaut.", "gut");
    await Promise.all([ladeInfo(), ladeVorlagen()]);
  } catch (e) { melden("m-vorlagen", "Fehler: " + e.message, "schlecht"); }
  knopf.disabled = false;
});

// ---- Lernbilder ---------------------------------------------------------------
async function ladeLernbilder() {
  alleLernbilder = await api("admin/lernbilder");
  renderLernbilder();
}
function renderLernbilder() {
  const sichtbar = zeigeAlle ? alleLernbilder : alleLernbilder.slice(0, SEITE_GROESSE);
  $("#lb-anzahl").textContent = `(${alleLernbilder.length})`;
  const mehr = $("#mehr");
  mehr.hidden = zeigeAlle || alleLernbilder.length <= SEITE_GROESSE;
  mehr.textContent = `Alle ${alleLernbilder.length} anzeigen`;
  $("#lernbilder").replaceChildren(...(sichtbar.length ? sichtbar.map(lernbildKarte)
    : [el("p", {class: "leise", text: "Noch keine Lernbilder."})]));
}
function lernbildKarte(lb) {
  const pfad = `admin/lernbilder/${encodeURIComponent(lb.name)}`;
  const eingabe = el("input", {name: "wert", inputmode: "decimal", value: m3(lb.wert), "aria-label": "Zählerstand in m³"});
  const speichern = el("button", {type: "submit", class: "zweit", text: "Wert speichern"});
  const loeschen = el("button", {type: "button", class: "zweit", text: "Löschen"});
  const meldung = el("div", {class: "meldung leise"});
  const fehler = (e, knopf) => { meldung.className = "meldung schlecht"; meldung.textContent = "Fehler: " + e.message; knopf.disabled = false; };
  const form = el("form", {autocomplete: "off"}, eingabe, speichern, loeschen);
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!WERT_MUSTER.test(eingabe.value.trim())) { fehler(new Error("bitte im Format 506.388 eingeben"), speichern); return; }
    speichern.disabled = true;
    try {
      const d = await api(`${pfad}/wert?wert=${encodeURIComponent(punkt(eingabe.value))}`, {method: "POST"});
      await nachAenderung(d, `Wert auf ${m3(punkt(eingabe.value))} geändert`);
    } catch (e) { fehler(e, speichern); }
  });
  loeschen.addEventListener("click", async () => {
    if (!bestaetigt(loeschen, "Wirklich löschen?")) return;
    loeschen.disabled = true;
    try { await nachAenderung(await api(`${pfad}/loeschen`, {method: "POST"}), "Lernbild gelöscht"); }
    catch (e) { fehler(e, loeschen); }
  });
  return el("div", {class: "lernbild", id: `lb-${lb.zeitstempel}`},
    el("a", {href: pfad, target: "_blank", rel: "noopener", title: "Ganzes Bild öffnen"},
      el("img", {src: `${pfad}?ausschnitt=1`, alt: `Zählwerk, gelernt als ${m3(lb.wert)}`, loading: "lazy"})),
    el("div", {}, el("span", {class: "num", text: `${m3(lb.wert)} m³`}), el("span", {class: "leise", text: ` · ${zeit(lb.zeit)}`})),
    form, meldung);
}
async function nachAenderung(d, text) {
  const zusatz = d.vorlagen_neu_aufgebaut ? "Vorlagen neu aufgebaut." : "Lerneffekt aus: Vorlagen unverändert.";
  melden("m-lernbilder", `${text}. ${zusatz}`, "gut");
  await Promise.all([ladeInfo(), ladeVorlagen(), ladeLernbilder()]);
}
$("#mehr").addEventListener("click", () => { zeigeAlle = true; renderLernbilder(); });

// ---- Nachlernen ---------------------------------------------------------------
$("#kamera").addEventListener("click", async (ev) => {
  const knopf = ev.currentTarget;
  knopf.disabled = true; melden("m-nachlernen", "Hole Kamerabild …");
  try { const d = await api("kamera-ablesen", {method: "POST"}); location.href = `./?nr=${d.nr}`; }
  catch (e) { melden("m-nachlernen", "Fehler: " + e.message, "schlecht"); knopf.disabled = false; }
});
$("#upload").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.currentTarget, knopf = f.querySelector("button"), datei = f.datei.files[0];
  if (!datei) { melden("m-nachlernen", "Bitte ein Bild auswählen.", "schlecht"); return; }
  if (!WERT_MUSTER.test(f.wert.value.trim())) { melden("m-nachlernen", "Bitte den Wert im Format 506.388 eingeben.", "schlecht"); return; }
  knopf.disabled = true; melden("m-nachlernen", "Lerne …");
  try {
    const d = await api(`lernen?wert=${encodeURIComponent(punkt(f.wert.value))}`,
      {method: "POST", headers: {"Content-Type": datei.type || "image/jpeg"}, body: datei});
    melden("m-nachlernen", `Gelernt: ${d.gespeichert} neue Vorlage(n).`, "gut");
    f.reset();
    await Promise.all([ladeInfo(), ladeVorlagen(), ladeLernbilder()]);
  } catch (e) { melden("m-nachlernen", "Fehler: " + e.message, "schlecht"); }
  knopf.disabled = false;
});

// ---- Export & Import ----------------------------------------------------------
$("#import").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.currentTarget, knopf = f.querySelector("button"), datei = f.datei.files[0], modus = f.modus.value;
  if (!datei) { melden("m-import", "Bitte eine ZIP-Datei auswählen.", "schlecht"); return; }
  if (modus === "ersetzen" && !bestaetigt(knopf, "Alles Vorhandene ersetzen?")) return;
  knopf.disabled = true; melden("m-import", "Importiere …");
  try {
    const d = await api(`admin/import?modus=${modus}`,
      {method: "POST", headers: {"Content-Type": "application/zip"}, body: datei});
    const teile = [modus === "ersetzen" ? `${d.lernbilder_neu} Lernbilder übernommen` : `${d.lernbilder_neu} neue Lernbilder`];
    if (d.uebersprungen) teile.push(`${d.uebersprungen} Dateien übersprungen`);
    teile.push(d.vorlagen_neu_aufgebaut ? "Vorlagen neu aufgebaut"
      : modus === "ersetzen" ? "Vorlagen aus dem ZIP übernommen" : "Vorlagen unverändert");
    melden("m-import", teile.join(" · "), "gut");
    f.reset();
    await allesLaden();
  } catch (e) { melden("m-import", "Fehler: " + e.message, "schlecht"); }
  knopf.disabled = false;
});

allesLaden().catch(e => melden("m-laden", "Fehler beim Laden: " + e.message, "schlecht"));
</script>"""

_HTML = """<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wasseruhr-CV · Verwaltung</title>
<style>@@CSS@@</style>
</head>
<body>
<main>
  <h1>Wasseruhr-CV</h1>
  @@NAV@@
  <div class="chips" id="chips"></div>
  <div id="m-laden" class="meldung"></div>

  <section class="karte" id="leer-hinweis" hidden>
    <h2>Noch kein Modell</h2>
    <p class="leise">Ein vorhandenes Modell (ZIP) unten unter „Sichern &amp; übertragen“ importieren,
      oder auf der Lernseite Kamerabilder mit dem richtigen Zählerstand anlernen, bis jede Ziffer 0–9
      einmal gelernt ist. Sitzt die Kamera anders als beim Standard, zuerst die ROIs einstellen.</p>
    <div class="zeile"><a class="knopf" href="#import-karte">Modell importieren</a>
      <a class="knopf zweit" href="./">Zur Lernseite</a></div>
  </section>

  <section class="karte">
    <h2>Nachlernen</h2>
    <div class="zeile" style="margin-top:0">
      <button type="button" id="kamera" hidden>Kamera jetzt ablesen</button>
      <a class="knopf zweit" href="./">Letzte Ablesung prüfen</a>
    </div>
    <p class="leise" id="kamera-hinweis"></p>
    <form id="upload" autocomplete="off">
      <label>Eigenes Bild mit bekanntem Zählerstand lernen</label>
      <input type="file" name="datei" accept="image/jpeg,image/png">
      <input name="wert" inputmode="decimal" placeholder="506.388" aria-label="Zählerstand in m³">
      <button type="submit">Lernen</button>
    </form>
    <div id="m-nachlernen" class="meldung"></div>
  </section>

  <section class="karte">
    <h2>Letzte Ablesungen</h2>
    <p class="leise">Die letzten 20 seit dem Start. Die Nummer öffnet die Ablesung auf der Lernseite.</p>
    <ul class="liste" id="ablesungen"></ul>
  </section>

  <section class="karte">
    <h2>Vorlagen</h2>
    <p class="leise">So sieht der Matcher jede gelernte Ziffer. Passt eine Kachel nicht in ihre Zeile,
      stammt sie aus einem falsch gelernten Bild: Kachel antippen, das Lernbild unten korrigieren oder löschen.</p>
    <div id="vorlagen"></div>
    <div class="zeile"><button type="button" class="zweit" id="neu-aufbauen">Vorlagen aus Lernbildern neu aufbauen</button></div>
    <div id="m-vorlagen" class="meldung"></div>
  </section>

  <section class="karte">
    <h2>Lernbilder <span id="lb-anzahl" class="leise"></span></h2>
    <p class="leise">Neueste zuerst, gezeigt wird das Zählwerk. Stimmt ein Wert nicht, korrigieren oder löschen.
      Mit Lerneffekt werden die Vorlagen danach sofort neu aufgebaut.</p>
    <div id="m-lernbilder" class="meldung"></div>
    <div id="lernbilder"></div>
    <div class="zeile"><button type="button" class="zweit" id="mehr" hidden></button></div>
  </section>

  <section class="karte" id="import-karte">
    <h2>Sichern &amp; übertragen</h2>
    <p class="leise">Das Modell besteht aus allen Lernbildern und Vorlagen. Es steckt auch in jeder
      Home-Assistant-Datensicherung des Add-ons. Ein Export lässt sich zwischen Add-on und Docker hin- und herschieben.</p>
    <div class="zeile" style="margin-top:0"><a class="knopf" href="admin/export.zip" download>Modell exportieren (ZIP)</a></div>
    <form id="import" autocomplete="off">
      <label>Modell importieren: Export aus der Verwaltung oder ZIP des data-Ordners</label>
      <input type="file" name="datei" accept=".zip,application/zip">
      <select name="modus" aria-label="Importmodus">
        <option value="ergaenzen">ergänzen: nur neue Lernbilder</option>
        <option value="ersetzen">ersetzen: Vorhandenes löschen</option>
      </select>
      <button type="submit">Importieren</button>
    </form>
    <div id="m-import" class="meldung"></div>
  </section>

  <section class="karte">
    <h2>Einstellungen</h2>
    <dl class="einstellungen" id="einstellungen"></dl>
    <p class="leise" id="einstellungen-hinweis"></p>
  </section>
</main>
@@SKRIPT@@
</body>
</html>
"""

SEITE = (
    _HTML.replace("@@CSS@@", BASIS_CSS + _CSS)
    .replace("@@NAV@@", navigation("admin", True))
    .replace("@@SKRIPT@@", _SKRIPT)
)
