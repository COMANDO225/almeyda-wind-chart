"""Detector de potencia (barra ROJA horizontal del HUD inferior).

El juego no muestra un número de potencia — solo una barra horizontal que se
llena de rojo desde la izquierda. Medimos el porcentaje calculando, columna a
columna, hasta qué punto la franja contiene píxeles rojos saturados.

Asunciones:
  - La ROI viene recortada exactamente al área interior del contorno de la
    barra (sin el borde gris/dorado de fuera).
  - El relleno es rojo saturado en HSV.
  - Crece de izquierda a derecha de forma monótona.
"""
from __future__ import annotations

import cv2
import numpy as np

from ..types import PowerReading


# Rojo en HSV cruza el 0 — se necesitan dos rangos.
RED_LO_1 = np.array([0,   110,  80], dtype=np.uint8)
RED_HI_1 = np.array([10,  255, 255], dtype=np.uint8)
RED_LO_2 = np.array([170, 110,  80], dtype=np.uint8)
RED_HI_2 = np.array([180, 255, 255], dtype=np.uint8)


def _red_mask(roi_bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, RED_LO_1, RED_HI_1) | cv2.inRange(hsv, RED_LO_2, RED_HI_2)
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))


def _last_filled_column(mask: np.ndarray, min_fill_ratio: float = 0.35) -> int:
    """Última columna cuyo % de píxeles rojos supera ``min_fill_ratio``.

    Devuelve -1 si ninguna columna llega al umbral (barra vacía).
    """
    if mask.size == 0:
        return -1
    col_ratios = mask.mean(axis=0) / 255.0
    filled = np.where(col_ratios >= min_fill_ratio)[0]
    return int(filled.max()) if filled.size else -1


def detect(roi_bgr: np.ndarray) -> PowerReading:
    if roi_bgr is None or roi_bgr.size == 0:
        return PowerReading()

    mask = _red_mask(roi_bgr)
    last_col = _last_filled_column(mask)
    if last_col < 0:
        return PowerReading(power_pct=0.0, confidence=0.0)

    width = roi_bgr.shape[1]
    pct = float(np.clip((last_col + 1) / width * 100.0, 0.0, 100.0))

    # Confianza: cuántas columnas tienen relleno significativo vs el ancho hasta last_col.
    total_red = int(mask.sum() / 255)
    expected = max(1, last_col * roi_bgr.shape[0])
    coverage = float(np.clip(total_red / expected, 0.0, 1.0))
    return PowerReading(power_pct=pct, confidence=coverage)
