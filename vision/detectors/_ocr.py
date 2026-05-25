"""Singleton del motor OCR + utilidades de lectura de dígitos.

Motor: **RapidOCR v3** (modelos PaddleOCR PP-OCRv4 sobre ONNX Runtime).
  - ~200 MB. 1.5–2× más rápido que paddleocr+paddlepaddle.
  - Modelos se descargan on-demand al primer ``RapidOCR()`` (~15 MB).

``read_digits`` prueba VARIAS estrategias de preprocesado (Otsu, canal de
luminancia, color-targeted) y devuelve la lectura con mayor confianza. Esto
da resistencia frente a fondos complejos del HUD del juego (verde sobre
dorado, amarillo sobre negro semitransparente, etc.).
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Optional

import cv2
import numpy as np

log = logging.getLogger(__name__)

_engine_lock = threading.Lock()
_engine: Optional[object] = None


def get_engine():
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                from rapidocr import RapidOCR

                log.info("inicializando motor RapidOCR (primera vez puede tardar)")
                _engine = RapidOCR()
                log.info("motor RapidOCR listo")
    return _engine


# Guardar imágenes preprocesadas a disco para debug.
# Activar con: $env:VISION_DEBUG_DIR = 'C:\projects\ai-dragonbound\assets\samples\_debug'
def _debug_save(img: np.ndarray, tag: str) -> None:
    dbg_dir = os.environ.get("VISION_DEBUG_DIR")
    if not dbg_dir:
        return
    os.makedirs(dbg_dir, exist_ok=True)
    cv2.imwrite(os.path.join(dbg_dir, f"_ocr_{tag}.png"), img)


def _strategy_otsu(gray: np.ndarray) -> np.ndarray:
    _, bin_ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return bin_


def _strategy_otsu_inv(gray: np.ndarray) -> np.ndarray:
    """Otsu invertido — útil cuando el texto es claro sobre fondo oscuro."""
    _, bin_ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return bin_


def _strategy_adaptive(gray: np.ndarray) -> np.ndarray:
    return cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 8
    )


def _strategy_brightness(bgr: np.ndarray) -> np.ndarray:
    """Aísla píxeles brillantes (V alto en HSV). Bueno para texto brillante sobre cualquier fondo."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    v = hsv[..., 2]
    _, bin_ = cv2.threshold(v, 180, 255, cv2.THRESH_BINARY)
    return bin_


def _strategy_yellow(bgr: np.ndarray) -> np.ndarray:
    """Produce 'texto negro sobre fondo blanco' aislando amarillo del HUD."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([15, 100, 100]), np.array([40, 255, 255]))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    out = np.full(mask.shape, 255, dtype=np.uint8)
    out[mask > 0] = 0
    return out


def _strategy_green(bgr: np.ndarray) -> np.ndarray:
    """Produce 'texto negro sobre fondo blanco' aislando verde del HUD."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([35, 80, 80]), np.array([85, 255, 255]))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    out = np.full(mask.shape, 255, dtype=np.uint8)
    out[mask > 0] = 0
    return out


