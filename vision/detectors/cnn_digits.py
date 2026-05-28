"""Lector de numeros basado en la CNN custom (Sprint C.4).

Reemplaza a RapidOCR para el angulo: usa `segment_digits` (proyeccion
vertical) + el modelo ONNX entrenado (`digit_classifier.onnx`) para
clasificar cada digito, y arma el numero completo.

El signo "-" se detecta por GEOMETRIA (segment_digits ya marca `has_dash`),
no por la CNN. La CNN solo clasifica 0-9.

Ventajas sobre RapidOCR:
  * ~1 ms por inferencia (vs ~50-200 ms).
  * 611 KB (vs ~200 MB).
  * Entrenado especificamente con la fuente del juego.

Singleton de la sesion ONNX: se carga una vez (lazy).
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

import numpy as np

from .segment import DIGIT_SIZE, SegResult, segment_all

log = logging.getLogger(__name__)

_MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "digit_classifier.onnx"

_lock = threading.Lock()
_session: Optional[object] = None


def _get_session():
    global _session
    if _session is None:
        with _lock:
            if _session is None:
                import onnxruntime as ort

                if not _MODEL_PATH.exists():
                    raise FileNotFoundError(f"modelo no encontrado: {_MODEL_PATH}")
                log.info("cargando CNN de digitos: %s", _MODEL_PATH)
                _session = ort.InferenceSession(
                    str(_MODEL_PATH), providers=["CPUExecutionProvider"]
                )
    return _session


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - x.max())
    return e / e.sum()


def _classify(seg: SegResult) -> tuple[Optional[int], float]:
    """Clasifica los digitos de UNA segmentacion candidata con la CNN."""
    if not seg.digits:
        return None, 0.0
    session = _get_session()
    batch = np.stack(
        [d.astype(np.float32) / 255.0 for d in seg.digits]
    )[:, None, :, :].astype(np.float32)
    logits = session.run(None, {"input": batch})[0]  # (N, 10)

    digits, confs = [], []
    for row in logits:
        probs = _softmax(row)
        digits.append(str(int(probs.argmax())))
        confs.append(float(probs.max()))

    try:
        value = int("".join(digits))
    except ValueError:
        return None, 0.0
    if seg.has_dash:
        value = -value
    return value, (float(np.mean(confs)) if confs else 0.0)


def read_number(
    bgr: np.ndarray,
    *,
    min_value: int = -90,
    max_value: int = 90,
) -> tuple[Optional[int], float]:
    """Lee un numero del recorte probando TODAS las binarizaciones candidatas
    y eligiendo la lectura mas confiable dentro del rango valido.

    Aprovecha que la CNN es barata (~1 ms): en vez de depender de una sola
    segmentacion, clasifica las 3 candidatas y vota por confianza. Mucho mas
    robusto frente a binarizaciones que pierden/agregan un digito.
    """
    if bgr is None or bgr.size == 0:
        return None, 0.0

    candidates = segment_all(bgr)
    if not candidates:
        return None, 0.0

    best_val: Optional[int] = None
    best_conf = 0.0
    for seg in candidates:
        value, conf = _classify(seg)
        if value is None or not (min_value <= value <= max_value):
            continue
        # Bonus leve a candidatas con 1-2 digitos (rango tipico del angulo)
        # para desempatar contra lecturas de 3 digitos por ruido.
        plaus = conf + (0.05 if seg.digit_count <= 2 else 0.0)
        if plaus > best_conf:
            best_conf = plaus
            best_val = value

    if best_val is None:
        return None, 0.0
    log.debug("read_number → %d (conf=%.2f)", best_val, best_conf)
    return best_val, min(1.0, best_conf)
