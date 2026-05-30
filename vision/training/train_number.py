"""Entrena la CNN de NUMERO COMPLETO del angulo y exporta a ONNX (Camino 2).

Lee `assets/dataset/raw/angle/*.png` + `assets/dataset/labels_angle.json`
(numeros completos con signo, YA etiquetados) y entrena la `NumberCNN`
multi-cabeza (sign / tens / ones) — sin segmentar digitos. Exporta a
`vision/models/angle_number.onnx` (3 salidas, opset 17, archivo unico).

A diferencia del modelo viejo de digitos NO necesita `prepare_dataset.py`:
los labels ya estan en la forma correcta y `number_preprocess.to_canvas`
normaliza el recorte entero.

Uso (desde la raiz, con el venv):
    .\\.venv\\Scripts\\python.exe -m vision.training.train_number
    # opciones:
    #   --epochs 60     --batch 64     --mult 30
    #   --kfold 5       (validacion cruzada honesta antes del modelo final; 0 = saltar)
    #   --no-cuda

Validacion: k-fold estratificado por signo + tipo (1-digito / 2-digitos /
negativo) da una metrica honesta con dataset chico. El modelo FINAL se entrena
sobre todas las muestras y se exporta.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset

from vision.detectors.number_preprocess import (
    CANVAS_H,
    CANVAS_W,
    ONES_CLASSES,
    SIGN_CLASSES,
    TENS_CLASSES,
    parse_label,
    reconstruct,
    to_canvas,
)
from vision.training.number_model import NumberCNN

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RAW_DIR = PROJECT_ROOT / "assets" / "dataset" / "raw" / "angle"
LABELS_PATH = PROJECT_ROOT / "assets" / "dataset" / "labels_angle.json"
MODEL_OUT = PROJECT_ROOT / "vision" / "models" / "angle_number.onnx"

# Indices dentro de cada tupla de muestra.
I_CANVAS, I_SIGN, I_TENS, I_ONES, I_VALUE = 0, 1, 2, 3, 4


def _augment(img: np.ndarray, rng: random.Random) -> np.ndarray:
    """Augmentation sobre el lienzo 32x64 (mismas operaciones que el modelo
    viejo pero tuneadas: shear y traslacion mas suaves porque el right-align
    ya fija la posicion de las unidades)."""
    h, w = img.shape
    out = img.copy()

    angle = rng.uniform(-6, 6)
    scale = rng.uniform(0.9, 1.1)
    tx = rng.uniform(-3, 3)
    ty = rng.uniform(-2, 2)
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, scale)
    m[0, 2] += tx
    m[1, 2] += ty
    out = cv2.warpAffine(out, m, (w, h), borderValue=0)

    shear = rng.uniform(-0.10, 0.10)
    ms = np.array([[1, shear, -shear * h / 2], [0, 1, 0]], dtype=np.float32)
    out = cv2.warpAffine(out, ms, (w, h), borderValue=0)

    alpha = rng.uniform(0.8, 1.2)
    beta = rng.uniform(-25, 25)
    out = np.clip(out.astype(np.float32) * alpha + beta, 0, 255).astype(np.uint8)

    if rng.random() < 0.5:
        noise = np.random.randn(h, w) * 12
        out = np.clip(out.astype(np.float32) + noise, 0, 255).astype(np.uint8)

    if rng.random() < 0.3:
        out = cv2.GaussianBlur(out, (3, 3), 0)

    return out


class NumberDataset(Dataset):
    def __init__(self, samples: list[tuple], train: bool, mult: int = 1):
        self.samples = samples
        self.train = train
        self.mult = mult if train else 1
        self.rng = random.Random(1234)

    def __len__(self) -> int:
        return len(self.samples) * self.mult

    def __getitem__(self, idx: int):
        s = self.samples[idx % len(self.samples)]
        canvas = s[I_CANVAS]
        if self.train:
            canvas = _augment(canvas, self.rng)
        tensor = torch.from_numpy(canvas.astype(np.float32) / 255.0).unsqueeze(0)
        return tensor, s[I_SIGN], s[I_TENS], s[I_ONES]


def load_samples() -> list[tuple]:
    labels = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    labels = {k: str(v) for k, v in labels.items()}
    samples = []
    skipped = 0
    for fname, label in labels.items():
        path = RAW_DIR / fname
        if not path.exists():
            skipped += 1
            continue
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            skipped += 1
            continue
        try:
            sign, tens, ones = parse_label(label)
        except ValueError:
            skipped += 1
            continue
        canvas = to_canvas(img)
        value = reconstruct(sign, tens, ones)
        samples.append((canvas, sign, tens, ones, value))
    if skipped:
        print(f"  ({skipped} muestras saltadas: archivo ausente o ilegible)")
    return samples


def _strat_key(s: tuple) -> tuple[int, int]:
    """Estrato para split balanceado: (signo, magnitud chica/grande)."""
    kind = 0 if s[I_TENS] == 0 else 1  # magnitud 0-9 vs 10-90
    return (s[I_SIGN], kind)


def stratified_folds(samples: list[tuple], k: int, seed: int = 42):
    """Genera k particiones (train, val) estratificadas por `_strat_key`."""
    rng = random.Random(seed)
    by_key: dict[tuple, list] = {}
    for s in samples:
        by_key.setdefault(_strat_key(s), []).append(s)
    # Asigna cada muestra a un fold de forma round-robin dentro de su estrato.
    fold_of = {}
    for items in by_key.values():
        rng.shuffle(items)
        for i, s in enumerate(items):
            fold_of[id(s)] = i % k
    for f in range(k):
        val = [s for s in samples if fold_of[id(s)] == f]
        train = [s for s in samples if fold_of[id(s)] != f]
        if val and train:
            yield train, val


def stratified_split(samples: list[tuple], val_frac=0.15, seed=42):
    rng = random.Random(seed)
    by_key: dict[tuple, list] = {}
    for s in samples:
        by_key.setdefault(_strat_key(s), []).append(s)
    train, val = [], []
    for items in by_key.values():
        rng.shuffle(items)
        n_val = max(1, int(len(items) * val_frac))
        val += items[:n_val]
        train += items[n_val:]
    rng.shuffle(train)
    rng.shuffle(val)
    return train, val


def class_weights(samples: list[tuple], head_idx: int, n_classes: int, device: str):
    counts = [0] * n_classes
    for s in samples:
        counts[s[head_idx]] += 1
    total = sum(counts)
    w = [total / (n_classes * c) if c > 0 else 0.0 for c in counts]
    return torch.tensor(w, dtype=torch.float32, device=device)


@torch.no_grad()
def evaluate(model: nn.Module, samples: list[tuple], device: str) -> dict:
    model.eval()
    if not samples:
        return {"exact": 0.0, "sign": 0.0, "tens": 0.0, "ones": 0.0, "n": 0}
    batch = (
        torch.from_numpy(np.stack([s[I_CANVAS].astype(np.float32) / 255.0 for s in samples]))
        .unsqueeze(1)
        .to(device)
    )
    sl, tl, ol = model(batch)
    sp = sl.argmax(1).tolist()
    tp = tl.argmax(1).tolist()
    op = ol.argmax(1).tolist()
    exact = sok = tok = ook = 0
    for i, s in enumerate(samples):
        sok += sp[i] == s[I_SIGN]
        tok += tp[i] == s[I_TENS]
        ook += op[i] == s[I_ONES]
        if reconstruct(sp[i], tp[i], op[i]) == s[I_VALUE]:
            exact += 1
    n = len(samples)
    return {
        "exact": exact / n,
        "sign": sok / n,
        "tens": tok / n,
        "ones": ook / n,
        "n": n,
    }


def train_once(train_s, val_s, args, device, verbose=False) -> tuple[dict, dict]:
    """Entrena un modelo sobre `train_s`, selecciona el mejor por exact-match
    en `val_s`. Devuelve (best_state, best_metrics)."""
    train_dl = DataLoader(
        NumberDataset(train_s, train=True, mult=args.mult),
        batch_size=args.batch,
        shuffle=True,
        num_workers=0,
    )
    model = NumberCNN().to(device)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs)
    w_sign = class_weights(train_s, I_SIGN, SIGN_CLASSES, device)
    w_tens = class_weights(train_s, I_TENS, TENS_CLASSES, device)
    w_ones = class_weights(train_s, I_ONES, ONES_CLASSES, device)
    crit_sign = nn.CrossEntropyLoss(weight=w_sign)
    crit_tens = nn.CrossEntropyLoss(weight=w_tens)
    crit_ones = nn.CrossEntropyLoss(weight=w_ones)

    best_exact = -1.0
    best_state = None
    best_metrics = {}
    for epoch in range(args.epochs):
        model.train()
        tloss = 0.0
        for x, ys, yt, yo in train_dl:
            x = x.to(device)
            ys, yt, yo = ys.to(device), yt.to(device), yo.to(device)
            opt.zero_grad()
            sl, tl, ol = model(x)
            loss = crit_sign(sl, ys) + crit_tens(tl, yt) + crit_ones(ol, yo)
            loss.backward()
            opt.step()
            tloss += loss.item() * x.size(0)
        sched.step()

        m = evaluate(model, val_s, device)
        if verbose and ((epoch + 1) % 10 == 0 or epoch == args.epochs - 1):
            print(
                f"  epoch {epoch + 1:2d}/{args.epochs}  loss={tloss / len(train_dl.dataset):.3f}"
                f"  exact={m['exact']:.3f} sign={m['sign']:.3f} tens={m['tens']:.3f} ones={m['ones']:.3f}"
            )
        if m["exact"] >= best_exact:
            best_exact = m["exact"]
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            best_metrics = m
    return best_state, best_metrics


def export_onnx(state: dict, device: str) -> None:
    model = NumberCNN().to(device)
    model.load_state_dict(state)
    model.eval()
    MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)
    dummy = torch.randn(1, 1, CANVAS_H, CANVAS_W, device=device)
    torch.onnx.export(
        model,
        dummy,
        str(MODEL_OUT),
        input_names=["input"],
        output_names=["sign", "tens", "ones"],
        dynamic_axes={
            "input": {0: "batch"},
            "sign": {0: "batch"},
            "tens": {0: "batch"},
            "ones": {0: "batch"},
        },
        opset_version=17,
    )
    # Consolidar pesos externos (.onnx.data) en un unico archivo.
    import onnx as _onnx

    consolidated = _onnx.load(str(MODEL_OUT))
    _onnx.save_model(consolidated, str(MODEL_OUT), save_as_external_data=False)
    data_file = MODEL_OUT.parent / (MODEL_OUT.name + ".data")
    if data_file.exists():
        data_file.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--batch", type=int, default=64)
    parser.add_argument(
        "--mult", type=int, default=30, help="repeticiones con augmentation por epoch"
    )
    parser.add_argument("--kfold", type=int, default=5, help="folds de CV honesta (0 = saltar)")
    parser.add_argument("--no-cuda", action="store_true")
    args = parser.parse_args(argv)

    print("Cargando muestras...")
    samples = load_samples()
    if len(samples) < 20:
        print(f"FALLO: muy pocas muestras ({len(samples)}). Capturá mas con F2 + label_digits.")
        return 1
    n_neg = sum(1 for s in samples if s[I_SIGN] == 1)
    print(f"Muestras: {len(samples)} ({n_neg} negativas, {len(samples) - n_neg} positivas)")

    device = "cuda" if (torch.cuda.is_available() and not args.no_cuda) else "cpu"
    print(f"Device: {device}" + (f" ({torch.cuda.get_device_name(0)})" if device == "cuda" else ""))

    if args.kfold and args.kfold > 1:
        print(f"\n=== Validacion cruzada {args.kfold}-fold (estimacion honesta) ===")
        accs = {"exact": [], "sign": [], "tens": [], "ones": []}
        for i, (tr, va) in enumerate(stratified_folds(samples, args.kfold)):
            _, m = train_once(tr, va, args, device)
            for k in accs:
                accs[k].append(m[k])
            print(
                f"  fold {i + 1}/{args.kfold} (val n={m['n']}): "
                f"exact={m['exact']:.3f} sign={m['sign']:.3f} tens={m['tens']:.3f} ones={m['ones']:.3f}"
            )
        print("  --- media k-fold ---")
        for k in ("exact", "sign", "tens", "ones"):
            print(f"    {k}: {np.mean(accs[k]):.3f}")

    print("\n=== Modelo FINAL (split estratificado, exporta el mejor) ===")
    train_s, val_s = stratified_split(samples)
    print(f"  {len(train_s)} train | {len(val_s)} val")
    best_state, m = train_once(train_s, val_s, args, device, verbose=True)
    print(
        f"  mejor val: exact={m['exact']:.3f} sign={m['sign']:.3f} "
        f"tens={m['tens']:.3f} ones={m['ones']:.3f}"
    )

    if not best_state:
        print("FALLO: no se entreno ningun modelo.")
        return 1
    export_onnx(best_state, device)
    print(f"\nModelo exportado a {MODEL_OUT}")
    print(f"Tamaño: {MODEL_OUT.stat().st_size / 1024:.0f} KB (3 salidas, archivo unico)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
