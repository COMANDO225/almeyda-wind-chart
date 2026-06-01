"""Preprocesado y codificacion angular para el modelo del PUNTERO del viento.

Compartido entre entrenamiento (`vision/training/train_wind_pointer.py`) y
runtime (`vision/detectors/wind_pointer_reader.py`). Misma regla de oro que
con el angulo del HUD: train y runtime deben preprocesar identico.

El recorte de entrada YA viene con mascara circular aplicada (capturado con
`CaptureShape::Circle` desde Rust).

CANAL DE ENTRADA = "warm" (R - B), NO grayscale. El puntero del juego es rojo
con estela amarilla (R alto, B bajo → warm alto); el dial gris/azulado del
radar y los fondos texturados (satelite, remolino, mapas) dan warm ~0. En
grayscale el puntero se FUNDIA con fondos brillantes/texturados (el satelite
parecia una rejilla con lineas en toda direccion y el modelo alucinaba la
direccion). El canal warm aisla el puntero sobre CUALQUIER fondo porque es lo
unico rojo-amarillo-brillante de la escena. Sigue siendo 1 canal (el modelo no
cambia). Validado sobre frames reales: warm muestra el puntero limpio incluso
sobre el satelite rojo, donde grayscale lo perdia por completo.

Convencion de angulos (la misma que `wind.py` y `WindCompass.svelte`):
    0° = derecha (este), 90° = abajo, horario, rango [0, 360).

Codificacion como vector unitario (sin, cos) para evitar el bug del
wrap-around (359° y 1° estan cerca en el circulo pero lejos como numero).
La cabeza del modelo predice (sin, cos) y se decodifica con atan2.
"""

from __future__ import annotations

import math

import cv2
import numpy as np

# --- Lienzo de entrada del modelo ---
CANVAS = 64
CHANNELS = 1

# Máscara CENTRAL: se pinta de 0 (negro) el círculo central del canvas, donde
# vive el NÚMERO del viento. Así el modelo solo "ve" el anillo con el puntero y
# no se sesga por el número (en algunos temas es amarillo/dorado, que en el
# canal warm brilla tanto como el puntero rojo y desviaba la dirección unos
# grados). Es un círculo (rotacionalmente simétrico) → no introduce ninguna
# orientación artificial en la regresión angular. Radio = fracción del radio
# del canvas; el puntero llega a ~0.52R, el número hasta ~0.33R, así que 0.42
# tapa el número con margen y deja el tramo exterior del puntero (dirección).
MASK_INNER_FRAC = 0.42


def _warm_channel(bgr: np.ndarray) -> np.ndarray:
    """Canal 'warm' = clip(R - B, 0, 255). Resalta el puntero rojo-amarillo y
    suprime el dial gris/azulado y los fondos. Si la entrada ya es 1 canal
    (grayscale), la usa tal cual (fallback)."""
    if bgr.ndim == 2:
        return bgr
    b = bgr[:, :, 0].astype(np.int16)
    r = bgr[:, :, 2].astype(np.int16)
    return np.clip(r - b, 0, 255).astype(np.uint8)


def _mask_center(canvas: np.ndarray) -> np.ndarray:
    """Pinta de 0 el círculo central (donde está el número), dejando el anillo
    con el puntero. Opera in-place sobre una copia."""
    h, w = canvas.shape[:2]
    cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
    r = MASK_INNER_FRAC * (min(h, w) / 2.0)
    yy, xx = np.ogrid[:h, :w]
    inner = (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r
    out = canvas.copy()
    out[inner] = 0
    return out


def to_canvas(bgr: np.ndarray) -> np.ndarray:
    """Recorte del radar -> uint8 (CANVAS, CANVAS), canal warm (R-B) con el
    centro (número) enmascarado en negro.

    Asume entrada cuadrada o casi cuadrada con la mascara circular aplicada
    (afuera del circulo en negro). Si no es cuadrada, la encuadra centrando
    sobre fondo negro antes de redimensionar — asi el centro de la imagen
    sigue siendo el centro del radar (clave porque el angulo se mide desde
    ahi). Por ultimo enmascara el circulo central (el numero) para que el
    modelo se enfoque solo en el puntero del anillo.
    """
    if bgr is None or bgr.size == 0:
        return np.zeros((CANVAS, CANVAS), dtype=np.uint8)
    ch = _warm_channel(bgr)
    h, w = ch.shape[:2]
    if h != w:
        side = max(h, w)
        square = np.zeros((side, side), dtype=np.uint8)
        oy = (side - h) // 2
        ox = (side - w) // 2
        square[oy : oy + h, ox : ox + w] = ch
        ch = square
    resized = cv2.resize(ch, (CANVAS, CANVAS), interpolation=cv2.INTER_AREA)
    return _mask_center(resized)


def angle_to_xy(deg: float) -> tuple[float, float]:
    """deg en convencion proyecto -> (sin, cos) en el circulo unitario."""
    rad = math.radians(deg)
    # Devolvemos (sin, cos) en ese orden para que en el reader sea simetrico
    # con atan2(sin, cos). Igual da lo que da; lo importante es la convencion
    # consistente entre train y runtime.
    return math.sin(rad), math.cos(rad)


def xy_to_angle(sin_v: float, cos_v: float) -> float:
    """(sin, cos) -> deg en convencion proyecto, normalizado a [0, 360)."""
    deg = math.degrees(math.atan2(sin_v, cos_v))
    return (deg + 360.0) % 360.0


def angular_distance(a: float, b: float) -> float:
    """Distancia angular minima entre a y b en grados (siempre [0, 180])."""
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)
