"""Detector del NUMERO del viento — CNN custom (Camino 2 para wind_number).

Reemplaza el RapidOCR (~300 MB, ~50-200 ms por inferencia) por la CNN
multi-cabeza entrenada con el dataset sintetico del Almeyda Wind Visor
(~22k muestras, distribucion balanceada de los 51 valores 0-50, 6 etapas
de opacidad). ~1 MB de modelo, ~1 ms de inferencia.

El recorte que recibe el detector es el FRAME CIRCULAR ENTERO del
marker_wind (con la mascara aplicada por `CaptureShape::Circle` en Rust).
Antes de pasarlo al reader, recortamos el cuadrado CENTRAL al 80% — el
MISMO encuadre que el visor uso para generar las muestras (`CAP_FRAC=0.8`).
Asi train y runtime ven exactamente lo mismo.

CNN pura, sin fallback: si el modelo no carga retorna `WindReading()` vacio
y el loop conserva la ultima lectura emitida.
"""

from __future__ import annotations

import numpy as np

from ..types import WindReading
from .wind_number_reader import read_number


def detect(roi_bgr: np.ndarray) -> WindReading:
    if roi_bgr is None or roi_bgr.size == 0:
        return WindReading()

    # Recortar el cuadrado central al 80% del lado — replica EXACTO el crop
    # que el visor usa para generar las muestras (CAP_FRAC=0.8 en app.js).
    # Sin esto, el bbox de tinta del modelo agarraria tambien las marcas
    # naranjas del anillo exterior y el puntero, confundiendolo.
    h, w = roi_bgr.shape[:2]
    side = int(min(h, w) * 0.80)
    cx, cy = w // 2, h // 2
    x0 = max(0, cx - side // 2)
    y0 = max(0, cy - side // 2)
    center = roi_bgr[y0 : y0 + side, x0 : x0 + side]

    value, conf = read_number(center)
    if value is None:
        return WindReading()
    return WindReading(value=value, direction_deg=None, confidence=conf)
