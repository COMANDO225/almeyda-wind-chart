"""Detector del angulo de tiro — CNN de NUMERO COMPLETO (Camino 2).

El usuario coloca el marker sobre el numero del HUD inferior del juego. Usamos
la red multi-cabeza (`number_reader.read_angle`) que lee el numero ENTERO del
recorte sin segmentar digitos — lo que elimina el cuello de botella de
segmentacion del modelo viejo.

Rango valido del angulo en el juego: -26 a 90 (el negativo solo llega a ~-26;
pasando 90 vuelve a bajar sin volverse negativo). `read_angle` ya valida ese
rango como prior de validez.

CNN pura, SIN fallback: si la red no lee con confianza suficiente (o el modelo
no esta entrenado todavia), ese frame no produce lectura — el suavizado
temporal del loop mantiene la ultima lectura buena.
"""

from __future__ import annotations

import numpy as np

from ..types import AngleReading
from .number_reader import read_angle


def detect(roi_bgr: np.ndarray) -> AngleReading:
    if roi_bgr is None or roi_bgr.size == 0:
        return AngleReading()

    value, conf = read_angle(roi_bgr)
    if value is None:
        return AngleReading()
    return AngleReading(angle_deg=value, confidence=conf)
