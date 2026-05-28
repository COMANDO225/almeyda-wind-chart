"""Segmentacion de digitos individuales desde un recorte del HUD.

Compartido entre:
  * `scripts/prepare_dataset.py` (arma el dataset de entrenamiento)
  * el detector CNN final (C.4) en produccion

La consistencia es clave: si entrenamos con digitos segmentados de cierta
forma, el detector en produccion debe segmentar IGUAL. Por eso vive en un
solo lugar.

Estrategia:
  1. Gris + upscale (los digitos del HUD son chicos).
  2. Binarizar con Otsu; si el fondo queda mayoritariamente blanco, invertir
     para tener "texto blanco sobre negro" (lo que espera findContours).
  3. Encontrar contornos externos.
  4. Clasificar cada contorno como 'digit' o 'dash' (el signo "-"):
       - dash: ancho y bajo (aspect ratio alto, altura baja vs el mas alto)
       - digit: altura razonable, aspect ratio tipo digito
  5. Ordenar por X (izquierda a derecha).
  6. Normalizar cada digito a un cuadrado NxN con padding (mantiene aspecto).

`segment_digits` acepta `expected_digits`: si se pasa (lo conocemos en
preparacion porque tenemos el label), prueba varias binarizaciones y se
queda con la que produce exactamente esa cantidad de digitos — maximiza el
dataset utilizable. En produccion se llama sin ese parametro.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

# Tamano de salida de cada digito normalizado (cuadrado).
DIGIT_SIZE = 32

# Un contorno es "dash" (signo -) si es ancho/bajo.
DASH_AR_MIN = 1.8  # ancho / alto
DASH_MAX_REL_HEIGHT = 0.55  # altura <= 55% del contorno mas alto


@dataclass
class CharBox:
    x: int
    y: int
    w: int
    h: int
    kind: str  # "digit" | "dash"


def _binarize_variants(gray: np.ndarray) -> list[np.ndarray]:
    """Devuelve varias binarizaciones candidatas (texto blanco sobre negro)."""
    out = []
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, otsu_inv = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    for b in (otsu, otsu_inv):
        # Queremos texto en blanco (255) sobre fondo negro. Si hay mas blanco
        # que negro, probablemente el fondo es blanco -> ya cubierto por la
        # variante invertida, asi que solo aseguramos ambas presentes.
        out.append(b)
    # Adaptativo como tercera opcion (fondos con gradiente).
    adap = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 8
    )
    out.append(adap)
    return out


def _split_region(binary: np.ndarray, x0: int, x1: int, n: int) -> list[tuple[int, int]]:
    """Subdivide una region [x0,x1] en n digitos, cortando en los minimos
    locales de la proyeccion de columnas (donde los digitos se separan).
    Si no hay minimos claros, corta uniformemente."""
    if n <= 1:
        return [(x0, x1)]
    col = (binary[:, x0:x1] > 0).sum(axis=0).astype(np.float32)
    width = len(col)
    if width < n:
        return [(x0, x1)]
    cuts = []
    seg_w = width / n
    for k in range(1, n):
        center = int(seg_w * k)
        # Ventana de busqueda alrededor del corte teorico (+-30% del ancho de digito).
        half = max(1, int(seg_w * 0.3))
        lo = max(1, center - half)
        hi = min(width - 1, center + half)
        if hi <= lo:
            cut = center
        else:
            cut = lo + int(np.argmin(col[lo:hi]))
        cuts.append(cut)
    bounds = [0, *cuts, width]
    return [(x0 + bounds[i], x0 + bounds[i + 1]) for i in range(len(bounds) - 1)]


def _char_boxes(binary: np.ndarray) -> list[CharBox]:
    """Segmenta caracteres por PROYECCION VERTICAL (perfil de columnas).

    Sumamos pixeles de texto por columna. Los caracteres son "picos" de
    pixeles; los espacios entre ellos son "valles" (~0). Cortamos en los
    valles. Inmune a la fragmentacion vertical (un digito partido arriba/
    abajo sigue siendo una columna continua de pixeles), que es el problema
    que rompia findContours con la fuente del juego.
    """
    h_img, w_img = binary.shape[:2]
    # Cierre leve para tapar gaps horizontales chicos dentro de un trazo.
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    bin_closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    col_on = (bin_closed > 0).sum(axis=0)
    col_thresh = max(1, int(h_img * 0.04))  # min pixeles para considerar "texto"
    active = col_on > col_thresh

    # Agrupar columnas activas contiguas (permitiendo gaps de 1px).
    regions: list[tuple[int, int]] = []
    start = None
    gap = 0
    MAX_GAP = 1
    for i, on in enumerate(active):
        if on:
            if start is None:
                start = i
            gap = 0
        else:
            if start is not None:
                gap += 1
                if gap > MAX_GAP:
                    regions.append((start, i - gap + 1))
                    start = None
                    gap = 0
    if start is not None:
        regions.append((start, len(active)))

    # Paso 1: extraer bbox de cada region (SIN subdividir todavia).
    region_boxes: list[tuple[int, int, int, int]] = []
    for x0, x1 in regions:
        if x1 - x0 < 2:
            continue
        col_slice = bin_closed[:, x0:x1]
        rows = np.where(col_slice.sum(axis=1) > 0)[0]
        if len(rows) == 0:
            continue
        y0, y1 = int(rows[0]), int(rows[-1]) + 1
        if (y1 - y0) < 4:
            continue
        region_boxes.append((x0, y0, x1 - x0, y1 - y0))

    if not region_boxes:
        return []

    # Paso 2: max_h sobre las regiones (para clasificar dash vs digit).
    max_h = max(b[3] for b in region_boxes)

    # Paso 3: clasificar. El dash NO se subdivide. Los digitos anchos
    # (varios pegados) se subdividen por ancho esperado.
    boxes: list[CharBox] = []
    for x, y, w, h in region_boxes:
        ar = w / max(1, h)
        if ar >= DASH_AR_MIN and h <= max_h * DASH_MAX_REL_HEIGHT:
            boxes.append(CharBox(x, y, w, h, "dash"))
            continue
        if h < max_h * 0.45:
            continue  # ruido bajo que no es dash
        # Solo subdividir si la region es CLARAMENTE varios digitos pegados
        # (ancho >= 1.3x el alto). Conservador para no sobre-segmentar
        # digitos individuales anchos.
        if w >= h * 1.3:
            n_digits = max(2, int(round(w / (h * 0.75))))
            for sx0, sx1 in _split_region(bin_closed, x, x + w, n_digits):
                if sx1 - sx0 < 2:
                    continue
                sub = bin_closed[:, sx0:sx1]
                srows = np.where(sub.sum(axis=1) > 0)[0]
                if len(srows) == 0:
                    continue
                sy0, sy1 = int(srows[0]), int(srows[-1]) + 1
                if sy1 - sy0 < 4:
                    continue
                boxes.append(CharBox(sx0, sy0, sx1 - sx0, sy1 - sy0, "digit"))
        else:
            boxes.append(CharBox(x, y, w, h, "digit"))

    boxes.sort(key=lambda b: b.x)
    return boxes


def _normalize_digit(gray_bin: np.ndarray, box: CharBox, pad: int = 3) -> np.ndarray:
    """Recorta el digito y lo centra en un cuadrado DIGIT_SIZE con padding."""
    x0 = max(0, box.x - pad)
    y0 = max(0, box.y - pad)
    x1 = min(gray_bin.shape[1], box.x + box.w + pad)
    y1 = min(gray_bin.shape[0], box.y + box.h + pad)
    crop = gray_bin[y0:y1, x0:x1]
    h, w = crop.shape[:2]
    side = max(h, w)
    square = np.zeros((side, side), dtype=np.uint8)
    oy = (side - h) // 2
    ox = (side - w) // 2
    square[oy : oy + h, ox : ox + w] = crop
    return cv2.resize(square, (DIGIT_SIZE, DIGIT_SIZE), interpolation=cv2.INTER_AREA)


@dataclass
class SegResult:
    digits: list[np.ndarray]  # imagenes normalizadas DIGIT_SIZE x DIGIT_SIZE
    has_dash: bool
    strategy: str  # nombre de la binarizacion usada
    digit_count: int


def segment_digits(
    bgr: np.ndarray,
    *,
    expected_digits: Optional[int] = None,
    upscale: float = 4.0,
) -> Optional[SegResult]:
    """Segmenta los digitos de un recorte del HUD.

    Si `expected_digits` se pasa, prueba binarizaciones y se queda con la que
    produce exactamente esa cantidad de digitos. Si no, usa la primera que
    produzca >= 1 digito.

    Devuelve None si ninguna estrategia produce digitos validos.
    """
    if bgr is None or bgr.size == 0:
        return None
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    if upscale != 1.0:
        gray = cv2.resize(gray, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)

    best: Optional[SegResult] = None
    for i, binary in enumerate(_binarize_variants(gray)):
        boxes = _char_boxes(binary)
        digit_boxes = [b for b in boxes if b.kind == "digit"]
        has_dash = any(b.kind == "dash" for b in boxes)
        if not digit_boxes:
            continue
        digits = [_normalize_digit(binary, b) for b in digit_boxes]
        result = SegResult(
            digits=digits,
            has_dash=has_dash,
            strategy=["otsu", "otsu_inv", "adaptive"][i] if i < 3 else f"v{i}",
            digit_count=len(digit_boxes),
        )
        if expected_digits is not None:
            if len(digit_boxes) == expected_digits:
                return result  # match exacto, listo
            # guardar el mas cercano por si ninguno matchea exacto
            if best is None or abs(len(digit_boxes) - expected_digits) < abs(
                best.digit_count - expected_digits
            ):
                best = result
        else:
            if best is None:
                best = result
    return best


def segment_all(bgr: np.ndarray, *, upscale: float = 4.0) -> list[SegResult]:
    """Devuelve TODAS las segmentaciones candidatas (una por binarizacion).

    Para produccion: el caller (cnn_digits) clasifica cada candidata con la
    CNN y elige la lectura mas confiable. Aprovecha que la CNN es barata
    (~1 ms) para no depender de una sola binarizacion.
    """
    if bgr is None or bgr.size == 0:
        return []
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    if upscale != 1.0:
        gray = cv2.resize(gray, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)

    results: list[SegResult] = []
    names = ["otsu", "otsu_inv", "adaptive"]
    for i, binary in enumerate(_binarize_variants(gray)):
        boxes = _char_boxes(binary)
        digit_boxes = [b for b in boxes if b.kind == "digit"]
        if not digit_boxes:
            continue
        results.append(
            SegResult(
                digits=[_normalize_digit(binary, b) for b in digit_boxes],
                has_dash=any(b.kind == "dash" for b in boxes),
                strategy=names[i] if i < len(names) else f"v{i}",
                digit_count=len(digit_boxes),
            )
        )
    return results
