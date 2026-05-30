"""Preprocesado y codificacion de labels para el modelo de NUMERO COMPLETO.

Este modulo es COMPARTIDO entre entrenamiento (`vision/training/train_number.py`)
y runtime (`vision/detectors/number_reader.py`), igual rol que `segment.py` para
el modelo viejo de digitos. La regla es: train y runtime DEBEN preprocesar
identico, o el modelo ve algo distinto en produccion. Por eso vive en un solo
lugar.

El modelo lee el numero completo del HUD sin segmentar. CLAVE: el HUD del juego
SIEMPRE dibuja DOS digitos de magnitud con cero a la izquierda ("09", "00",
"26", "90"), nunca un solo digito. Por eso descomponemos en exactamente:

  * cabeza `sign`: {positivo, negativo}        -> 2 clases
  * cabeza `tens`: {0..9}  (digito de decenas) -> 10 clases
  * cabeza `ones`: {0..9}  (digito de unidad)  -> 10 clases

No hay clase "blank": como siempre se dibujan 2 digitos, no hay ambiguedad de
longitud. Parseamos por MAGNITUD (no por el largo del string del label), asi el
label puede venir como "9" o "09" o "-09" — da igual:

  "5" / "05"  -> sign=+, tens=0, ones=5   (el HUD dibuja "05")
  "0" / "00"  -> sign=+, tens=0, ones=0   (el HUD dibuja "00")
  "87"        -> sign=+, tens=8, ones=7
  "-09"       -> sign=-, tens=0, ones=9
  "-26"       -> sign=-, tens=2, ones=6
"""

from __future__ import annotations

import cv2
import numpy as np

# --- Lienzo de entrada del modelo ---
CANVAS_H = 32
CANVAS_W = 64

# --- Clases por cabeza ---
SIGN_CLASSES = 2
TENS_CLASSES = 10  # 0..9 (el HUD siempre dibuja 2 digitos de magnitud)
ONES_CLASSES = 10  # 0..9

# --- Indices de clase del signo ---
SIGN_POS = 0
SIGN_NEG = 1

# --- Rango legal del angulo en el juego (prior fuerte de validez) ---
VALID_MIN = -26
VALID_MAX = 90


def _ink_bbox(gray: np.ndarray) -> tuple[int, int, int, int] | None:
    """Bounding box de la TINTA (los glifos) en un recorte grayscale.

    No segmenta digitos: solo encuentra la extension global del numero para
    poder escalarlo y alinearlo de forma consistente. Mucho mas robusto que
    la segmentacion por digito.

    Asume tinta clara sobre fondo oscuro (HUD del juego). Si Otsu deja mas
    blanco que negro, invierte (la tinta es la minoria).
    """
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if mask.mean() > 127:
        mask = cv2.bitwise_not(mask)
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def to_canvas(bgr: np.ndarray, *, pad: int = 2) -> np.ndarray:
    """Normaliza un recorte del HUD al lienzo del modelo.

    Pasos: grayscale -> bbox de tinta -> recorte con padding -> escala
    preservando aspecto (`min(H/h, W/w)`) -> alineado a la DERECHA y centrado
    vertical sobre fondo negro. El right-align fija la posicion de las
    unidades (siempre el glifo mas a la derecha) y las decenas a su izquierda.

    Devuelve uint8 (CANVAS_H, CANVAS_W) en grayscale CRUDO (sin /255 — el
    caller normaliza). NO binariza: la binarizacion era la fragilidad del
    modelo viejo.
    """
    if bgr is None or bgr.size == 0:
        return np.zeros((CANVAS_H, CANVAS_W), dtype=np.uint8)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr

    box = _ink_bbox(gray)
    if box is None:
        return np.zeros((CANVAS_H, CANVAS_W), dtype=np.uint8)
    x0, y0, x1, y1 = box
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(gray.shape[1], x1 + pad)
    y1 = min(gray.shape[0], y1 + pad)
    crop = gray[y0:y1, x0:x1]
    h, w = crop.shape[:2]
    if h == 0 or w == 0:
        return np.zeros((CANVAS_H, CANVAS_W), dtype=np.uint8)

    scale = min(CANVAS_H / h, CANVAS_W / w)
    new_w = max(1, min(CANVAS_W, int(round(w * scale))))
    new_h = max(1, min(CANVAS_H, int(round(h * scale))))
    resized = cv2.resize(crop, (new_w, new_h), interpolation=cv2.INTER_AREA)

    canvas = np.zeros((CANVAS_H, CANVAS_W), dtype=np.uint8)
    ox = CANVAS_W - new_w  # alineado a la derecha
    oy = (CANVAS_H - new_h) // 2  # centrado vertical
    canvas[oy : oy + new_h, ox : ox + new_w] = resized
    return canvas


def parse_label(s: str) -> tuple[int, int, int]:
    """Convierte un label string ("89", "-09", "9", "0") en indices de clase
    (sign, tens, ones). Parsea por MAGNITUD: el HUD siempre dibuja 2 digitos,
    asi que el label puede venir con o sin cero a la izquierda — da igual.
    """
    s = s.strip()
    sign = SIGN_NEG if s.startswith("-") else SIGN_POS
    digits = s.lstrip("+-")
    if not digits.isdigit():
        raise ValueError(f"label invalido: {s!r}")
    mag = int(digits)
    if mag > 99:
        raise ValueError(f"magnitud de mas de 2 digitos: {s!r}")
    return sign, mag // 10, mag % 10


def reconstruct(sign: int, tens: int, ones: int) -> int:
    """Inversa de `parse_label` a nivel de VALOR entero."""
    mag = tens * 10 + ones
    return -mag if sign == SIGN_NEG else mag


def in_valid_range(value: int) -> bool:
    return VALID_MIN <= value <= VALID_MAX
