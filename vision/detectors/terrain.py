"""Detector de terreno (polígono de colisión del mapa).

Stub de Fase 0. En Fase 3+ se integra SAM 2 con prompts por click guardados
por mapa, y caché en disco para evitar reinferencia.
"""
from __future__ import annotations

import numpy as np

from ..types import TerrainPolygon


def detect(frame_bgr: np.ndarray) -> TerrainPolygon:  # noqa: ARG001
    return TerrainPolygon(points=[])
