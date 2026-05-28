"""Prepara el dataset de digitos individuales para entrenar la CNN (Sprint C.3).

Lee `labels_<detector>.json`, y por cada captura:
  1. Segmenta los digitos con `segment_digits` (conociendo el count esperado).
  2. Valida que la cantidad de digitos segmentados coincida con el label.
  3. Si coincide: guarda cada digito normalizado en
     `assets/dataset/labeled/<digito>/<hash>.png`.
  4. Si NO coincide: cuenta como fallo de segmentacion y lo reporta (no se usa).

El signo "-" se ignora para el dataset (la CNN solo clasifica 0-9; el signo
se detecta por geometria en produccion). Pero validamos que aparezca cuando
el label es negativo.

Uso:
    .\\.venv\\Scripts\\python.exe -m vision.scripts.prepare_dataset --detector angle
    # opciones:
    #   --clean   borra labeled/ antes de regenerar
    #   --debug   guarda los fallos de segmentacion en _debug/ para inspeccion
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from collections import Counter
from pathlib import Path

import cv2

from vision.detectors.segment import segment_digits
from vision.scripts.label_digits import load_labels

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LABELED_DIR = PROJECT_ROOT / "assets" / "dataset" / "labeled"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--detector", required=True, choices=["angle", "wind_number"])
    parser.add_argument("--clean", action="store_true", help="borrar labeled/ antes")
    parser.add_argument("--debug", action="store_true", help="guardar fallos en _debug/")
    args = parser.parse_args(argv)

    raw_dir = PROJECT_ROOT / "assets" / "dataset" / "raw" / args.detector
    labels = load_labels(args.detector)
    if not labels:
        print(f"FALLO: no hay labels para {args.detector}", file=sys.stderr)
        return 1

    if args.clean and LABELED_DIR.exists():
        shutil.rmtree(LABELED_DIR)
    for d in "0123456789":
        (LABELED_DIR / d).mkdir(parents=True, exist_ok=True)

    debug_dir = PROJECT_ROOT / "assets" / "dataset" / "_debug_seg"
    if args.debug:
        debug_dir.mkdir(parents=True, exist_ok=True)

    saved = Counter()
    ok_caps = 0
    fail_caps = 0
    fail_list: list[tuple[str, str, int]] = []

    for fname, label in labels.items():
        label = str(label)
        neg = label.startswith("-")
        digits_str = label.lstrip("-")
        if not digits_str.isdigit():
            continue
        expected = len(digits_str)

        img = cv2.imread(str(raw_dir / fname), cv2.IMREAD_COLOR)
        if img is None:
            continue

        res = segment_digits(img, expected_digits=expected)
        if res is None or res.digit_count != expected:
            fail_caps += 1
            got = res.digit_count if res else 0
            fail_list.append((fname, label, got))
            if args.debug:
                cv2.imwrite(str(debug_dir / f"FAIL_{label}_{fname}"), img)
            continue

        # (Opcional) validar signo: si el label es negativo, esperamos un dash.
        # No es bloqueante — solo informativo.
        ok_caps += 1
        for digit_char, digit_img in zip(digits_str, res.digits):
            h = hashlib.md5(digit_img.tobytes()).hexdigest()[:10]
            out = LABELED_DIR / digit_char / f"{fname[:-4]}_{h}.png"
            cv2.imwrite(str(out), digit_img)
            saved[digit_char] += 1

    print("=" * 50)
    print(f"Capturas OK (segmentacion valida):   {ok_caps}")
    print(f"Capturas con fallo de segmentacion:  {fail_caps}")
    print(f"Total digitos guardados en labeled/: {sum(saved.values())}")
    print("-" * 50)
    print("Distribucion de digitos guardados:")
    for d in "0123456789":
        c = saved.get(d, 0)
        print(f"  {d}: {c:3d}  {'#' * c}")
    if fail_list:
        print("-" * 50)
        print(f"Fallos de segmentacion ({len(fail_list)}) — label vs digitos detectados:")
        for fname, label, got in fail_list[:20]:
            print(f"  {fname}  label='{label}'  detecto {got} digitos")
        if len(fail_list) > 20:
            print(f"  ... y {len(fail_list) - 20} mas")
        if args.debug:
            print(f"  (imagenes de fallo en {debug_dir})")
    print("=" * 50)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
