"""Estadisticas y HUECOS de cobertura del dataset de angulo (Camino 2).

Lee `assets/dataset/labels_angle.json` y muestra:
  * resumen (total, positivos/negativos)
  * cobertura de NEGATIVOS (-1..-26) — la prioridad de captura
  * cobertura de digitos sueltos positivos (0-9)
  * distribucion por cabeza del modelo (sign / tens / ones)
  * valores con pocas muestras
  * sugerencias concretas de que capturar

Sirve para guiar la Fase 0 (captura con F2 + label_digits) hacia un dataset
balanceado. Meta sugerida: ~300+ muestras, 60-80 negativas.

Uso:
    .\\.venv\\Scripts\\python.exe -m vision.scripts.dataset_stats
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from vision.detectors.number_preprocess import (
    VALID_MAX,
    VALID_MIN,
    parse_label,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

TARGET_TOTAL = 300
TARGET_NEG = 70
MIN_PER_VALUE = 2  # umbral por debajo del cual marcamos un valor como "flojo"


def _load_labels(detector: str) -> dict[str, str]:
    p = PROJECT_ROOT / "assets" / "dataset" / f"labels_{detector}.json"
    if not p.exists():
        raise SystemExit(f"FALLO: no existe {p}")
    raw = json.loads(p.read_text(encoding="utf-8"))
    return {k: str(v) for k, v in raw.items()}


def _bar(n: int, scale: int = 1) -> str:
    return "#" * (n * scale)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--detector", default="angle", choices=["angle", "wind_number"])
    args = parser.parse_args(argv)

    labels = _load_labels(args.detector)
    values = [int(v) for v in labels.values()]
    by_value = Counter(values)
    n_total = len(values)
    n_neg = sum(1 for v in values if v < 0)
    n_pos = n_total - n_neg

    print(f"=== Dataset '{args.detector}' ===")
    print(f"Total: {n_total}   positivos: {n_pos}   negativos: {n_neg}")
    print(f"Meta sugerida: {TARGET_TOTAL}+ total, {TARGET_NEG} negativos\n")

    # --- Negativos: la prioridad de captura ---
    print("--- NEGATIVOS (prioridad): -1 .. -26 ---")
    missing_neg = []
    for v in range(-1, VALID_MIN - 1, -1):
        c = by_value.get(v, 0)
        flag = "  <-- FALTA" if c == 0 else ("  (pocas)" if c < MIN_PER_VALUE else "")
        if c == 0:
            missing_neg.append(v)
        print(f"  {v:>3}: {c:>2} {_bar(c)}{flag}")
    if missing_neg:
        print(f"  >> faltan por completo: {', '.join(str(v) for v in missing_neg)}")

    # --- Digitos sueltos positivos 0-9 ---
    print("\n--- DIGITOS SUELTOS positivos: 0 .. 9 ---")
    for v in range(10):
        c = by_value.get(v, 0)
        flag = "  <-- FALTA" if c == 0 else ("  (pocas)" if c < MIN_PER_VALUE else "")
        print(f"  {v:>3}: {c:>2} {_bar(c)}{flag}")

    # --- Distribucion por cabeza del modelo ---
    cs, ct, co = Counter(), Counter(), Counter()
    for s in labels.values():
        sg, tn, on = parse_label(s)
        cs[sg] += 1
        ct[tn] += 1
        co[on] += 1
    print("\n--- POR CABEZA del modelo (lo que cada cabeza ve) ---")
    print(f"  sign  +:{cs.get(0, 0)}  -:{cs.get(1, 0)}")
    tens_str = "  ".join(f"{i}:{ct.get(i, 0)}" for i in range(10))
    print(f"  tens  {tens_str}")
    ones_str = "  ".join(f"{i}:{co.get(i, 0)}" for i in range(10))
    print(f"  ones  {ones_str}")

    # --- Valores flojos en todo el rango legal ---
    weak = [v for v in range(VALID_MIN, VALID_MAX + 1) if by_value.get(v, 0) < MIN_PER_VALUE]
    print(
        f"\n--- VALORES con < {MIN_PER_VALUE} muestras ({len(weak)} de {VALID_MAX - VALID_MIN + 1}) ---"
    )
    print("  " + ", ".join(str(v) for v in weak) if weak else "  (ninguno)")

    # --- Sugerencias ---
    print("\n--- SUGERENCIAS ---")
    if n_total < TARGET_TOTAL:
        print(f"  * Capturar {TARGET_TOTAL - n_total} muestras mas (F2 sobre el HUD).")
    if n_neg < TARGET_NEG:
        print(f"  * Faltan ~{TARGET_NEG - n_neg} negativas: apuntar entre 0 y -26.")
    if missing_neg:
        print(f"  * Priorizar negativos sin cobertura: {', '.join(str(v) for v in missing_neg)}.")
    if n_total >= TARGET_TOTAL and n_neg >= TARGET_NEG and not missing_neg:
        print("  * Dataset balanceado. Listo para `python -m vision.training.train_number`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
