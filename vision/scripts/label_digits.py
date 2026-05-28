"""Tool interactivo de etiquetado de capturas del dataset (Sprint C.2).

Muestra cada captura de `assets/dataset/raw/<detector>/` ampliada, y vos
tecleas el NUMERO que ves. El label se guarda en un JSON (no renombra los
archivos, asi no hay colision de nombres si hay numeros repetidos).

Controles:
    0-9        escribir digitos del numero visible
    - / _ / m  marcar el numero como NEGATIVO (el angulo puede ser negativo)
    Enter      confirmar el label y pasar a la siguiente
    Backspace  borrar el ultimo digito tecleado
    s / ESC    saltar esta imagen (no etiquetar)
    z          volver a la imagen anterior
    q          guardar y salir

Los labels se guardan como STRING (ej. "-09", "45") para preservar el signo
y los ceros a la izquierda — info que un int perderia.

Reanudable: si ya etiquetaste algunas, las saltea y sigue donde quedaste.

Uso (desde la raiz del proyecto, con el venv):
    .\\.venv\\Scripts\\python.exe -m vision.scripts.label_digits --detector angle
    .\\.venv\\Scripts\\python.exe -m vision.scripts.label_digits --detector wind_number
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def labels_path(detector: str) -> Path:
    return PROJECT_ROOT / "assets" / "dataset" / f"labels_{detector}.json"


def load_labels(detector: str) -> dict[str, str]:
    p = labels_path(detector)
    if p.exists():
        raw = json.loads(p.read_text(encoding="utf-8"))
        # Normalizar a string (compat con labels viejos guardados como int).
        return {k: str(v) for k, v in raw.items()}
    return {}


def save_labels(detector: str, labels: dict[str, str]) -> None:
    p = labels_path(detector)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(labels, indent=2), encoding="utf-8")


def render(img: np.ndarray, fname: str, typed: str, idx: int, total: int, labeled: int) -> np.ndarray:
    """Compone la imagen ampliada + una barra de estado abajo."""
    target_w = 480
    h, w = img.shape[:2]
    scale = target_w / max(1, w)
    big = cv2.resize(img, (target_w, int(h * scale)), interpolation=cv2.INTER_NEAREST)
    if big.ndim == 2:
        big = cv2.cvtColor(big, cv2.COLOR_GRAY2BGR)

    bar_h = 90
    canvas = np.full((big.shape[0] + bar_h, big.shape[1], 3), 30, dtype=np.uint8)
    canvas[: big.shape[0], : big.shape[1]] = big

    y0 = big.shape[0] + 24
    cv2.putText(canvas, f"[{idx + 1}/{total}]  etiquetadas: {labeled}", (10, y0),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 180, 180), 1, cv2.LINE_AA)
    cv2.putText(canvas, f"numero: {typed or '_'}", (10, y0 + 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (80, 220, 120), 2, cv2.LINE_AA)
    cv2.putText(canvas, "Enter=ok  Bksp=borrar  -/m=negativo  s/ESC=skip  z=atras  q=salir",
                (10, y0 + 52), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (140, 140, 140), 1, cv2.LINE_AA)
    return canvas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--detector", required=True, choices=["angle", "wind_number"])
    args = parser.parse_args(argv)

    raw_dir = PROJECT_ROOT / "assets" / "dataset" / "raw" / args.detector
    if not raw_dir.exists():
        print(f"FALLO: no existe {raw_dir}", file=sys.stderr)
        return 1

    files = sorted(p.name for p in raw_dir.glob("*.png"))
    if not files:
        print(f"FALLO: no hay PNGs en {raw_dir}", file=sys.stderr)
        return 1

    labels = load_labels(args.detector)
    print(f"{len(files)} capturas, {len(labels)} ya etiquetadas. Abriendo ventana...")

    win = f"label [{args.detector}]"
    cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)

    idx = 0
    typed = ""
    while 0 <= idx < len(files):
        fname = files[idx]
        # Si ya esta etiquetada y no estamos editando, saltar hacia adelante.
        if fname in labels and typed == "":
            idx += 1
            continue

        img = cv2.imread(str(raw_dir / fname), cv2.IMREAD_COLOR)
        if img is None:
            idx += 1
            continue

        cv2.imshow(win, render(img, fname, typed, idx, len(files), len(labels)))

        # Esperar tecla con timeout para poder detectar el cierre de la
        # ventana (la X). Sin esto, waitKey(0) bloquea para siempre y al
        # cerrar la ventana el loop la reabre — quedaba colgado.
        raw = -1
        while raw == -1:
            raw = cv2.waitKey(100)
            try:
                closed = cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE) < 1
            except cv2.error:
                closed = True
            if closed:
                save_labels(args.detector, labels)
                cv2.destroyAllWindows()
                print(f"Ventana cerrada. Guardado: {len(labels)} labels.")
                return 0
        key = raw & 0xFF

        if key == ord("q"):
            break
        elif key in range(ord("0"), ord("9") + 1):
            typed += chr(key)
        elif key in (ord("-"), ord("_"), ord("m")):
            # Marca negativo: el "-" va siempre al frente, una sola vez.
            if not typed.startswith("-"):
                typed = "-" + typed
        elif key == 8:  # Backspace
            typed = typed[:-1]
        elif key in (ord("s"), 27):  # skip
            typed = ""
            idx += 1
        elif key == ord("z"):  # atras
            typed = ""
            idx = max(0, idx - 1)
            # forzar re-etiquetado de la anterior aunque ya tenga label
            prev = files[idx]
            labels.pop(prev, None)
        elif key in (13, 10):  # Enter
            # Aceptar solo si hay al menos un digito (no solo "-").
            if typed and any(c.isdigit() for c in typed):
                labels[fname] = typed  # guardar string tal cual ("-09", "45")
                save_labels(args.detector, labels)
                typed = ""
                idx += 1
            # si no hay nada tecleado, Enter no hace nada

    save_labels(args.detector, labels)
    cv2.destroyAllWindows()
    print(f"Guardado: {len(labels)} labels en {labels_path(args.detector)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
