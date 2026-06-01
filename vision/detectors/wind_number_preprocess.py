"""Preprocesado y codificacion de labels del NUMERO del viento.

Compartido entre `vision/training/train_wind_number.py` y
`vision/detectors/wind_number_reader.py` — train y runtime deben preprocesar
IDENTICO. Mismo patron que `number_preprocess.py` (angulo) pero adaptado al
wind_number:

  * Rango 0-50  (no hay negativos como en el angulo).
  * 2 cabezas:  `tens` (0..5) + `ones` (0..9).
  * Sin clase "blank" — el HUD del juego SIEMPRE dibuja 2 digitos con cero
    a la izquierda ("00", "05", "47", "50"), y el visor sintetico (Almeyda
    Wind Visor) tambien genera labels zero-padded. Parseamos por MAGNITUD,
    asi tanto "5" como "05" funcionan.
"""

from __future__ import annotations

import cv2
import numpy as np

# --- Lienzo de entrada del modelo ---
CANVAS_H = 32
CANVAS_W = 64

# --- Clases por cabeza ---
TENS_CLASSES = 6  # 0..5 (rango 0-50, decena maxima = 5)
ONES_CLASSES = 10  # 0..9

# --- Rango legal del viento en el juego (prior fuerte) ---
VALID_MIN = 0
VALID_MAX = 50


# Region central del recorte (centro-80 del radar) donde viven los DOS
# digitos. Es FIJA a proposito: en el radar, segmentar por contenido (bbox)
# era inconsistente — a veces agarraba el dial/marcas/puntero, a veces parte
# del numero — y esa inconsistencia (no "ver el radar") fue lo que tumbo la
# precision. Un recorte fijo da entrada CONSISTENTE: el modelo aprende a leer
# los digitos centrados e ignora la textura del radar (que con 22k muestras x
# 4 fondos x 6 opacidades x punteros aleatorios es ruido no correlacionado).
# Valores derivados de la geometria del visor (digitos ~0.5R ancho x 0.38R
# alto, centrados; el recorte de entrada es 0.8R) + margen.
CENTER_W_FRAC = 0.74
CENTER_H_FRAC = 0.56


def to_canvas(bgr: np.ndarray) -> np.ndarray:
    """Normaliza un recorte del radar (centro-80) al lienzo del modelo.

    Toma una ventana CENTRAL fija (donde estan los 2 digitos), la pasa a
    grayscale y la escala a CANVAS_H x CANVAS_W. Determinista: misma entrada
    para el mismo recorte, sin segmentacion dependiente del contenido.

    Devuelve uint8 (CANVAS_H, CANVAS_W) grayscale CRUDO (sin /255 — el caller
    normaliza). NO binariza.
    """
    if bgr is None or bgr.size == 0:
        return np.zeros((CANVAS_H, CANVAS_W), dtype=np.uint8)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    h, w = gray.shape[:2]
    if h == 0 or w == 0:
        return np.zeros((CANVAS_H, CANVAS_W), dtype=np.uint8)

    cw = max(1, int(round(w * CENTER_W_FRAC)))
    ch = max(1, int(round(h * CENTER_H_FRAC)))
    x0 = (w - cw) // 2
    y0 = (h - ch) // 2
    crop = gray[y0 : y0 + ch, x0 : x0 + cw]

    return cv2.resize(crop, (CANVAS_W, CANVAS_H), interpolation=cv2.INTER_AREA)


def parse_label(s: str) -> tuple[int, int]:
    """Convierte un label string ("5", "05", "47", "50") en (tens, ones).

    Parsea por MAGNITUD: el HUD/visor siempre dibuja 2 digitos, asi que el
    label puede venir con o sin cero a la izquierda — da igual.
    """
    s = s.strip().lstrip("+")
    if not s.isdigit():
        raise ValueError(f"label invalido (esperaba digitos sin signo): {s!r}")
    mag = int(s)
    if mag < VALID_MIN or mag > VALID_MAX:
        raise ValueError(f"label fuera de rango {VALID_MIN}-{VALID_MAX}: {s!r}")
    return mag // 10, mag % 10


def reconstruct(tens: int, ones: int) -> int:
    """Inversa de `parse_label` a nivel de VALOR entero."""
    return tens * 10 + ones


def in_valid_range(value: int) -> bool:
    return VALID_MIN <= value <= VALID_MAX
