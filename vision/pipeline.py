"""Compone los detectores en un único estado de juego por frame."""
from __future__ import annotations

import logging

import numpy as np

from .detectors import angle, mobiles, power, terrain, wind
from .types import GameState, ROIConfig

log = logging.getLogger(__name__)


def _crop(frame_bgr: np.ndarray, rect) -> np.ndarray:
    if rect is None:
        return np.empty((0, 0, 3), dtype=np.uint8)
    sy, sx = rect.to_slice()
    return frame_bgr[sy, sx].copy()


def process_frame(frame_bgr: np.ndarray, cfg: ROIConfig, frame_id: int = 0) -> GameState:
    """Ejecuta todos los detectores sobre un frame y devuelve el estado completo."""
    game_area = _crop(frame_bgr, cfg.game_area)

    wind_roi = _crop(frame_bgr, cfg.wind_indicator) if cfg.wind_indicator else np.empty((0, 0, 3), dtype=np.uint8)
    power_roi = _crop(frame_bgr, cfg.power_bar) if cfg.power_bar else np.empty((0, 0, 3), dtype=np.uint8)
    angle_roi = _crop(frame_bgr, cfg.angle_hud) if cfg.angle_hud else np.empty((0, 0, 3), dtype=np.uint8)

    state = GameState(frame_id=frame_id)
    if wind_roi.size:
        state.wind = wind.detect(wind_roi)
    if power_roi.size:
        state.power = power.detect(power_roi)
    if angle_roi.size:
        state.angle = angle.detect(angle_roi)
    if game_area.size:
        state.mobiles = mobiles.detect(game_area)
        state.terrain = terrain.detect(game_area)

    return state
