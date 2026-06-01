"""Tool interactivo de etiquetado del PUNTERO del viento.

A diferencia del label de digitos (que es texto), aca el label es un ANGULO
continuo (0-360°, float). Para no tener que adivinarlo a ojo, el tool muestra
la imagen del radar AMPLIADA + una aguja semitransparente desde el centro que
el usuario ARRASTRA con el mouse para alinearla con la flecha real del juego.
El angulo se calcula con atan2 y se guarda como float en
`labels_wind_pointer.json`.

Convencion de angulos (la misma que `wind.py` y `WindCompass.svelte`):
    0° = derecha (este), 90° = abajo, 180° = izquierda, 270° = arriba.
    Crece HORARIO en coords de pantalla (porque y crece hacia abajo).

Controles:
    Mouse drag (boton izq)  arrastra el extremo de la aguja
    Enter                   confirma el label y pasa a la siguiente
    z                       volver a la imagen anterior (re-etiquetarla)
    s / ESC                 saltar esta imagen
    q                       guardar y salir

Reanudable: salta las imagenes que ya tienen label.

Uso (desde la raiz del proyecto, con el venv):
    .\\.venv\\Scripts\\python.exe -m vision.scripts.label_wind_pointer
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RAW_DIR = PROJECT_ROOT / "assets" / "dataset" / "raw" / "wind_pointer"
LABELS_PATH = PROJECT_ROOT / "assets" / "dataset" / "labels_wind_pointer.json"

CANVAS_SIZE = 480  # px del visor (cuadrado)
BAR_H = 90  # alto de la barra inferior con info


def load_labels() -> dict[str, float]:
    if LABELS_PATH.exists():
        raw = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
        return {k: float(v) for k, v in raw.items()}
    return {}


def save_labels(labels: dict[str, float]) -> None:
    LABELS_PATH.parent.mkdir(parents=True, exist_ok=True)
    LABELS_PATH.write_text(json.dumps(labels, indent=2), encoding="utf-8")


def render(
    img: np.ndarray,
    fname: str,
    angle_deg: float | None,
    idx: int,
    total: int,
    labeled: int,
) -> np.ndarray:
    """Compone el canvas: imagen del radar a CANVAS_SIZE + barra inferior + aguja.

    La aguja se dibuja DESDE el centro hacia el extremo (a 90% del radio del
    canvas) en la direccion `angle_deg`. La convencion (0=derecha, 90=abajo,
    horario) sale natural de `cv2.line` porque Y crece hacia abajo.
    """
    h, w = img.shape[:2]
    side = max(h, w)
    square = np.zeros((side, side, 3), dtype=np.uint8)
    oy = (side - h) // 2
    ox = (side - w) // 2
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    square[oy : oy + h, ox : ox + w] = img
    canvas = cv2.resize(square, (CANVAS_SIZE, CANVAS_SIZE), interpolation=cv2.INTER_NEAREST)

    cx, cy = CANVAS_SIZE // 2, CANVAS_SIZE // 2
    r = int(CANVAS_SIZE * 0.45)
    cv2.circle(canvas, (cx, cy), r, (60, 60, 60), 1, cv2.LINE_AA)
    cv2.circle(canvas, (cx, cy), 4, (0, 200, 255), -1, cv2.LINE_AA)

    if angle_deg is not None:
        rad = math.radians(angle_deg)
        tip_x = int(round(cx + r * math.cos(rad)))
        tip_y = int(round(cy + r * math.sin(rad)))
        cv2.line(canvas, (cx, cy), (tip_x, tip_y), (0, 220, 255), 3, cv2.LINE_AA)
        cv2.circle(canvas, (tip_x, tip_y), 6, (0, 220, 255), -1, cv2.LINE_AA)

    bar = np.full((BAR_H, CANVAS_SIZE, 3), 30, dtype=np.uint8)
    y0 = 24
    cv2.putText(
        bar,
        f"[{idx + 1}/{total}]  etiquetadas: {labeled}  ({fname})",
        (10, y0),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (180, 180, 180),
        1,
        cv2.LINE_AA,
    )
    ang_text = f"{angle_deg:.1f}°" if angle_deg is not None else "--"
    cv2.putText(
        bar,
        f"angulo: {ang_text}",
        (10, y0 + 26),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.75,
        (80, 220, 120),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        bar,
        "Drag=apuntar  Enter=ok  s/ESC=skip  z=atras  q=salir",
        (10, y0 + 50),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.38,
        (140, 140, 140),
        1,
        cv2.LINE_AA,
    )
    return np.vstack([canvas, bar])


class _MouseState:
    """Estado compartido con el callback de mouse: arrastrando + ultimo angulo."""

    def __init__(self) -> None:
        self.angle: float | None = None
        self.dragging = False

    def on_event(self, event: int, x: int, y: int, flags: int, _param: object) -> None:
        # Solo procesar dentro del canvas circular (no en la barra inferior).
        if y >= CANVAS_SIZE:
            return
        if event == cv2.EVENT_LBUTTONDOWN:
            self.dragging = True
        elif event == cv2.EVENT_LBUTTONUP:
            self.dragging = False
        if self.dragging or event == cv2.EVENT_LBUTTONDOWN:
            cx, cy = CANVAS_SIZE // 2, CANVAS_SIZE // 2
            dx = x - cx
            dy = y - cy
            if dx * dx + dy * dy < 16:  # muy cerca del centro: ignorar
                return
            self.angle = (math.degrees(math.atan2(dy, dx)) + 360.0) % 360.0


def main() -> int:
    if not RAW_DIR.exists():
        print(f"FALLO: no existe {RAW_DIR}. Captura primero con F3.", file=sys.stderr)
        return 1
    files = sorted(p.name for p in RAW_DIR.glob("*.png"))
    if not files:
        print(f"FALLO: no hay PNGs en {RAW_DIR}", file=sys.stderr)
        return 1

    labels = load_labels()
    print(f"{len(files)} capturas, {len(labels)} ya etiquetadas. Abriendo ventana...")

    win = "label wind_pointer (arrastra la aguja)"
    cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
    mouse = _MouseState()
    cv2.setMouseCallback(win, mouse.on_event)

    idx = 0
    while 0 <= idx < len(files):
        fname = files[idx]
        if fname in labels and mouse.angle is None:
            idx += 1
            continue

        img = cv2.imread(str(RAW_DIR / fname), cv2.IMREAD_COLOR)
        if img is None:
            idx += 1
            continue

        # Inicializa la aguja al label previo si lo hay y no estamos editando.
        if mouse.angle is None and fname in labels:
            mouse.angle = labels[fname]

        # Loop de refresco a 30 ms para que el drag se actualice fluido.
        while True:
            cv2.imshow(win, render(img, fname, mouse.angle, idx, len(files), len(labels)))
            raw = cv2.waitKey(30)
            try:
                closed = cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE) < 1
            except cv2.error:
                closed = True
            if closed:
                save_labels(labels)
                cv2.destroyAllWindows()
                print(f"Ventana cerrada. Guardado: {len(labels)} labels.")
                return 0
            if raw == -1:
                continue
            key = raw & 0xFF
            if key == ord("q"):
                save_labels(labels)
                cv2.destroyAllWindows()
                print(f"Guardado: {len(labels)} labels en {LABELS_PATH}")
                return 0
            if key in (ord("s"), 27):  # skip
                mouse.angle = None
                idx += 1
                break
            if key == ord("z"):  # atras
                mouse.angle = None
                idx = max(0, idx - 1)
                labels.pop(files[idx], None)
                break
            if key in (13, 10) and mouse.angle is not None:  # Enter
                labels[fname] = round(mouse.angle, 1)
                save_labels(labels)
                mouse.angle = None
                idx += 1
                break

    save_labels(labels)
    cv2.destroyAllWindows()
    print(f"Guardado: {len(labels)} labels en {LABELS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
