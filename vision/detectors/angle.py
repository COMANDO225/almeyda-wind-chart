"""Detector del ángulo de tiro.

Cuando el marker se coloca sobre el "54" amarillo del HUD inferior del juego,
la ROI ya viene recortada solo al dígito (cuadrado pequeño). Aplicamos
RapidOCR con preprocesado de upscale + Otsu.

El detector es agnóstico al juego: si lo apuntás a CUALQUIER número en
pantalla (libro, foto, otro juego, etc.), lo lee igual. Esto es el test de
resiliencia del MVP de Fase 1.
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
        roi_bgr, upscale=5.0, min_value=0, max_value=90, color="yellow", debug_tag="angle"
    )
    return AngleReading(angle_deg=value, confidence=conf)
