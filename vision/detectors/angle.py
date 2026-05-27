"""Detector del angulo de tiro.

El usuario coloca este marker (rect chico) sobre el numero del HUD inferior
del juego (formato "LAST XX YY" o "YY°"). Aplicamos OCR con preprocesado
multi-strategy.

A.4 + B.1: usamos ``crop_digits=True`` para que ``read_digits`` descarte
el simbolo "°" antes del OCR (el ° es mucho mas bajo que los digitos).
Eliminamos ``color="yellow"`` para no depender de temas del juego.

El detector es agnostico al juego: si lo apuntas a CUALQUIER numero en
pantalla (libro, foto, otro juego, etc.), lo lee igual.
"""
from __future__ import annotations

import logging

import numpy as np

from ..types import AngleReading
from ._ocr import read_digits

log = logging.getLogger(__name__)


def detect(roi_bgr: np.ndarray) -> AngleReading:
    if roi_bgr is None or roi_bgr.size == 0:
        return AngleReading()
    value, conf = read_digits(
        roi_bgr,
        upscale=5.0,
        min_value=0,
        max_value=90,
        crop_digits=True,  # A.4: descarta el "°"
        debug_tag="angle",
    )
    return AngleReading(angle_deg=value, confidence=conf)
