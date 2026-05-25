"""Tipos compartidos entre detectores y el sidecar."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class Rect(BaseModel):
    x: int
    y: int
    w: int
    h: int

    def to_slice(self) -> tuple[slice, slice]:
        return slice(self.y, self.y + self.h), slice(self.x, self.x + self.w)


class Point(BaseModel):
    x: float
    y: float


class WindReading(BaseModel):
    value: Optional[int] = Field(None, description="Magnitud del viento (entero del HUD).")
    direction_deg: Optional[float] = Field(
        None, description="0° = derecha, 90° = abajo, sentido horario."
    )
    confidence: float = 0.0


class AngleReading(BaseModel):
    angle_deg: Optional[int] = None
    confidence: float = 0.0


class PowerReading(BaseModel):
    power_pct: Optional[float] = Field(None, ge=0.0, le=100.0)
    confidence: float = 0.0


class MobileDetection(BaseModel):
    name: str = "unknown"
    position: Point
    team: Literal["self", "ally", "enemy", "unknown"] = "unknown"
    confidence: float = 0.0


class TerrainPolygon(BaseModel):
    points: list[Point] = []


class GameState(BaseModel):
    """Estado completo emitido por el pipeline para un frame."""

    frame_id: int = 0
    wind: WindReading = WindReading()
    angle: AngleReading = AngleReading()
    power: PowerReading = PowerReading()
    mobiles: list[MobileDetection] = []
    terrain: TerrainPolygon = TerrainPolygon()


class ROIConfig(BaseModel):
    """ROIs configuradas por el usuario (corners + power-box)."""

    game_area: Rect
    wind_indicator: Optional[Rect] = None
    power_bar: Optional[Rect] = None
    angle_hud: Optional[Rect] = None
