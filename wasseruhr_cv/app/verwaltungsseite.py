"""Verwaltungsseite (GET /admin): HTML je Sprache, die Daten kommen per fetch
aus /admin/… . Alle Pfade sind relativ zur Seite <basis>/admin, damit alles
auch hinter dem Home-Assistant-Ingress (/api/hassio_ingress/<token>/) läuft.

Texte: {{schlüssel}} im HTML wird beim Erzeugen übersetzt (escaped, außer
Schlüssel auf _html), das Skript holt sich seine Texte mit t() aus den
"ui."-Schlüsseln (siehe sprache.py)."""

from __future__ import annotations

import re
from functools import lru_cache
from html import escape

from .lernseite import BASIS_CSS, kopf, skript
from .sprache import SPRACHEN, uebersetzen

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

# Das Skript wird so an den Browser ausgeliefert – Kommentare darin deshalb englisch.
_SKRIPT = r"""
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
  optionen.headers = {"Accept-Language": LANG, ...(optionen.headers || {})};
  const r = await fetch(pfad, optionen);
  const d = (r.headers.get("content-type") || "").includes("json") ? await r.json() : null;
  if (!r.ok) throw new Error((d && d.detail) || `HTTP ${r.status}`);
  return d;
}
function melden(id, text, art = "leise") {
  const m = document.getElementById(id); m.className = `meldung ${art}`; m.textContent = text;
}
const fehler = (e) => t("fehler", {text: e.message});
const zeit = (iso) => new Date(iso).toLocaleString(LOCALE, {dateStyle: "medium", timeStyle: "short"});
const m3 = (w) => w == null ? "–" : Number(w).toFixed(3);
const punkt = (w) => w.trim().replace(",", ".");
const anAus = (b) => t(b ? "an" : "aus");
const mehrzahl = (schluessel, n) => t(`${schluessel}_${n === 1 ? "1" : "n"}`, {n});
const statusText = (l) => `${t("status." + l.status)}${l.grund ? " – " + l.grund : ""}`;
function stempelZeit(zs) {
  const m = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})/.exec(zs);
  return m ? new Date(Date.UTC(+m[1], m[2] - 1, +m[3], +m[4], +m[5], +m[6])).toISOString() : null;
}
// Two-click confirmation without a browser dialog (also works inside the HA frame)
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

// ---- Overview & settings -------------------------------------------------------
async function ladeInfo() {
  info = await api("admin/info");
  const vorlagen = Object.values(info.vorlagen_pro_ziffer).reduce((a, b) => a + b, 0);
  const chips = [
    t("chip.version", {version: info.version}),
    t(info.lerneffekt ? "chip.lerneffekt_an" : "chip.lerneffekt_aus"),
    mehrzahl("chip.lernbilder", info.lernbilder),
    mehrzahl("chip.vorlagen", vorlagen),
    info.fehlende_vorlagen.length ? t("chip.fehlend", {liste: info.fehlende_vorlagen.join(", ")}) : t("chip.alle"),
  ];
  const e = info.erstausstattung;
  if (e && e.uebernommen) chips.push(t("chip.modell_uebernommen", {zeit: zeit(e.zeit)}));
  $("#chips").replaceChildren(...chips.map(c => el("span", {class: "chip", text: c})));
  $("#leer-hinweis").hidden = info.lernbilder > 0 || vorlagen > 0;

  $("#kamera").hidden = !info.kamera_bereit;
  $("#kamera-hinweis").textContent = info.kamera_bereit ? ""
    : info.kamera ? t("kamera.ohne_ha", {kamera: info.kamera}) : t("kamera.tipp");

  const s = info.einstellungen;
  const zeilen = [
    [t("e.lerneffekt"), info.lerneffekt ? t("an") : t("e.eingefroren")],
    [t("e.min_score"), s.MIN_SCORE],
    [t("e.min_abstand"), s.MIN_ABSTAND],
    [t("e.max_vorlagen"), t("e.hoechstens", {n: s.MAX_VORLAGEN_PRO_ZIFFER})],
    [t("e.verschiebung"), `±${s.VERSCHIEBUNG} px`],
    [t("e.kamera"), info.kamera || "–"],
    [t("e.verwaltung"), t(s.ADMIN_NUR_INGRESS ? "e.nur_ha" : "e.heimnetz")],
    [t("e.http"), anAus(s.HTTP)],
    [t("e.https"), anAus(s.HTTPS)],
    [t("e.sprache"), t("e.sprache_" + s.SPRACHE)],
    ["ROIs", el("code", {text: JSON.stringify(s.ROIS)})],
  ];
  zeigeAutomatik(info.automatik);
  ladeKameras();
  $("#einstellungen").replaceChildren(...zeilen.flatMap(([k, v]) => [el("dt", {text: k}), el("dd", {}, typeof v === "object" ? v : String(v))]));
  $("#einstellungen-hinweis").textContent = t(info.addon ? "e.hinweis_addon" : "e.hinweis_docker");
}

// ---- Automatic reading ---------------------------------------------------------
function zeigeAutomatik(a) {
  const l = a.letzter;
  const helfer = a.input_number ? a.input_number + (a.input_number_fehlt ? t("a.helfer_fehlt") : "") : null;
  const ziele = [a.sensor, helfer].filter(Boolean).join(", ") || t("a.keine_ziele");
  const status = a.aktiv ? t("a.liest", {n: a.intervall_minuten})
    : a.intervall_minuten === 0 ? t("a.aus_intervall") : !a.kamera ? t("a.aus_kamera") : t("a.aus_ha");
  const zeilen = [
    [t("a.status"), status],
    [t("e.kamera"), a.kamera || "–"],
    [t("a.ziele"), ziele],
    [t("a.stand"), a.zaehlerstand == null ? t("a.kein_stand")
      : t("a.stand_wert", {wert: m3(a.zaehlerstand), zeit: zeit(a.zaehlerstand_zeit)})],
    [t("a.letzte"), l ? `${zeit(l.zeit)}: ${statusText(l)}` : t("a.keine_pruefung")],
  ];
  if (l && l.uebertragen && l.uebertragen !== "ok") zeilen.push([t("a.uebertragen"), t("a.fehlgeschlagen", {text: l.uebertragen})]);
  $("#automatik").replaceChildren(...zeilen.flatMap(([k, v]) => [el("dt", {text: k}), el("dd", {text: v})]));
  $("#jetzt").hidden = !a.kamera;
}
let kameraGeladen = false;
async function ladeKameras() {
  if (kameraGeladen || !info || !info.kamera_bereit && !info.ha_zugang) return;
  kameraGeladen = true;
  let d;
  try { d = await api("admin/kameras"); }
  catch (e) { melden("m-automatik", t("kameras_fehler", {text: e.message}), "schlecht"); return; }
  const liste = $("#kamera-liste");
  liste.replaceChildren(
    el("option", {value: "", text: d.kameras.length ? t("kamera.waehlen") : t("kamera.keine")}),
    ...d.kameras.map(k => el("option", {value: k.entity_id, selected: k.entity_id === d.aktuell,
      text: `${k.name} (${k.entity_id})${k.state === "unavailable" ? t("kamera.nicht_verfuegbar") : ""}`})));
  $("#kamera-wahl").hidden = false;
  $("#kamera-wahl").dataset.speichern = d.speichern_moeglich ? "1" : "";
  if (d.aktuell) zeigeVorschau(d.aktuell);
}
function zeigeVorschau(entity) {
  const bild = $("#kamera-vorschau");
  if (!entity) { bild.hidden = true; return; }
  bild.onerror = () => { bild.hidden = true; melden("m-automatik", t("kamera.kein_bild", {entity}), "schlecht"); };
  bild.onload = () => { bild.hidden = false; };
  bild.src = `admin/kameras/${encodeURIComponent(entity)}/bild?t=${Date.now()}`;
}
$("#kamera-liste").addEventListener("change", (ev) => zeigeVorschau(ev.currentTarget.value));
$("#kamera-wahl").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.currentTarget, knopf = f.querySelector("button"), entity = f.kamera.value;
  if (!entity) { melden("m-automatik", t("kamera.bitte_waehlen"), "schlecht"); return; }
  if (!f.dataset.speichern) { melden("m-automatik", t("kamera.variable", {entity}), "schlecht"); return; }
  knopf.disabled = true; melden("m-automatik", t("kamera.speichere"));
  try {
    await api(`admin/kamera?entity_id=${encodeURIComponent(entity)}`, {method: "POST"});
    await new Promise(r => setTimeout(r, 4000));
    for (let i = 0; i < 45; i++) {  // wait until the add-on answers again
      try { const neu = await api("admin/info"); if (neu.kamera === entity) { location.reload(); return; } } catch (_) {}
      await new Promise(r => setTimeout(r, 2000));
    }
    melden("m-automatik", t("kamera.gespeichert"), "gut");
  } catch (e) { melden("m-automatik", fehler(e), "schlecht"); knopf.disabled = false; }
});

$("#jetzt").addEventListener("click", async (ev) => {
  const knopf = ev.currentTarget;
  knopf.disabled = true; melden("m-automatik", t("lese_ab"));
  try {
    const a = await api("admin/automatik/jetzt", {method: "POST"});
    const l = a.letzter;
    melden("m-automatik", statusText(l), l.status === "error" || l.status === "rejected" ? "schlecht" : "gut");
    await Promise.all([ladeInfo(), ladeAblesungen()]);
  } catch (e) { melden("m-automatik", fehler(e), "schlecht"); }
  knopf.disabled = false;
});
$("#zaehlerstand").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.currentTarget, knopf = f.querySelector("button");
  if (!WERT_MUSTER.test(f.wert.value.trim())) { melden("m-automatik", t("format"), "schlecht"); return; }
  if (!bestaetigt(knopf, t("wirklich_setzen"))) return;
  knopf.disabled = true;
  try {
    await api(`admin/automatik/zaehlerstand?wert=${encodeURIComponent(punkt(f.wert.value))}`, {method: "POST"});
    melden("m-automatik", t("stand_gesetzt", {wert: m3(punkt(f.wert.value))}), "gut"); f.reset();
    await ladeInfo();
  } catch (e) { melden("m-automatik", fehler(e), "schlecht"); }
  knopf.disabled = false;
});

// ---- Recent readings -----------------------------------------------------------
async function ladeAblesungen() {
  const liste = await api("admin/ablesungen");
  $("#ablesungen").replaceChildren(...(liste.length ? liste.map(a => el("li", {},
    el("a", {href: `./?nr=${a.nr}`, text: `#${a.nr}`}),
    el("span", {class: "num", text: `${m3(a.wert)} m³`}),
    el("span", {class: a.sicher ? "gut" : "schlecht", text: t(a.sicher ? "sicher" : "unsicher")}),
    el("span", {class: "leise", text: zeit(a.zeit)}),
  )) : [el("li", {class: "leise", text: t("keine_ablesung")})]));
}

// ---- Templates -----------------------------------------------------------------
async function ladeVorlagen() {
  const daten = await api("admin/vorlagen");
  $("#vorlagen").replaceChildren(...Object.entries(daten).map(([ziffer, liste]) =>
    el("div", {class: "ziffer-zeile"},
      el("div", {class: "ziffer-kopf"}, ziffer, el("small", {text: `${liste.length}×`})),
      el("div", {class: "kacheln"}, ...(liste.length ? liste.map(v => {
        const [zs, rolle] = v.name.replace(/\.png$/, "").split("_r");
        const wann = stempelZeit(zs);
        return el("img", {
          src: `data:image/png;base64,${v.png}`, alt: t("vorlage.alt", {ziffer}),
          title: t("vorlage.titel", {rolle, wann: wann ? t("vorlage.wann", {zeit: zeit(wann)}) : ""}),
          onclick: () => zeigeLernbild(zs),
        });
      }) : [el("span", {class: "leer", text: t("vorlage.keine")})]))
    )));
}
function zeigeLernbild(zeitstempel) {
  const i = alleLernbilder.findIndex(lb => lb.zeitstempel === zeitstempel);
  if (i < 0) { melden("m-vorlagen", t("vorlage.ohne_lernbild"), "schlecht"); return; }
  if (i >= SEITE_GROESSE && !zeigeAlle) { zeigeAlle = true; renderLernbilder(); }
  const karte = document.getElementById(`lb-${zeitstempel}`);
  karte.scrollIntoView({behavior: "smooth", block: "center"});
  karte.classList.add("markiert");
  setTimeout(() => karte.classList.remove("markiert"), 2500);
}
$("#neu-aufbauen").addEventListener("click", async (ev) => {
  const knopf = ev.currentTarget;
  if (!info.lerneffekt && !bestaetigt(knopf, t("neu.trotzdem"))) return;
  knopf.disabled = true; melden("m-vorlagen", t("neu.laeuft"));
  try {
    await api("admin/neu-aufbauen", {method: "POST"});
    melden("m-vorlagen", t("neu.fertig"), "gut");
    await Promise.all([ladeInfo(), ladeVorlagen()]);
  } catch (e) { melden("m-vorlagen", fehler(e), "schlecht"); }
  knopf.disabled = false;
});

// ---- Training images -----------------------------------------------------------
async function ladeLernbilder() {
  alleLernbilder = await api("admin/lernbilder");
  renderLernbilder();
}
function renderLernbilder() {
  const sichtbar = zeigeAlle ? alleLernbilder : alleLernbilder.slice(0, SEITE_GROESSE);
  $("#lb-anzahl").textContent = `(${alleLernbilder.length})`;
  const mehr = $("#mehr");
  mehr.hidden = zeigeAlle || alleLernbilder.length <= SEITE_GROESSE;
  mehr.textContent = t("lb.alle", {n: alleLernbilder.length});
  $("#lernbilder").replaceChildren(...(sichtbar.length ? sichtbar.map(lernbildKarte)
    : [el("p", {class: "leise", text: t("lb.keine")})]));
}
function lernbildKarte(lb) {
  const pfad = `admin/lernbilder/${encodeURIComponent(lb.name)}`;
  const eingabe = el("input", {name: "wert", inputmode: "decimal", value: m3(lb.wert), "aria-label": t("stand_m3")});
  const speichern = el("button", {type: "submit", class: "zweit", text: t("lb.speichern")});
  const loeschen = el("button", {type: "button", class: "zweit", text: t("lb.loeschen")});
  const meldung = el("div", {class: "meldung leise"});
  const falsch = (e, knopf) => { meldung.className = "meldung schlecht"; meldung.textContent = fehler(e); knopf.disabled = false; };
  const form = el("form", {autocomplete: "off"}, eingabe, speichern, loeschen);
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!WERT_MUSTER.test(eingabe.value.trim())) { falsch(new Error(t("format")), speichern); return; }
    speichern.disabled = true;
    try {
      const d = await api(`${pfad}/wert?wert=${encodeURIComponent(punkt(eingabe.value))}`, {method: "POST"});
      await nachAenderung(d, t("lb.geaendert", {wert: m3(punkt(eingabe.value))}));
    } catch (e) { falsch(e, speichern); }
  });
  loeschen.addEventListener("click", async () => {
    if (!bestaetigt(loeschen, t("lb.wirklich_loeschen"))) return;
    loeschen.disabled = true;
    try { await nachAenderung(await api(`${pfad}/loeschen`, {method: "POST"}), t("lb.geloescht")); }
    catch (e) { falsch(e, loeschen); }
  });
  return el("div", {class: "lernbild", id: `lb-${lb.zeitstempel}`},
    el("a", {href: pfad, target: "_blank", rel: "noopener", title: t("lb.ganzes_bild")},
      el("img", {src: `${pfad}?ausschnitt=1`, alt: t("lb.alt", {wert: m3(lb.wert)}), loading: "lazy"})),
    el("div", {}, el("span", {class: "num", text: `${m3(lb.wert)} m³`}), el("span", {class: "leise", text: ` · ${zeit(lb.zeit)}`})),
    form, meldung);
}
async function nachAenderung(d, text) {
  const zusatz = t(d.vorlagen_neu_aufgebaut ? "neu.fertig" : "lb.unveraendert");
  melden("m-lernbilder", `${text}. ${zusatz}`, "gut");
  await Promise.all([ladeInfo(), ladeVorlagen(), ladeLernbilder()]);
}
$("#mehr").addEventListener("click", () => { zeigeAlle = true; renderLernbilder(); });

// ---- Training ------------------------------------------------------------------
$("#kamera").addEventListener("click", async (ev) => {
  const knopf = ev.currentTarget;
  knopf.disabled = true; melden("m-nachlernen", t("hole_bild"));
  try { const d = await api("kamera-ablesen", {method: "POST"}); location.href = `./?nr=${d.nr}`; }
  catch (e) { melden("m-nachlernen", fehler(e), "schlecht"); knopf.disabled = false; }
});
$("#upload").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.currentTarget, knopf = f.querySelector("button"), datei = f.datei.files[0];
  if (!datei) { melden("m-nachlernen", t("upload.bild_fehlt"), "schlecht"); return; }
  if (!WERT_MUSTER.test(f.wert.value.trim())) { melden("m-nachlernen", t("upload.format"), "schlecht"); return; }
  knopf.disabled = true; melden("m-nachlernen", t("lerne"));
  try {
    const d = await api(`lernen?wert=${encodeURIComponent(punkt(f.wert.value))}`,
      {method: "POST", headers: {"Content-Type": datei.type || "image/jpeg"}, body: datei});
    melden("m-nachlernen", t("upload.gelernt", {n: d.gespeichert}), "gut");
    f.reset();
    await Promise.all([ladeInfo(), ladeVorlagen(), ladeLernbilder()]);
  } catch (e) { melden("m-nachlernen", fehler(e), "schlecht"); }
  knopf.disabled = false;
});

// ---- Export & import -----------------------------------------------------------
$("#import").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.currentTarget, knopf = f.querySelector("button"), datei = f.datei.files[0], modus = f.modus.value;
  if (!datei) { melden("m-import", t("import.zip_fehlt"), "schlecht"); return; }
  if (modus === "ersetzen" && !bestaetigt(knopf, t("import.wirklich"))) return;
  knopf.disabled = true; melden("m-import", t("import.laeuft"));
  try {
    const d = await api(`admin/import?modus=${modus}`,
      {method: "POST", headers: {"Content-Type": "application/zip"}, body: datei});
    const teile = [t(modus === "ersetzen" ? "import.uebernommen" : "import.neu", {n: d.lernbilder_neu})];
    if (d.uebersprungen) teile.push(t("import.uebersprungen", {n: d.uebersprungen}));
    teile.push(t(d.vorlagen_neu_aufgebaut ? "import.vorlagen_neu"
      : modus === "ersetzen" ? "import.vorlagen_zip" : "import.vorlagen_gleich"));
    melden("m-import", teile.join(" · "), "gut");
    f.reset();
    await allesLaden();
  } catch (e) { melden("m-import", fehler(e), "schlecht"); }
  knopf.disabled = false;
});

$("#zuruecksetzen").addEventListener("click", async (ev) => {
  const knopf = ev.currentTarget;
  if (!bestaetigt(knopf, t("reset.wirklich"))) return;
  knopf.disabled = true;
  try {
    await api("admin/zuruecksetzen", {method: "POST"});
    melden("m-import", t("reset.fertig"), "gut");
    await allesLaden();
  } catch (e) { melden("m-import", fehler(e), "schlecht"); }
  knopf.disabled = false;
});

allesLaden().catch(e => melden("m-laden", t("laden_fehler", {text: e.message}), "schlecht"));
"""

