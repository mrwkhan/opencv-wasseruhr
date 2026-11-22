"""Debug-Bild: Kamerabild mit eingezeichneten ROIs, darunter die aufbereiteten Ziffern."""

from __future__ import annotations

from typing import Sequence

import cv2
import numpy as np

from .erkennung import ZiffernErgebnis

GRUEN = (0, 200, 0)
ROT = (0, 0, 255)
WEISS = (255, 255, 255)
GRAU = (170, 170, 170)
SCHRIFT = cv2.FONT_HERSHEY_SIMPLEX
ZOOM = 3
ABSTAND = 8


def zeichne(
    bild: np.ndarray,
    rois: Sequence[Sequence[int]],
    ziffern: Sequence[np.ndarray],
    ergebnisse: Sequence[ZiffernErgebnis],
    sicher_pro_rolle: Sequence[bool],
    wert: float | None,
    sicher: bool,
) -> bytes:
    oben = bild.copy()
    for (x1, y1, x2, y2), e, ok in zip(rois, ergebnisse, sicher_pro_rolle):
        farbe = GRUEN if ok else ROT
        cv2.rectangle(oben, (x1, y1), (x2 - 1, y2 - 1), farbe, 1)
        cv2.putText(oben, str(e.rolle), (x1, y1 - 4), SCHRIFT, 0.4, farbe, 1, cv2.LINE_AA)

    # Kacheln: aufbereitete Ziffer vergrößert + Beschriftung
    kachel_b = ziffern[0].shape[1] * ZOOM
    kachel_h = ziffern[0].shape[0] * ZOOM
    text_h = 44
    kacheln = []
    for z, e, ok in zip(ziffern, ergebnisse, sicher_pro_rolle):
        k = np.zeros((kachel_h + text_h, kachel_b), np.uint8)
        k = cv2.cvtColor(k, cv2.COLOR_GRAY2BGR)
        gross = cv2.resize(z, (kachel_b, kachel_h), interpolation=cv2.INTER_NEAREST)
        k[:kachel_h] = cv2.cvtColor(gross, cv2.COLOR_GRAY2BGR)
        farbe = GRUEN if ok else ROT
        cv2.rectangle(k, (0, 0), (kachel_b - 1, kachel_h - 1), farbe, 1)
        ziffer = "?" if e.ziffer is None else str(e.ziffer)
        score = "" if e.score is None else f"{e.score:.2f}"
        cv2.putText(k, f"{ziffer} {score}", (2, kachel_h + 16), SCHRIFT, 0.45, farbe, 1, cv2.LINE_AA)
        if e.zweitbeste is not None:
            cv2.putText(k, f"{e.zweitbeste} {e.score2:.2f}", (2, kachel_h + 36), SCHRIFT, 0.4, GRAU, 1, cv2.LINE_AA)
        kacheln.append(k)

    trenner = np.zeros((kachel_h + text_h, ABSTAND, 3), np.uint8)
    teile = []
    for k in kacheln:
        teile += [k, trenner]
    streifen = np.hstack(teile[:-1])

    titel = f"wert={'-' if wert is None else f'{wert:.3f}'}  sicher={'ja' if sicher else 'nein'}"
    kopf = np.zeros((28, max(oben.shape[1], streifen.shape[1]), 3), np.uint8)
    cv2.putText(kopf, titel, (6, 19), SCHRIFT, 0.55, GRUEN if sicher else ROT, 1, cv2.LINE_AA)

    breite = kopf.shape[1]
    zeilen = [_auffuellen(oben, breite), kopf, _auffuellen(streifen, breite)]
    ok, png = cv2.imencode(".png", np.vstack(zeilen))
    if not ok:
        raise RuntimeError("PNG-Kodierung fehlgeschlagen")
    return png.tobytes()


def _auffuellen(teil: np.ndarray, breite: int) -> np.ndarray:
    rest = breite - teil.shape[1]
    if rest <= 0:
        return teil
    return cv2.copyMakeBorder(teil, 0, 0, 0, rest, cv2.BORDER_CONSTANT, value=(0, 0, 0))
