"""CLI / sidecar del pipeline de visión.

Modos:

  ``detect``  — procesa una imagen estática y emite JSON por stdout.
                Útil para Fase 0 (validación sobre capturas).

  ``serve``   — lee frames desde stdin (un PNG en base64 por línea) y emite
                un JSON de ``GameState`` por línea de stdout. Listo para ser
                el sidecar de la app Tauri en Fase 2.

Uso de ejemplo (Fase 0):

    python -m vision.main detect \\
        --image assets/samples/frame_001.png \\
        --config assets/samples/frame_001.roi.json
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import sys
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from .pipeline import process_frame
from .types import ROIConfig

log = logging.getLogger("vision")


def _load_image(path: Path) -> np.ndarray:
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"No se pudo leer la imagen: {path}")
    return img


def _load_config(path: Optional[Path]) -> ROIConfig:
    if path is None:
        raise SystemExit("--config es obligatorio en modo detect")
    return ROIConfig.model_validate_json(path.read_text(encoding="utf-8"))


def _decode_b64_png(b64: str) -> np.ndarray:
    raw = base64.b64decode(b64)
    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Frame base64 inválido (decode falló).")
    return img


def cmd_detect(args: argparse.Namespace) -> int:
    cfg = _load_config(Path(args.config) if args.config else None)
    frame = _load_image(Path(args.image))
    state = process_frame(frame, cfg)
    sys.stdout.write(state.model_dump_json(indent=2 if args.pretty else None))
    sys.stdout.write("\n")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:  # noqa: ARG001
    """Loop sidecar. Una línea de stdin = un mensaje JSON, una línea de stdout = una respuesta JSON.

    Formato del mensaje (lo que manda Tauri/Rust):
        {"type": "frame",
         "detector": "wind" | "angle",
         "frame_id": int, "png_b64": str}

    El PNG viene YA RECORTADO al ROI del marker. Cada frame trae el detector
    que se le aplica. Para "wind", el sidecar ejecuta DOS FLUJOS sobre el
    mismo frame circular: puntero + numero, y devuelve ambos resultados.

    Respuesta (lo que Rust deserializa en `DetectResponse`):
        {"wind":  {"value": int|null, "direction_deg": float|null, "confidence": float}}
        {"angle": {"value": int|null, "confidence": float}}
    """
    from .detectors import angle as angle_det
    from .detectors import wind as wind_det
    from .detectors import wind_number as wind_num_det

    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError as e:
            sys.stderr.write(f"[serve] JSON inválido: {e}\n")
            continue

        if msg.get("type") != "frame":
            sys.stderr.write(f"[serve] tipo desconocido: {msg.get('type')!r}\n")
            continue
        detector = msg.get("detector")
        try:
            frame = _decode_b64_png(msg["png_b64"])
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"[serve] decode falló: {e}\n")
            continue

        response: dict = {}
        if detector == "wind":
            # DOS FLUJOS SOBRE EL MISMO FRAME:
            #   - puntero: geometria pura, sin OCR (instantaneo)
            #   - numero: OCR sobre el centro del circulo
            # Ambos rapidos, combinamos resultados en un solo WindReading.
            pointer = wind_det.detect(frame)
            number = wind_num_det.detect(frame)
            conf_parts = [c for c in (pointer.confidence, number.confidence) if c > 0]
            response["wind"] = {
                "value": number.value,
                "direction_deg": pointer.direction_deg,
                "confidence": sum(conf_parts) / len(conf_parts) if conf_parts else 0.0,
            }
        elif detector == "angle":
            r = angle_det.detect(frame)
            response["angle"] = {"value": r.angle_deg, "confidence": r.confidence}
        else:
            sys.stderr.write(f"[serve] detector desconocido: {detector!r}\n")
            response = {}

        sys.stdout.write(json.dumps(response))
        sys.stdout.write("\n")
        sys.stdout.flush()
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="vision", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_detect = sub.add_parser("detect", help="Procesar imagen estática.")
    p_detect.add_argument("--image", required=True)
    p_detect.add_argument("--config", required=True, help="Ruta a ROIConfig JSON.")
    p_detect.add_argument("--pretty", action="store_true")
    p_detect.set_defaults(func=cmd_detect)

    p_serve = sub.add_parser("serve", help="Modo sidecar stdin/stdout.")
    p_serve.add_argument("--config", help="ROIConfig inicial opcional.")
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
