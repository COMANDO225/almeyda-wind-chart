"""Direccion del puntero del medidor de viento — CNN custom (Camino 2).

Reemplaza al detector geometrico anterior (fan-sweep angular) por el modelo
de regresion angular entrenado: una sola pasada sobre el recorte circular
del marker_wind devuelve la direccion del puntero como vector (sin, cos)
que se decodifica con atan2.

El recorte llega con la mascara circular ya aplicada (capturado con
`CaptureShape::Circle` desde Rust) — el mismo preprocesado que en
entrenamiento (`to_canvas`).

El NUMERO del viento se sigue leyendo aparte en `wind_number.detect()`; el
sidecar combina ambos en un solo `WindReading` (value + direction_deg). Aca
solo nos ocupamos del `direction_deg`.
"""

from __future__ import annotations

import numpy as np

from ..types import WindReading
from .wind_pointer_reader import read_pointer


def detect(roi_bgr: np.ndarray) -> WindReading:
    if roi_bgr is None or roi_bgr.size == 0 or min(roi_bgr.shape[:2]) < 20:
        return WindReading()
    direction, conf = read_pointer(roi_bgr)
    return WindReading(value=None, direction_deg=direction, confidence=conf)
