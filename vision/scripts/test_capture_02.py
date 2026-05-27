"""Test del pipeline OCR contra la captura 02_aero_trico-vs-armor_a77_p75_w02.png.

Ground truth:  ángulo=77°, viento=2, potencia=75%.

Esta captura es de 1714x1285 px (grabada con Win+Shift+S en monitor del usuario).
En el flujo REAL de la app, los markers son pequeños (~40x40 px) y capturan
regiones en vivo de la pantalla. Esto es solo un test offline para confirmar
que RapidOCR lee los dígitos del HUD del juego.

Ejecutar (desde la raíz del proyecto, con el venv activo):
    .\\.venv\\Scripts\\python.exe -m vision.scripts.test_capture_02
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import cv2

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SAMPLE = PROJECT_ROOT / "assets" / "samples" / "02_aero_trico-vs-armor_a77_p75_w02.png"


def main() -> int:
    if not SAMPLE.exists():
        print(f"FALLO: no encuentro {SAMPLE}", file=sys.stderr)
        return 1
    img = cv2.imread(str(SAMPLE), cv2.IMREAD_COLOR)
    if img is None:
        print(f"FALLO: cv2 no pudo leer {SAMPLE}", file=sys.stderr)
        return 1

    h, w = img.shape[:2]
    print(f"Captura: {w}x{h} px")

    # Coords del "77" amarillo. Más ancho para incluir AMBOS dígitos.
    angle_roi = img[1120:1195, 470:640]
    wind_roi = img[35:115, 790:880]

    out_dir = PROJECT_ROOT / "assets" / "samples" / "_debug"
    out_dir.mkdir(exist_ok=True)
    cv2.imwrite(str(out_dir / "02_angle_roi.png"), angle_roi)
    cv2.imwrite(str(out_dir / "02_wind_roi.png"), wind_roi)
    print(f"ROIs guardadas en {out_dir}")

    from vision.detectors.angle import detect as detect_angle
    from vision.detectors.wind import detect as detect_wind  # solo direccion
    from vision.detectors.wind_number import detect as detect_wind_num  # solo numero

    print("\n--- Detector de angulo ---")
    angle = detect_angle(angle_roi)
    print(f"  Esperado: 77")
    print(f"  Detectado: {angle.angle_deg} (confianza={angle.confidence:.2f})")

    print("\n--- Detectores de viento (DOS FLUJOS sobre el mismo frame) ---")
    wind_dir = detect_wind(wind_roi)        # geometria (puntero)
    wind_val = detect_wind_num(wind_roi)    # OCR (numero)
    print(f"  Esperado: valor=2, dir~90 grados (sur)")
    print(
        f"  Detectado: valor={wind_val.value} (conf={wind_val.confidence:.2f}) "
        f"dir={wind_dir.direction_deg} (conf={wind_dir.confidence:.2f})"
    )

    ok_angle = angle.angle_deg == 77
    ok_wind = wind_val.value == 2
    print(f"\n{'PASS' if ok_angle else 'FAIL'} angulo (esperado 77, leido {angle.angle_deg})")
    print(f"{'PASS' if ok_wind else 'FAIL'} viento (esperado 2, leido {wind_val.value})")
    return 0 if (ok_angle and ok_wind) else 2


if __name__ == "__main__":
    raise SystemExit(main())
