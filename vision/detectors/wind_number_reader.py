"""Lector ONNX del NUMERO del viento (Camino 2 para wind_number).

Reemplaza el `read_digits` con RapidOCR por el modelo CNN multi-cabeza
entrenado: `wind_number.onnx` (2 salidas: tens, ones). Una sola pasada del
recorte central del radar da (tens, ones) y se reconstruye el numero.

Sesion ONNX singleton (carga unica, ~1 ms por inferencia despues). Lee las
salidas por NOMBRE (no por indice) por si el exportador las reordena. Sin
fallback: si el modelo falta o falla, retorna (None, 0.0) y el loop mantiene
la ultima lectura emitida.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import numpy as np

from .wind_number_preprocess import VALID_MAX, VALID_MIN, reconstruct, to_canvas

log = logging.getLogger(__name__)

_MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "wind_number.onnx"

_lock = threading.Lock()
_session: object | None = None
_out_index: dict[str, int] | None = None
_warned_missing = False


def _get_session():
    global _session, _out_index
    if _session is None:
        with _lock:
            if _session is None:
                import onnxruntime as ort

                if not _MODEL_PATH.exists():
                    raise FileNotFoundError(f"modelo no encontrado: {_MODEL_PATH}")
                log.info("cargando CNN del numero del viento: %s", _MODEL_PATH)
                sess = ort.InferenceSession(str(_MODEL_PATH), providers=["CPUExecutionProvider"])
                _out_index = {o.name: i for i, o in enumerate(sess.get_outputs())}
                for name in ("tens", "ones"):
                    if name not in _out_index:
                        raise RuntimeError(
                            f"el modelo no expone la salida {name!r}; salidas: {list(_out_index)}"
                        )
                _session = sess
    return _session


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - x.max())
    return e / e.sum()


def read_number(
    bgr: np.ndarray,
    *,
    min_value: int = VALID_MIN,
    max_value: int = VALID_MAX,
) -> tuple[int | None, float]:
    """Lee el numero del viento del recorte (centro del radar, sin el anillo).

    Devuelve (value, confidence). value es None si el modelo falta, la imagen
    esta vacia, o la lectura cae fuera del rango legal (prior fuerte). La
    confianza es el producto de los 2 max-softmax (penaliza incertidumbre
    combinada — ideal para gate temporal en el loop).
    """
    global _warned_missing
    if bgr is None or bgr.size == 0:
        return None, 0.0
    try:
        session = _get_session()
    except FileNotFoundError:
        if not _warned_missing:
            log.warning(
                "wind_number.onnx no existe — entrenalo con "
                "`python -m vision.training.train_wind_number`. Sin lectura del numero."
            )
            _warned_missing = True
        return None, 0.0

    canvas = to_canvas(bgr)
    batch = (canvas.astype(np.float32) / 255.0)[None, None, :, :]
    outs = session.run(None, {"input": batch})
    tens = _softmax(outs[_out_index["tens"]][0])
    ones = _softmax(outs[_out_index["ones"]][0])

    value = reconstruct(int(tens.argmax()), int(ones.argmax()))
    if not (min_value <= value <= max_value):
        return None, 0.0
    conf = float(tens.max() * ones.max())
    log.debug("wind_number → %d (conf=%.2f)", value, conf)
    return value, conf
