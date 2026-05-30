"""Lector de angulo basado en la CNN de NUMERO COMPLETO (Camino 2).

Reemplaza a `cnn_digits` (segmentacion + clasificacion por digito) para el
angulo: una sola red lee el numero entero del recorte via `number_preprocess.
to_canvas` + el modelo ONNX `angle_number.onnx` (3 cabezas: sign/tens/ones).
Sin segmentar — elimina el cuello de botella del modelo viejo.

Singleton de la sesion ONNX: se carga una vez (lazy). Las salidas se leen por
NOMBRE (no por indice posicional) para no romperse si el exportador reordena.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import numpy as np

from .number_preprocess import VALID_MAX, VALID_MIN, reconstruct, to_canvas

log = logging.getLogger(__name__)

_MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "angle_number.onnx"

_lock = threading.Lock()
_session: object | None = None
_out_index: dict[str, int] | None = None
_warned_missing = False


def _get_session():
    """Carga la sesion ONNX una sola vez. Lanza FileNotFoundError si falta el
    modelo (el caller decide: aca no hay fallback)."""
    global _session, _out_index
    if _session is None:
        with _lock:
            if _session is None:
                import onnxruntime as ort

                if not _MODEL_PATH.exists():
                    raise FileNotFoundError(f"modelo no encontrado: {_MODEL_PATH}")
                log.info("cargando CNN de numero completo: %s", _MODEL_PATH)
                sess = ort.InferenceSession(str(_MODEL_PATH), providers=["CPUExecutionProvider"])
                _out_index = {o.name: i for i, o in enumerate(sess.get_outputs())}
                for name in ("sign", "tens", "ones"):
                    if name not in _out_index:
                        raise RuntimeError(
                            f"el modelo no expone la salida {name!r}; "
                            f"salidas: {list(_out_index)}"
                        )
                _session = sess
    return _session


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - x.max())
    return e / e.sum()


def read_angle(
    bgr: np.ndarray,
    *,
    min_value: int = VALID_MIN,
    max_value: int = VALID_MAX,
) -> tuple[int | None, float]:
    """Lee el angulo del recorte con la CNN de numero completo.

    Devuelve (value, confidence). value es None si el modelo falta, la imagen
    esta vacia, o la lectura cae fuera del rango legal (prior fuerte). La
    confianza es el producto de los 3 max-softmax (penaliza la incertidumbre
    combinada — ideal para el gate temporal del loop).
    """
    global _warned_missing
    if bgr is None or bgr.size == 0:
        return None, 0.0

    try:
        session = _get_session()
    except FileNotFoundError:
        if not _warned_missing:
            log.warning(
                "angle_number.onnx no existe — entrenalo con "
                "`python -m vision.training.train_number`. Sin lectura de angulo."
            )
            _warned_missing = True
        return None, 0.0

    canvas = to_canvas(bgr)
    batch = (canvas.astype(np.float32) / 255.0)[None, None, :, :]
    outs = session.run(None, {"input": batch})
    sign = _softmax(outs[_out_index["sign"]][0])
    tens = _softmax(outs[_out_index["tens"]][0])
    ones = _softmax(outs[_out_index["ones"]][0])

    value = reconstruct(int(sign.argmax()), int(tens.argmax()), int(ones.argmax()))
    if not (min_value <= value <= max_value):
        return None, 0.0

    conf = float(sign.max() * tens.max() * ones.max())
    log.debug("read_angle → %d (conf=%.2f)", value, conf)
    return value, conf