_HTML = """<!doctype html>
<html lang="@@LANG@@">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{adm.titel}}</title>
<style>@@CSS@@</style>
</head>
<body>
<main>
  @@KOPF@@
  <div class="chips" id="chips"></div>
  <div id="m-laden" class="meldung"></div>

  <section class="karte" id="leer-hinweis" hidden>
    <h2>{{adm.leer.titel}}</h2>
    <p class="leise">{{adm.leer.text}}</p>
    <div class="zeile"><a class="knopf" href="#import-karte">{{adm.leer.importieren}}</a>
      <a class="knopf zweit" href="./">{{adm.leer.lernseite}}</a></div>
  </section>

  <section class="karte">
    <h2>{{adm.automatik.titel}}</h2>
    <p class="leise">{{adm.automatik.text}}</p>
    <dl class="einstellungen" id="automatik"></dl>
    <form id="kamera-wahl" autocomplete="off" hidden>
      <label for="kamera-liste">{{adm.automatik.kamera_label}}</label>
      <select id="kamera-liste" name="kamera"></select>
      <button type="submit">{{adm.automatik.uebernehmen}}</button>
    </form>
    <img id="kamera-vorschau" class="bild" alt="{{adm.automatik.vorschau}}" hidden>
    <div class="zeile"><button type="button" id="jetzt" hidden>{{adm.automatik.jetzt}}</button></div>
    <form id="zaehlerstand" autocomplete="off">
      <label>{{adm.automatik.stand_label}}</label>
      <input name="wert" inputmode="decimal" placeholder="506.388" aria-label="{{ui.stand_m3}}">
      <button type="submit" class="zweit">{{adm.automatik.setzen}}</button>
    </form>
    <div id="m-automatik" class="meldung"></div>
  </section>

  <section class="karte">
    <h2>{{adm.lernen.titel}}</h2>
    <div class="zeile" style="margin-top:0">
      <button type="button" id="kamera" hidden>{{ui.kamera_jetzt}}</button>
      <a class="knopf zweit" href="./">{{adm.lernen.pruefen}}</a>
    </div>
    <p class="leise" id="kamera-hinweis"></p>
    <form id="upload" autocomplete="off">
      <label>{{adm.lernen.upload_label}}</label>
      <input type="file" name="datei" accept="image/jpeg,image/png">
      <input name="wert" inputmode="decimal" placeholder="506.388" aria-label="{{ui.stand_m3}}">
      <button type="submit">{{adm.lernen.knopf}}</button>
    </form>
    <div id="m-nachlernen" class="meldung"></div>
  </section>

  <section class="karte">
    <h2>{{adm.ablesungen.titel}}</h2>
    <p class="leise">{{adm.ablesungen.text}}</p>
    <ul class="liste" id="ablesungen"></ul>
  </section>

  <section class="karte">
    <h2>{{adm.vorlagen.titel}}</h2>
    <p class="leise">{{adm.vorlagen.text}}</p>
    <div id="vorlagen"></div>
    <div class="zeile"><button type="button" class="zweit" id="neu-aufbauen">{{adm.vorlagen.neu}}</button></div>
    <div id="m-vorlagen" class="meldung"></div>
  </section>

  <section class="karte">
    <h2>{{adm.lernbilder.titel}} <span id="lb-anzahl" class="leise"></span></h2>
    <p class="leise">{{adm.lernbilder.text}}</p>
    <div id="m-lernbilder" class="meldung"></div>
    <div id="lernbilder"></div>
    <div class="zeile"><button type="button" class="zweit" id="mehr" hidden></button></div>
  </section>

  <section class="karte" id="import-karte">
    <h2>{{adm.sichern.titel}}</h2>
    <p class="leise">{{adm.sichern.text}}</p>
    <div class="zeile" style="margin-top:0"><a class="knopf" href="admin/export.zip" download>{{adm.sichern.export}}</a></div>
    <form id="import" autocomplete="off">
      <label>{{adm.sichern.import_label}}</label>
      <input type="file" name="datei" accept=".zip,application/zip">
      <select name="modus" aria-label="{{adm.sichern.modus}}">
        <option value="ergaenzen">{{adm.sichern.ergaenzen}}</option>
        <option value="ersetzen">{{adm.sichern.ersetzen}}</option>
      </select>
      <button type="submit">{{adm.sichern.importieren}}</button>
    </form>
    <div class="zeile"><button type="button" id="zuruecksetzen" class="zweit">{{adm.sichern.zuruecksetzen}}</button></div>
    <div id="m-import" class="meldung"></div>
  </section>

  <section class="karte">
    <h2>{{adm.einstellungen.titel}}</h2>
    <dl class="einstellungen" id="einstellungen"></dl>
    <p class="leise" id="einstellungen-hinweis"></p>
  </section>
</main>
@@SKRIPT@@
</body>
</html>
"""

_MARKE = re.compile(r"\{\{([\w.]+)\}\}")


@lru_cache(maxsize=len(SPRACHEN))
def seite(sprache: str) -> str:
    """Die Verwaltungsseite in einer Sprache (einmal erzeugt, danach aus dem Zwischenspeicher)."""

    def text(m: re.Match) -> str:
        schluessel = m.group(1)
        wert = uebersetzen(schluessel, sprache)
        return wert if schluessel.endswith("_html") else escape(wert)

    return (
        _MARKE.sub(text, _HTML)
        .replace("@@LANG@@", sprache)
        .replace("@@CSS@@", BASIS_CSS + _CSS)
        .replace("@@KOPF@@", kopf("admin", True, sprache))
        .replace("@@SKRIPT@@", skript(sprache, _SKRIPT))
    )
