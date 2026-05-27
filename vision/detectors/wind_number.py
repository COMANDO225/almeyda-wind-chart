"""Flujo del NUMERO del viento dentro del marker circular.

Recibe el frame circular completo (mascara aplicada). Recorta el cuadrado
central donde vive el numero verde y aplica OCR. La direccion la maneja
`wind.detect()` en un flujo paralelo.

Performance: el OCR se aplica sobre un crop pequeno (~60% del lado del
circulo) — rapido. Y como no depende de colores, es robusto a temas.
"""
from __future__ import annotations

import logging

import numpy as np

from ..types import WindReading
from ._ocr import read_digits

log = logging.getLogger(__name__)


def detect(roi_bgr: np.ndarray) -> WindReading:
    """Lee solo la magnitud del viento desde el centro del circulo."""
    if roi_bgr is None or roi_bgr.size == 0:
        return WindReading()

    # Recortar el cuadrado central donde esta el numero (evita borde negro
    # de la mascara circular y zona del puntero en el anillo exterior).
    h, w = roi_bgr.shape[:2]
    side = int(min(h, w) * 0.55)
    cx, cy = w // 2, h // 2
    x0 = max(0, cx - side // 2)
    y0 = max(0, cy - side // 2)
    center = roi_bgr[y0 : y0 + side, x0 : x0 + side]

    # color="green" como HINT (asistencia, no dependencia): si el HUD del
    # juego sigue mostrando el numero en verde (tema vainilla), la
    # green_mask suma una strategy adicional al voting. Si cambia el tema,
    # las otras strategies generales (otsu, edges, brightness, B.1) hacen
    # el trabajo. No es excluyente.
    value, conf = read_digits(
        center,
        upscale=4.0,
        min_value=0,
        max_value=99,
        color="green",
        debug_tag="wind_number",
    )
    return WindReading(value=value, direction_deg=None, confidence=conf)