def auto_crop_color(
    bgr: np.ndarray, color: str, padding: int = 4
) -> Optional[np.ndarray]:
    """Recorta automáticamente la zona de los **contornos más grandes** del color.

    Idea: el texto "objetivo" del HUD (ej. el "77" amarillo grande) tiene
    contornos significativamente más grandes que otros elementos del mismo
    color (números pequeños tipo "+590", "LAST 55"). Tomamos solo los
    contornos cuya área es ≥ 50% del más grande — eso aísla los dígitos
    del número principal y descarta texto secundario.

    Si hay un único contorno o todos son chicos, retorna None.
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    if color == "yellow":
        mask = cv2.inRange(hsv, np.array([15, 100, 100]), np.array([40, 255, 255]))
    elif color == "green":
        mask = cv2.inRange(hsv, np.array([35, 80, 80]), np.array([85, 255, 255]))
    else:
        return None
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    # Ordenar por área DESC y quedarnos con los contornos "grandes":
    # ≥ 50% del más grande y ≥ 30 px² absolutos.
    areas = sorted(((cv2.contourArea(c), c) for c in contours), key=lambda x: -x[0])
    if not areas or areas[0][0] < 30:
        return None
    threshold = max(30.0, areas[0][0] * 0.5)
    big = [c for area, c in areas if area >= threshold]
    if not big:
        return None

    boxes = [cv2.boundingRect(c) for c in big]
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    h, w = bgr.shape[:2]
    x0 = max(0, x0 - padding)
    y0 = max(0, y0 - padding)
    x1 = min(w, x1 + padding)
    y1 = min(h, y1 + padding)
    if x1 <= x0 or y1 <= y0:
        return None
    return bgr[y0:y1, x0:x1].copy()


def _ocr_text_with_score(img: np.ndarray) -> list[tuple[str, float]]:
    """Llama a RapidOCR con detector FULL — encuentra cada dígito como caja
    separada. Si el detector no encuentra nada, fallback a rec-only.
    El "77" del juego tiene un gap entre los dos 7s que rec-only confunde
    con un solo carácter — el detector full les ve como cajas separadas.
    """
    engine = get_engine()
    try:
        result = engine(img, use_det=True, use_cls=False, use_rec=True)
    except Exception as e:  # noqa: BLE001
        log.debug("RapidOCR detector full falló: %s", e)
        result = None

    txts = getattr(result, "txts", None) if result else None
    if txts:
        scores = getattr(result, "scores", None) or []
        return list(zip([str(t) for t in txts], [float(s) for s in scores]))

    # Fallback: rec-only — para imágenes de un solo carácter o cuando el
    # detector no encuentra cajas (común con fuentes pixeladas del juego).
    try:
        result = engine(img, use_det=False, use_cls=False, use_rec=True)
    except Exception as e:  # noqa: BLE001
        log.debug("RapidOCR rec-only falló: %s", e)
        return []
    txts = getattr(result, "txts", None) or []
    scores = getattr(result, "scores", None) or []
    return list(zip([str(t) for t in txts], [float(s) for s in scores]))


def read_digits(
    img_bgr: np.ndarray,
    *,
    upscale: float = 4.0,
    min_value: int = 0,
    max_value: int = 999,
    color: Optional[str] = None,
    debug_tag: str = "",
) -> tuple[Optional[int], float]:
    """Aísla dígitos de una imagen pequeña probando múltiples preprocesados.

    ``color``: si se pasa "yellow" o "green", añade un strategy específico
    para ese color además de los strategies generales (más robusto).
    """
    if img_bgr is None or img_bgr.size == 0:
        return None, 0.0
    if img_bgr.ndim == 2:
        bgr = cv2.cvtColor(img_bgr, cv2.COLOR_GRAY2BGR)
    else:
        bgr = img_bgr.copy()

    # Si se pasó un color, intentar auto-recortar a la zona de ese color ANTES
    # de upscalear. Esto resuelve el caso "ROI grande con texto pequeño".
    if color in ("yellow", "green"):
        cropped = auto_crop_color(bgr, color, padding=6)
        if cropped is not None and cropped.size:
            if debug_tag:
                _debug_save(cropped, f"{debug_tag}_autocrop")
            bgr = cropped

    # Upscale después del auto-crop.
    if upscale != 1.0:
        bgr = cv2.resize(bgr, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    candidates: list[tuple[str, np.ndarray]] = [
        ("otsu", _strategy_otsu(gray)),
        ("otsu_inv", _strategy_otsu_inv(gray)),
        ("adaptive", _strategy_adaptive(gray)),
        ("brightness", _strategy_brightness(bgr)),
    ]
    if color == "yellow":
        candidates.append(("yellow_mask", _strategy_yellow(bgr)))
    if color == "green":
        candidates.append(("green_mask", _strategy_green(bgr)))

    if debug_tag:
        _debug_save(bgr, f"{debug_tag}_00_upscaled")

    # Acumular votos por valor: cada strategy aporta su score al valor que
    # leyó. El valor con mayor suma de scores gana — más robusto que solo
    # tomar el de mayor confianza puntual (que puede ser un falso positivo).
    votes: dict[int, float] = {}
    raw_log: list[tuple[str, str, float]] = []
    for strategy_name, img in candidates:
        if debug_tag:
            _debug_save(img, f"{debug_tag}_{strategy_name}")
        for txt, score in _ocr_text_with_score(img):
            raw_log.append((strategy_name, txt, score))
            digits = "".join(ch for ch in txt if ch.isdigit())
            if not digits:
                continue
            try:
                val = int(digits)
            except ValueError:
                continue
            if min_value <= val <= max_value:
                votes[val] = votes.get(val, 0.0) + score

    if not votes:
        log.debug("read_digits[%s] → None (raw=%s)", debug_tag or "?", raw_log)
        return None, 0.0

    best_val = max(votes, key=lambda v: votes[v])
    best_conf = float(min(1.0, votes[best_val] / max(1, len(candidates))))
    log.debug(
        "read_digits[%s] → %d (votos=%s, raw=%s)",
        debug_tag or "?",
        best_val,
        votes,
        raw_log,
    )
    return best_val, best_conf
