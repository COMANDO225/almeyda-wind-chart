"""Detector del angulo de tiro — ahora con CNN custom (Sprint C.4).

El usuario coloca el marker sobre el numero del HUD inferior del juego.
Usamos la CNN entrenada (`digit_classifier.onnx`) via `cnn_digits.read_number`
en lugar de RapidOCR: mas rapido (~1 ms), mas chico (611 KB), y entrenado
con la fuente especifica del juego.

Rango valido del angulo en el juego: -26 a 90 aprox (el negativo solo llega
a ~-26 con el mobile de mayor angulo; pasando 90 vuelve a bajar sin volverse
negativo). Usamos -90..90 por margen.

Fallback: si la CNN no encuentra digitos (modelo ausente o segmentacion
fallida), cae a RapidOCR via `read_digits` para no quedarse sin lectura.
"""
from __future__ import annotations

import logging

import numpy as np

from ..types import AngleReading

log = logging.getLogger(__name__)


def detect(roi_bgr: np.ndarray) -> AngleReading:
    if roi_bgr is None or roi_bgr.size == 0:
        return AngleReading()

    # Camino principal: CNN custom.
    try:
        from .cnn_digits import read_number

        value, conf = read_number(roi_bgr, min_value=-90, max_value=90)
        if value is not None:
            return AngleReading(angle_deg=value, confidence=conf)
    except FileNotFoundError:
        log.warning("CNN no disponible, usando RapidOCR fallback")
    except Exception as e:  # noqa: BLE001
        log.debug("CNN read_number fallo: %s — fallback a RapidOCR", e)

    # Fallback: RapidOCR (no maneja negativos, pero mejor que nada).
    from ._ocr import read_digits

    value, conf = read_digits(
        roi_bgr, upscale=5.0, min_value=0, max_value=90, crop_digits=True, debug_tag="angle"
    )
    return AngleReading(angle_deg=value, confidence=conf)
