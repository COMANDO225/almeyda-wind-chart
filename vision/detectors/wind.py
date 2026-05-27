"""Flujo del PUNTERO del medidor de viento dentro del marker circular.

El marker_wind es CIRCULAR con mascara aplicada en Rust (todo lo de afuera
del circulo viene en negro). Este detector se enfoca SOLO en la direccion
del puntero — el numero se lee en paralelo en `wind_number.detect()`.

Algoritmo: **detector angular por fan-sweep**.

  1. Convertir a grises + blur amplio. Calcular |gray - blur| (desviacion
     respecto al promedio local). Eso resalta cualquier elemento que rompe
     la suavidad del fondo (puntero, dígitos, etc.).
  2. Construir un "fan" angular (sector circular) en el anillo donde
     suele estar el puntero (35%-49% del radio).
  3. Rotar el fan en pasos de 2 grados y sumar la deviation dentro. El
     angulo con mayor suma es la direccion del puntero.

Por que es mejor que centro de masa:
  - El centro de masa promedia TODA la deviation del anillo, asi que se
    distorsiona si hay ruido distribuido o partes del numero asoman.
  - El fan-sweep busca un PICO direccional concentrado — exactamente
    como se ve un puntero (es una linea/triangulo apuntando hacia un
    angulo, no un ruido distribuido).

Independiente de tema: no usa colores.
"""
from __future__ import annotations

import logging
from typing import Optional

import cv2
import numpy as np

from ..types import WindReading

log = logging.getLogger(__name__)


# Anillo donde se busca el puntero (% del radio).
RING_INNER = 0.35
RING_OUTER = 0.49

# Apertura del fan angular en grados (cuanto del anillo cubre cada fan).
FAN_WIDTH_DEG = 30.0

# Paso angular de busqueda (resolucion).
STEP_DEG = 2.0


def _deviation_map(roi_bgr: np.ndarray) -> np.ndarray:
    """|gray - blur|. Resalta pixeles que rompen la suavidad local."""
    gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    sigma = max(roi_bgr.shape[0], roi_bgr.shape[1]) / 8.0
    blurred = cv2.GaussianBlur(gray, (0, 0), sigmaX=sigma)
    return np.abs(gray - blurred)


def _ring_indices(shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Devuelve (radius_norm, angle_deg, ring_mask_bool) para cada pixel."""
    h, w = shape
    cx, cy = w / 2.0, h / 2.0
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dx = xx - cx
    dy = yy - cy
    r = np.sqrt(dx * dx + dy * dy)
    r_max = min(h, w) / 2.0
    r_norm = r / r_max
    # arctan2 devuelve [-pi, pi]; convertimos a [0, 360) horario, 0=derecha.
    ang = (np.degrees(np.arctan2(dy, dx)) + 360.0) % 360.0
    ring = (r_norm >= RING_INNER) & (r_norm <= RING_OUTER)
    return r_norm, ang, ring


def _fan_sweep(deviation: np.ndarray, ang: np.ndarray, ring: np.ndarray) -> tuple[Optional[float], float]:
    """Para cada angulo theta (en pasos de STEP_DEG), suma la deviation
    dentro del fan centrado en theta. Devuelve (theta_max, score)."""
    half = FAN_WIDTH_DEG / 2.0
    best_deg: Optional[float] = None
    best_sum = -1.0
    second_best_sum = 0.0  # para calcular relacion peak/2nd-peak (confianza)

    for theta in np.arange(0.0, 360.0, STEP_DEG):
        # Distancia angular minima (toma en cuenta wrap-around 360->0).
        diff = np.abs(ang - theta)
        diff = np.minimum(diff, 360.0 - diff)
        fan = ring & (diff <= half)
        if not fan.any():
            continue
        s = float(deviation[fan].sum())
        if s > best_sum:
            second_best_sum = best_sum if best_sum > 0 else 0.0
            best_sum = s
            best_deg = float(theta)
        elif s > second_best_sum:
            second_best_sum = s

    if best_deg is None or best_sum <= 0:
        return None, 0.0

    # Confianza: cuanto se destaca el peak vs el segundo (proxy de
    # concentracion del puntero). Si hay un puntero claro, el peak es
    # mucho mas alto que el resto -> ratio cerca de 1. Si es ruido,
    # ratio cerca de 0.
    if second_best_sum <= 0:
        conf = 1.0
    else:
        conf = float(np.clip(1.0 - second_best_sum / best_sum, 0.0, 1.0))
    return best_deg, conf


def detect(roi_bgr: np.ndarray) -> WindReading:
    """Devuelve solo la direccion del puntero. El value lo pone `wind_number.detect()`."""
    if roi_bgr is None or roi_bgr.size == 0 or min(roi_bgr.shape[:2]) < 20:
        return WindReading()

    deviation = _deviation_map(roi_bgr)
    _, ang, ring = _ring_indices(roi_bgr.shape[:2])
    direction, conf = _fan_sweep(deviation, ang, ring)
    return WindReading(value=None, direction_deg=direction, confidence=conf)
