"""Smoke tests del pipeline sin requerir PaddleOCR ni capturas reales.

Estos tests validan que el cableado funciona: que ``process_frame`` no
explota sobre imágenes sintéticas y devuelve un ``GameState`` válido.

Ejecutar:  python -m pytest vision/tests -q
"""
from __future__ import annotations

import numpy as np

from vision.pipeline import process_frame
from vision.types import GameState, Rect, ROIConfig


def _blank_frame(w: int = 320, h: int = 240) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)


def test_process_frame_returns_state_on_blank_image() -> None:
    cfg = ROIConfig(
        game_area=Rect(x=0, y=0, w=320, h=240),
        wind_indicator=Rect(x=0, y=0, w=40, h=40),
        power_bar=Rect(x=100, y=100, w=40, h=40),
        angle_hud=Rect(x=50, y=50, w=40, h=20),
    )
    state = process_frame(_blank_frame(), cfg, frame_id=42)
    assert isinstance(state, GameState)
    assert state.frame_id == 42
    # En un frame en negro no hay nada que detectar — los campos quedan vacíos.
    assert state.wind.value is None
    assert state.angle.angle_deg is None
    assert (state.power.power_pct or 0.0) == 0.0
    assert state.mobiles == []


def test_power_detector_on_synthetic_red_bar() -> None:
    """Pintamos una barra roja horizontal y validamos que el detector lee ~50%."""
    import cv2

    from vision.detectors.power import detect

    img = np.zeros((20, 200, 3), dtype=np.uint8)
    cv2.rectangle(img, (0, 0), (100, 19), (0, 0, 255), thickness=-1)  # mitad llena
    reading = detect(img)
    assert reading.power_pct is not None
    assert 40.0 <= reading.power_pct <= 60.0
