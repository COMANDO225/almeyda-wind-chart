"""Detector del medidor de viento.

El indicador del juego es un círculo en la zona superior con:
  - Un número entero al centro (magnitud del viento, 0–99).
  - Una flecha pequeña roja DENTRO del mismo círculo apuntando 360° hacia
    la dirección del viento. A veces saturada, a veces semitransparente.

Estrategia de dirección (dos pasadas):
  1. Aguja roja: máscara HSV de rojo saturado. Si la encuentra, usa el
     momento de los píxeles para calcular el ángulo.
  2. Fallback: PCA pesado sobre la desviación del patrón radial. Robusto
     cuando la aguja es transparente o tiene color cambiante.

Estrategia de magnitud: RapidOCR sobre el cuadrado central del círculo
(donde vive el número), con preprocesado de upscale + Otsu.
"""
from __future__ import annotations

import logging
from typing import Optional

import cv2
import numpy as np

from ..types import WindReading
from ._ocr import read_digits

log = logging.getLogger(__name__)


# Rojo en HSV cruza el 0 — dos rangos.
RED_LO_1 = np.array([0, 140, 110], dtype=np.uint8)
RED_HI_1 = np.array([10, 255, 255], dtype=np.uint8)
RED_LO_2 = np.array([170, 140, 110], dtype=np.uint8)
RED_HI_2 = np.array([180, 255, 255], dtype=np.uint8)


def _ring_mask(shape: tuple[int, int]) -> np.ndarray:
    """Máscara booleana del anillo entre 20% y 55% del radio del círculo."""
    h, w = shape
    cx, cy = w / 2.0, h / 2.0
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    radius = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    inner = min(h, w) * 0.20
    outer = min(h, w) * 0.55
    return (radius >= inner) & (radius <= outer)


def _direction_from_red_needle(roi_bgr: np.ndarray) -> tuple[Optional[float], float]:
    h, w = roi_bgr.shape[:2]
    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, RED_LO_1, RED_HI_1) | cv2.inRange(hsv, RED_LO_2, RED_HI_2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))

    ring = _ring_mask((h, w))
    candidates = mask.astype(bool) & ring
    pts = np.argwhere(candidates)
    if len(pts) < 6:
        return None, 0.0
    cx, cy = w / 2.0, h / 2.0
    my = float(pts[:, 0].mean()) - cy
    mx = float(pts[:, 1].mean()) - cx
    deg = float(np.degrees(np.arctan2(my, mx))) % 360.0
    conf = float(min(1.0, len(pts) / 80.0))
    return deg, conf


def _direction_from_deviation(roi_bgr: np.ndarray) -> tuple[Optional[float], float]:
    h, w = roi_bgr.shape[:2]
    if h < 10 or w < 10:
        return None, 0.0
    gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    blurred = cv2.GaussianBlur(gray, (0, 0), sigmaX=h / 6.0)
    deviation = np.abs(gray - blurred)

    ring = _ring_mask((h, w)).astype(np.float32)
    weights = deviation * ring
    total = float(weights.sum())
    if total < 1.0:
        return None, 0.0

    cx, cy = w / 2.0, h / 2.0
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    mx = float((xx * weights).sum() / total)
    my = float((yy * weights).sum() / total)
    deg = float(np.degrees(np.arctan2(my - cy, mx - cx))) % 360.0
    conf = float(min(1.0, total / (ring.sum() * 30.0)))
    return deg, conf


def _read_magnitude(roi_bgr: np.ndarray) -> tuple[Optional[int], float]:
    """OCR sobre el cuadrado central del círculo (donde vive el número)."""
    h, w = roi_bgr.shape[:2]
    side = int(min(h, w) * 0.6)
    cx, cy = w // 2, h // 2
    x0 = max(0, cx - side // 2)
    y0 = max(0, cy - side // 2)
    center = roi_bgr[y0 : y0 + side, x0 : x0 + side]
    return read_digits(
        center, upscale=4.0, min_value=0, max_value=99, color="green", debug_tag="wind"
    )


def detect(roi_bgr: np.ndarray) -> WindReading:
    direction, dir_conf = _direction_from_red_needle(roi_bgr)
    if direction is None or dir_conf < 0.15:
        direction, dir_conf = _direction_from_deviation(roi_bgr)

    magnitude, mag_conf = _read_magnitude(roi_bgr)
    return WindReading(
        value=magnitude,
        direction_deg=direction,
        confidence=float(np.mean([dir_conf, mag_conf])),
    )
