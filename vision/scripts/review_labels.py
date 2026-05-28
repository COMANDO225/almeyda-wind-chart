"""Tool de REVIEW de labels (Sprint C.2b).

Galeria paginada para verificar/corregir rapido los labels puestos con
`label_digits.py`. Muestra una grilla de capturas con su numero etiquetado
superpuesto; de un vistazo detectas las mal etiquetadas. Click en una celda
para corregirla.

Controles (grilla):
    click izq.    editar la celda clickeada
    flecha der/a  pagina siguiente
    flecha izq/d  pagina anterior
    q             salir

Controles (modo edicion, tras click):
    0-9           teclear numero
    - / _ / m     marcar negativo
    Enter         guardar correccion y volver a la grilla
    Backspace     borrar ultimo digito
    ESC           cancelar (volver a la grilla sin cambios)

Uso:
    .\\.venv\\Scripts\\python.exe -m vision.scripts.review_labels --detector angle
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

from vision.scripts.label_digits import labels_path, load_labels, save_labels

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

COLS = 6
ROWS = 4
CELL_W = 150
CELL_H = 120
HEADER_H = 32
PER_PAGE = COLS * ROWS

GREEN = (90, 220, 120)
RED = (60, 60, 230)
GREY = (150, 150, 150)


def _thumb(img: np.ndarray, w: int, h: int) -> np.ndarray:
    ih, iw = img.shape[:2]
    scale = min(w / max(1, iw), h / max(1, ih))
    nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
    canvas = np.full((h, w, 3), 20, dtype=np.uint8)
    y0 = (h - nh) // 2
    x0 = (w - nw) // 2
    canvas[y0 : y0 + nh, x0 : x0 + nw] = resized
    return canvas


def build_grid(files: list[str], labels: dict[str, str], raw_dir: Path, page: int) -> np.ndarray:
    canvas = np.full((HEADER_H + ROWS * CELL_H, COLS * CELL_W, 3), 30, dtype=np.uint8)
    total_pages = (len(files) + PER_PAGE - 1) // PER_PAGE
    cv2.putText(
        canvas,
        f"Pagina {page + 1}/{total_pages}   click=editar   flechas/a-d=pagina   q=salir",
        (10, 21),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (200, 200, 200),
        1,
        cv2.LINE_AA,
    )

    start = page * PER_PAGE
    for cell in range(PER_PAGE):
        gidx = start + cell
        if gidx >= len(files):
            break
        row, col = divmod(cell, COLS)
        cx = col * CELL_W
        cy = HEADER_H + row * CELL_H

        fname = files[gidx]
        img = cv2.imread(str(raw_dir / fname), cv2.IMREAD_COLOR)
        thumb_h = CELL_H - 26
        if img is None:
            thumb = np.full((thumb_h, CELL_W - 6, 3), 50, dtype=np.uint8)
        else:
            thumb = _thumb(img, CELL_W - 6, thumb_h)
        canvas[cy + 3 : cy + 3 + thumb_h, cx + 3 : cx + 3 + (CELL_W - 6)] = thumb

        label = labels.get(fname)
        has = label is not None
        # Texto del label
        txt = label if has else "?"
        color = GREEN if has else RED
        cv2.putText(
            canvas, txt, (cx + 8, cy + CELL_H - 6),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2, cv2.LINE_AA,
        )
        # Borde de la celda (rojo si falta label)
        cv2.rectangle(
            canvas, (cx + 1, cy + 1), (cx + CELL_W - 2, cy + CELL_H - 2),
            RED if not has else (70, 70, 70), 1,
        )
    return canvas


def edit_one(win: str, raw_dir: Path, fname: str, current: str | None) -> str | None:
    """Modo edicion de una sola captura. Devuelve el nuevo label, o None si
    se cancela (no cambiar)."""
    img = cv2.imread(str(raw_dir / fname), cv2.IMREAD_COLOR)
    if img is None:
        return None
    typed = current or ""
    while True:
        big = cv2.resize(img, (440, int(img.shape[0] * 440 / img.shape[1])),
                         interpolation=cv2.INTER_NEAREST)
        if big.ndim == 2:
            big = cv2.cvtColor(big, cv2.COLOR_GRAY2BGR)
        bar = np.full((90, big.shape[1], 3), 30, dtype=np.uint8)
        cv2.putText(bar, f"EDITAR  actual: {current or '-'}", (10, 26),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, GREY, 1, cv2.LINE_AA)
        cv2.putText(bar, f"nuevo: {typed or '_'}", (10, 54),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, GREEN, 2, cv2.LINE_AA)
        cv2.putText(bar, "Enter=guardar  ESC=cancelar  Bksp  -/m=neg", (10, 78),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, GREY, 1, cv2.LINE_AA)
        cv2.imshow(win, np.vstack([big, bar]))

        raw = -1
        while raw == -1:
            raw = cv2.waitKey(100)
            try:
                if cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE) < 1:
                    return None
            except cv2.error:
                return None
        key = raw & 0xFF

        if key == 27:  # ESC cancelar
            return None
        elif key in (13, 10):  # Enter
            if typed and any(c.isdigit() for c in typed):
                return typed
        elif key in range(ord("0"), ord("9") + 1):
            typed += chr(key)
        elif key in (ord("-"), ord("_"), ord("m")):
            if not typed.startswith("-"):
                typed = "-" + typed
        elif key == 8:
            typed = typed[:-1]


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
    win = f"review [{args.detector}]"
    cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)

    state = {"page": 0, "click_cell": None}

    def on_mouse(event, x, y, flags, _param):
        if event == cv2.EVENT_LBUTTONDOWN and y >= HEADER_H:
            col = x // CELL_W
            row = (y - HEADER_H) // CELL_H
            if 0 <= col < COLS and 0 <= row < ROWS:
                state["click_cell"] = int(row * COLS + col)

    cv2.setMouseCallback(win, on_mouse)
    total_pages = (len(files) + PER_PAGE - 1) // PER_PAGE

    while True:
        cv2.imshow(win, build_grid(files, labels, raw_dir, state["page"]))
        raw = -1
        while raw == -1 and state["click_cell"] is None:
            raw = cv2.waitKey(50)
            try:
                if cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE) < 1:
                    save_labels(args.detector, labels)
                    cv2.destroyAllWindows()
                    print(f"Cerrado. {len(labels)} labels.")
                    return 0
            except cv2.error:
                save_labels(args.detector, labels)
                return 0

        # Click → editar
        if state["click_cell"] is not None:
            gidx = state["page"] * PER_PAGE + state["click_cell"]
            state["click_cell"] = None
            if gidx < len(files):
                fname = files[gidx]
                new = edit_one(win, raw_dir, fname, labels.get(fname))
                if new is not None:
                    labels[fname] = new
                    save_labels(args.detector, labels)
            continue

        key = raw & 0xFF
        if key == ord("q"):
            break
        elif key in (ord("d"), 83, 3):  # flecha der / d
            state["page"] = min(total_pages - 1, state["page"] + 1)
        elif key in (ord("a"), 81, 2):  # flecha izq / a
            state["page"] = max(0, state["page"] - 1)

    save_labels(args.detector, labels)
    cv2.destroyAllWindows()
    print(f"Guardado: {len(labels)} labels.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
