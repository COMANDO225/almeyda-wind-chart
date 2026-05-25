"""Detector de mobiles (avatares de jugadores).

Estrategia inicial: **template matching multi-escala** sobre los sprites en
``assets/mobiles/``. Se devuelve la lista de detecciones por encima de un
umbral con supresión no máxima básica.

Más adelante (Fase 4+) este módulo se reemplaza por un modelo YOLOv11 ONNX
entrenado con ~200–500 capturas etiquetadas a mano — la interfaz pública
(``detect(frame_bgr)``) se mantiene.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import cv2
import numpy as np

from ..types import MobileDetection, Point


TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "assets" / "mobiles"
MATCH_THRESHOLD = 0.78
NMS_IOU = 0.3
SCALES: tuple[float, ...] = (0.75, 0.9, 1.0, 1.1, 1.25)


def _load_templates() -> list[tuple[str, np.ndarray]]:
    if not TEMPLATES_DIR.exists():
        return []
    out: list[tuple[str, np.ndarray]] = []
    for p in TEMPLATES_DIR.iterdir():
        if p.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            continue
        img = cv2.imread(str(p), cv2.IMREAD_COLOR)
        if img is not None:
            out.append((p.stem, img))
    return out


def _nms(detections: list[tuple[str, float, int, int, int, int]]) -> list[tuple[str, float, int, int, int, int]]:
    """NMS clásico sobre rectángulos (x, y, w, h)."""
    if not detections:
        return []
    boxes = np.array([[x, y, x + w, y + h] for _, _, x, y, w, h in detections], dtype=np.float32)
    scores = np.array([s for _, s, *_ in detections], dtype=np.float32)
    indices = cv2.dnn.NMSBoxes(boxes.tolist(), scores.tolist(), MATCH_THRESHOLD, NMS_IOU)
    if len(indices) == 0:
        return []
    keep = [int(i) for i in np.array(indices).flatten()]
    return [detections[i] for i in keep]


def _match_template(frame_bgr: np.ndarray, name: str, tmpl: np.ndarray) -> Iterable[tuple[str, float, int, int, int, int]]:
    th, tw = tmpl.shape[:2]
    for scale in SCALES:
        new_w = int(tw * scale)
        new_h = int(th * scale)
        if new_w < 10 or new_h < 10:
            continue
        scaled = cv2.resize(tmpl, (new_w, new_h), interpolation=cv2.INTER_AREA)
        if scaled.shape[0] > frame_bgr.shape[0] or scaled.shape[1] > frame_bgr.shape[1]:
            continue
        result = cv2.matchTemplate(frame_bgr, scaled, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(result >= MATCH_THRESHOLD)
        for x, y in zip(xs, ys):
            score = float(result[y, x])
            yield name, score, int(x), int(y), new_w, new_h


def detect(frame_bgr: np.ndarray) -> list[MobileDetection]:
    if frame_bgr is None or frame_bgr.size == 0:
        return []
    templates = _load_templates()
    raw: list[tuple[str, float, int, int, int, int]] = []
    for name, tmpl in templates:
        raw.extend(_match_template(frame_bgr, name, tmpl))
    kept = _nms(raw)
    return [
        MobileDetection(
            name=name,
            position=Point(x=x + w / 2.0, y=y + h / 2.0),
            confidence=score,
        )
        for name, score, x, y, w, h in kept
    ]
