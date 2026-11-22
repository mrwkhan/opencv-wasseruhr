"""Klassische Bildverarbeitung: Ziffern ausschneiden, aufbereiten und per
Template Matching (TM_CCOEFF_NORMED) mit gelernten Vorlagen vergleichen."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping, Sequence

import cv2
import numpy as np

ZIFFER_BREITE = 24
ZIFFER_HOEHE = 40
RAND_SEITLICH = 3  # px, die pro ROI links und rechts abgeschnitten werden
MIN_KONTRAST_STD = 10.0  # echte Ziffern liegen nach MINMAX bei ~60–80


class BildFehler(ValueError):
    """Eingabebild unbrauchbar (kein JPEG, ROI außerhalb …)."""


@dataclass
class ZiffernErgebnis:
    rolle: int
    ziffer: int | None
    score: float | None
    zweitbeste: int | None
    score2: float | None

    def als_dict(self) -> dict:
        d = asdict(self)
        for k in ("score", "score2"):
            if d[k] is not None:
                d[k] = round(d[k], 3)
        return d


def dekodiere_bild(daten: bytes) -> np.ndarray:
    if not daten:
        raise BildFehler("Leerer Request-Body – rohes JPEG erwartet")
    try:
        bild = cv2.imdecode(np.frombuffer(daten, np.uint8), cv2.IMREAD_COLOR)
    except cv2.error:
        # OPENCV_IO_MAX_IMAGE_PIXELS überschritten (siehe app/__init__.py)
        raise BildFehler("Bild ist zu groß (Pixelzahl über der Grenze)") from None
    if bild is None:
        raise BildFehler("Body ist kein lesbares Bild – rohes JPEG erwartet")
    return bild


def bereite_ziffer_auf(roi_bgr: np.ndarray) -> np.ndarray:
    """ROI (BGR) -> normiertes 24x40-Graubild, Ziffer hell auf dunklem Grund."""
    roi = roi_bgr[:, RAND_SEITLICH:-RAND_SEITLICH]
    # "Tinte": schwarze und rote Ziffern haben beide wenig Blau UND Grün,
    # der helle Hintergrund nicht – unabhängig von der Farbe der Beleuchtung.
    tinte = 255 - np.minimum(roi[:, :, 0], roi[:, :, 1])
    tinte = cv2.normalize(tinte, None, 0, 255, cv2.NORM_MINMAX)
    tinte = cv2.GaussianBlur(tinte, (3, 3), 0)
    return cv2.resize(tinte, (ZIFFER_BREITE, ZIFFER_HOEHE), interpolation=cv2.INTER_AREA)


def schneide_ziffern(bild: np.ndarray, rois: Sequence[Sequence[int]]) -> list[np.ndarray]:
    hoehe, breite = bild.shape[:2]
    ziffern = []
    for rolle, (x1, y1, x2, y2) in enumerate(rois, start=1):
        if x2 > breite or y2 > hoehe:
            raise BildFehler(
                f"ROI der Rolle {rolle} {[x1, y1, x2, y2]} liegt außerhalb des Bildes "
                f"({breite}x{hoehe}) – ROIS anpassen"
            )
        ziffern.append(bereite_ziffer_auf(bild[y1:y2, x1:x2]))
    return ziffern


def ist_kontrastlos(bild: np.ndarray) -> bool:
    """Fast einfarbige Ziffer (Kamera dunkel/überbelichtet). Als Vorlage
    unbrauchbar: TM_CCOEFF_NORMED liefert für eine konstante Vorlage 1.0 gegen
    jedes Bild."""
    return float(bild.std()) < MIN_KONTRAST_STD


def korrelation(a: np.ndarray, b: np.ndarray) -> float:
    """Normierte Korrelation zweier gleich großer Bilder (ohne Verschiebung)."""
    wert = float(cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED)[0, 0])
    return wert if np.isfinite(wert) and abs(wert) <= 1.0 + 1e-6 else 0.0


def scores_pro_ziffer(
    ziffer_bild: np.ndarray,
    vorlagen: Mapping[int, Sequence[np.ndarray]],
    verschiebung: int,
) -> dict[int, float]:
    """Bester TM_CCOEFF_NORMED-Score je Ziffer über alle ihre Vorlagen,
    jeweils über alle Verschiebungen von ±verschiebung px."""
    v = verschiebung
    gepolstert = cv2.copyMakeBorder(ziffer_bild, v, v, v, v, cv2.BORDER_REPLICATE)
    scores: dict[int, float] = {}
    for ziffer, liste in vorlagen.items():
        bester = None
        for vorlage in liste:
            ergebnis = cv2.matchTemplate(gepolstert, vorlage, cv2.TM_CCOEFF_NORMED)
            # Konstante Bilder liefern NaN/Inf – als "keine Ähnlichkeit" werten.
            wert = float(np.nan_to_num(ergebnis, nan=0.0, posinf=0.0, neginf=0.0).max())
            if bester is None or wert > bester:
                bester = wert
        if bester is not None:
            scores[ziffer] = bester
    return scores


def erkenne_ziffer(
    rolle: int,
    ziffer_bild: np.ndarray,
    vorlagen: Mapping[int, Sequence[np.ndarray]],
    verschiebung: int,
) -> ZiffernErgebnis:
    rangliste = sorted(
        scores_pro_ziffer(ziffer_bild, vorlagen, verschiebung).items(),
        key=lambda kv: kv[1],
        reverse=True,
    )
    erste = rangliste[0] if rangliste else (None, None)
    zweite = rangliste[1] if len(rangliste) > 1 else (None, None)
    return ZiffernErgebnis(rolle, erste[0], erste[1], zweite[0], zweite[1])


def ist_sicher(e: ZiffernErgebnis, min_score: float, min_abstand: float) -> bool:
    return (
        e.ziffer is not None
        and e.score2 is not None
        and e.score >= min_score
        and e.score - e.score2 >= min_abstand
    )


def zusammensetzen(ergebnisse: Sequence[ZiffernErgebnis], nachkommastellen: int) -> float | None:
    """[0,0,5,0,6,3,8,8] -> 506.388; None, falls eine Rolle nicht erkannt wurde."""
    if not ergebnisse or any(e.ziffer is None for e in ergebnisse):
        return None
    ganzzahl = int("".join(str(e.ziffer) for e in ergebnisse))
    return round(ganzzahl / 10**nachkommastellen, nachkommastellen)


def zerlege_wert(wert: float, anzahl_rollen: int, nachkommastellen: int) -> list[int]:
    """506.388 -> [0,0,5,0,6,3,8,8] (entspricht "%09.3f" ohne Punkt bei 8 Rollen)."""
    if not np.isfinite(wert) or wert < 0:
        raise ValueError("Wert muss eine nicht-negative Zahl sein")
    breite = anzahl_rollen + 1  # +1 für den Dezimalpunkt
    text = f"{wert:0{breite}.{nachkommastellen}f}".replace(".", "")
    if len(text) != anzahl_rollen:
        raise ValueError(f"Wert {wert} passt nicht in {anzahl_rollen} Ziffern")
    return [int(c) for c in text]
