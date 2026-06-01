"""Lector ONNX del PUNTERO del viento (Camino 2 para viento).

Reemplaza el detector geometrico `wind.py` (fan-sweep angular) por el modelo
CNN entrenado: `wind_pointer.onnx`. Una sola pasada del recorte del radar
da `(sin, cos)` y se decodifica a grados con `atan2`.

Sesion ONNX singleton (carga unica, ~1 ms por inferencia despues). Lee la
salida por NOMBRE (no por indice) por si el exportador la reordena. Sin
fallback: si el modelo no existe o falla, retorna `(None, 0.0)` y el loop
mantiene la ultima lectura.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import numpy as np

from .wind_pointer_preprocess import to_canvas, xy_to_angle

log = logging.getLogger(__name__)

_MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "wind_pointer.onnx"

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
                log.info("cargando CNN del puntero del viento: %s", _MODEL_PATH)
                sess = ort.InferenceSession(str(_MODEL_PATH), providers=["CPUExecutionProvider"])
                _out_index = {o.name: i for i, o in enumerate(sess.get_outputs())}
                if "sincos" not in _out_index:
                    raise RuntimeError(
                        f"el modelo no expone la salida 'sincos'; salidas: {list(_out_index)}"
                    )
                _session = sess
    return _session


def read_pointer(bgr: np.ndarray) -> tuple[float | None, float]:
    """Lee la direccion del puntero del recorte del radar.

    Devuelve (direction_deg, confidence). direction en [0, 360) con la
    convencion del proyecto (0=derecha, 90=abajo, horario). La confianza es
    la NORMA del vector (sin, cos) antes de normalizar; como el modelo
    siempre normaliza a |v|=1, salimos con norma ya 1.0 y reportamos eso
    como proxy de "el modelo respondio sin saturarse". En la practica la
    confianza util viene del suavizado/gate en el loop.
    """
    global _warned_missing
    if bgr is None or bgr.size == 0:
        return None, 0.0
    try:
        session = _get_session()
    except FileNotFoundError:
        if not _warned_missing:
            log.warning(
                "wind_pointer.onnx no existe — entrenalo con "
                "`python -m vision.training.train_wind_pointer`. Sin direccion del puntero."
            )
            _warned_missing = True
        return None, 0.0

    canvas = to_canvas(bgr)
    batch = (canvas.astype(np.float32) / 255.0)[None, None, :, :]
    outs = session.run(None, {"input": batch})
    sincos = outs[_out_index["sincos"]][0]
    sin_v, cos_v = float(sincos[0]), float(sincos[1])
    direction = xy_to_angle(sin_v, cos_v)
    # Norma del vector unitario predicho — siempre ~1.0 por diseño del modelo;
    # la usamos como confidence "siempre alta" y dejamos el filtrado real al loop.
    conf = float(min(1.0, (sin_v * sin_v + cos_v * cos_v) ** 0.5))
    return direction, conf
