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


def _strategy_edges(gray: np.ndarray) -> np.ndarray:
    """Canny edges + dilate + invert.

    Independiente de COLOR — solo usa gradientes. Robusto contra cambios
    de tema del juego (Halloween, Navidad, etc.). Devuelve "texto negro
    sobre fondo blanco" que es lo que prefiere el OCR.
    """
    edges = cv2.Canny(gray, 50, 150)
    kernel = np.ones((2, 2), np.uint8)
    dilated = cv2.dilate(edges, kernel, iterations=1)
    # Invertir: edges blancos sobre negro → digitos negros sobre blanco.
    return cv2.bitwise_not(dilated)


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


def auto_crop_digits(
    bgr: np.ndarray, padding: int = 4, drop_short_ratio: float = 0.6
) -> Optional[np.ndarray]:
    """Recorta al bbox de los DIGITOS, descartando caracteres mas bajos.

    Detecta contornos del texto con Otsu + findContours. Descarta los
    contornos cuya altura sea menor que ``drop_short_ratio`` veces la
    altura del contorno mas alto — esto elimina el simbolo "°" del HUD
    de angulo del juego (el ° es chiquito y vive arriba del numero, no
    es un digito).

    Resultado: una version del bgr recortada solo a los digitos. Si no
    encuentra contornos validos, devuelve None.

    Es **independiente de color** (B.1).
    """
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    # Otsu binarizacion. Si el resultado tiene fondo blanco mayoritario,
    # lo invertimos para que findContours encuentre el texto como blob.
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if binary.mean() > 127:
        binary = cv2.bitwise_not(binary)

    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    boxes = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        # Descartar ruido (muy chico).
        if w < 3 or h < 5 or w * h < 15:
            continue
        # Aspect ratio "tipo digito": los digitos del HUD del juego son
        # mas o menos cuadrados (0.3 a 1.2 ancho/alto). Esto descarta:
        #   - bordes verticales de cajillas (ratio ~0.05)
        #   - bordes horizontales / lineas (ratio > 2)
        #   - simbolos angostos como "I" o "|" del HUD
        ar = w / max(1, h)
        if ar < 0.30 or ar > 1.5:
            continue
        # Tambien filtramos contornos que ocupen MUY poca area del bbox
        # (formas degeneradas no son digitos).
        area_ratio = float(cv2.contourArea(c)) / max(1, w * h)
        if area_ratio < 0.15:
            continue
        boxes.append((x, y, w, h))

    if not boxes:
        return None

    # Filtrar por altura: los digitos son los contornos mas altos.
    # El "°" del HUD del angulo siempre es mucho mas bajo.
    max_h = max(b[3] for b in boxes)
    boxes = [b for b in boxes if b[3] >= max_h * drop_short_ratio]
    if not boxes:
        return None

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
    crop_digits: bool = False,
    debug_tag: str = "",
) -> tuple[Optional[int], float]:
    """Aísla dígitos de una imagen pequeña probando múltiples preprocesados.

    ``color``: si se pasa "yellow" o "green", añade un strategy específico
    para ese color además de los strategies generales (deprecated en B.1 —
    preferir ``crop_digits=True``).

    ``crop_digits``: si True, aplica ``auto_crop_digits`` antes de procesar
    para descartar caracteres "bajos" como el "°" del HUD del angulo. Es
    independiente de color (B.1).
    """
    if img_bgr is None or img_bgr.size == 0:
        return None, 0.0
    if img_bgr.ndim == 2:
        bgr = cv2.cvtColor(img_bgr, cv2.COLOR_GRAY2BGR)
    else:
        bgr = img_bgr.copy()

    # A.4 + B.1: crop por contornos (descarta "°" y otros caracteres bajos).
    if crop_digits:
        cropped = auto_crop_digits(bgr, padding=6)
        if cropped is not None and cropped.size:
            if debug_tag:
                _debug_save(cropped, f"{debug_tag}_digitcrop")
            bgr = cropped

    # (Legacy) Si se pasó un color, auto-recortar a esa zona.
    if color in ("yellow", "green"):
        cropped = auto_crop_color(bgr, color, padding=6)
        if cropped is not None and cropped.size:
            if debug_tag:
                _debug_save(cropped, f"{debug_tag}_colorcrop")
            bgr = cropped

    # Upscale después del auto-crop.
    if upscale != 1.0:
        bgr = cv2.resize(bgr, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    # Strategies default — independientes de color (B.1).
    candidates: list[tuple[str, np.ndarray]] = [
        ("otsu", _strategy_otsu(gray)),
        ("otsu_inv", _strategy_otsu_inv(gray)),
        ("adaptive", _strategy_adaptive(gray)),
        ("brightness", _strategy_brightness(bgr)),
        ("edges", _strategy_edges(gray)),  # nuevo en B.1
    ]
    # Color-specific solo si el caller los pide explicitamente (deprecated).
    if color == "yellow":
        candidates.append(("yellow_mask", _strategy_yellow(bgr)))
    if color == "green":
        candidates.append(("green_mask", _strategy_green(bgr)))

    if debug_tag:
        _debug_save(bgr, f"{debug_tag}_00_upscaled")

    # Acumular votos por valor: cada strategy aporta su score AJUSTADO al
    # valor que leyo. El ajuste penaliza lecturas con caracteres NO-digito
    # (ej. "C1" tiene fraccion 0.5 → score x 0.5). Mas robusto al voting que
    # solo tomar el de mayor confianza puntual.
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
                # Penalizar lecturas con basura alrededor de los digitos.
                # Si el OCR ve "C1", queremos peso 0.5 (1 digito / 2 chars).
                # Si ve "2", peso 1.0. Si ve "12abc", peso 0.4.
                digit_ratio = len(digits) / max(1, len(txt))
                adjusted = score * digit_ratio
                votes[val] = votes.get(val, 0.0) + adjusted

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
