"""Entrena la CNN del NUMERO del viento y exporta a ONNX.

Lee `assets/dataset/raw/wind_number/*.png` + `labels_wind_number.json`
(generado por el visor sintetico Almeyda Wind Visor: 36 puntos x 51 valores
x 2 colores x 6 etapas de opacidad = ~22k muestras balanceadas) y entrena la
`WindNumberCNN` (2 cabezas: tens + ones). Exporta a
`vision/models/wind_number.onnx` (2 salidas, opset 17, archivo unico).

AUGMENTATION AGRESIVO de brillo/contraste para cubrir el shift residual entre
el visor sintetico (canvas->toBlob, sRGB puro) y la captura real del juego
(BitBlt post-DWM, ICC del display). Las variantes de opacidad ya cubren la
mayor parte del rango; el augmentation tapa el resto.

Uso:
    .\\.venv\\Scripts\\python.exe -m vision.training.train_wind_number
        # --epochs 60 --batch 128 --mult 4 --kfold 5 --no-cuda
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

from vision.detectors.wind_number_preprocess import (
    CANVAS_H,
    CANVAS_W,
    parse_label,
    reconstruct,
    to_canvas,
)
from vision.training.wind_number_model import WindNumberCNN

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RAW_DIR = PROJECT_ROOT / "assets" / "dataset" / "raw" / "wind_number"
LABELS_PATH = PROJECT_ROOT / "assets" / "dataset" / "labels_wind_number.json"
MODEL_OUT = PROJECT_ROOT / "vision" / "models" / "wind_number.onnx"

I_CANVAS, I_TENS, I_ONES, I_VALUE = 0, 1, 2, 3


def _augment(img: np.ndarray, rng: random.Random) -> np.ndarray:
    """Augmentation MAS AGRESIVO que el del angulo (brillo/contraste/noise
    amplios) para que el modelo aprenda invariancia a cambios de iluminacion
    y a la pequenia diferencia gamma/color-profile sintetico ↔ juego real.
    Rotacion + shear son chicos (los digitos del wind son fijos, no manuscritos).
    """
    h, w = img.shape
    out = img.copy()

    angle = rng.uniform(-4, 4)
    scale = rng.uniform(0.92, 1.08)
    tx = rng.uniform(-2, 2)
    ty = rng.uniform(-2, 2)
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, scale)
    m[0, 2] += tx
    m[1, 2] += ty
    out = cv2.warpAffine(out, m, (w, h), borderValue=0)

    shear = rng.uniform(-0.06, 0.06)
    ms = np.array([[1, shear, -shear * h / 2], [0, 1, 0]], dtype=np.float32)
    out = cv2.warpAffine(out, ms, (w, h), borderValue=0)

    # BRILLO/CONTRASTE AGRESIVO — el corazon del augmentation aqui.
    alpha = rng.uniform(0.5, 1.5)  # contraste (vs 0.8-1.2 del angulo)
    beta = rng.uniform(-60, 60)  # brillo (vs +-25 del angulo)
    out = np.clip(out.astype(np.float32) * alpha + beta, 0, 255).astype(np.uint8)

    if rng.random() < 0.5:
        noise = np.random.randn(h, w) * 15.0
        out = np.clip(out.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    if rng.random() < 0.3:
        out = cv2.GaussianBlur(out, (3, 3), 0)

    return out


def _worker_init_fn(worker_id: int) -> None:
    """Re-semilla el rng del dataset por worker para que cada uno genere una
    secuencia distinta de augmentation (sin esto, los N workers harian
    exactamente lo mismo y la diversidad caeria a 1/N)."""
    info = torch.utils.data.get_worker_info()
    if info is not None:
        info.dataset.rng = random.Random(1234 + worker_id)
        np.random.seed(1234 + worker_id)


class WindNumberDataset(Dataset):
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
        return tensor, s[I_TENS], s[I_ONES]


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
            tens, ones = parse_label(label)
        except ValueError:
            skipped += 1
            continue
        canvas = to_canvas(img)
        value = reconstruct(tens, ones)
        samples.append((canvas, tens, ones, value))
    if skipped:
        print(f"  ({skipped} muestras saltadas: archivo ausente o ilegible)")
    return samples


def _strat_key(s: tuple) -> int:
    """Estrato para split balanceado: el valor entero (asi cada fold ve
    distribucion uniforme de los 51 valores 0-50)."""
    return s[I_VALUE]


def stratified_folds(samples: list[tuple], k: int, seed: int = 42):
    rng = random.Random(seed)
    by_key: dict[int, list] = {}
    for s in samples:
        by_key.setdefault(_strat_key(s), []).append(s)
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


def stratified_split(samples: list[tuple], val_frac=0.1, seed=42):
    rng = random.Random(seed)
    by_key: dict[int, list] = {}
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


@torch.no_grad()
def evaluate(model: nn.Module, samples: list[tuple], device: str, batch_size: int = 256) -> dict:
    model.eval()
    n = len(samples)
    if not n:
        return {"exact": 0.0, "tens": 0.0, "ones": 0.0, "n": 0}
    exact = tok = ook = 0
    for i in range(0, n, batch_size):
        chunk = samples[i : i + batch_size]
        batch = (
            torch.from_numpy(np.stack([s[I_CANVAS].astype(np.float32) / 255.0 for s in chunk]))
            .unsqueeze(1)
            .to(device)
        )
        tl, ol = model(batch)
        tp = tl.argmax(1).tolist()
        op = ol.argmax(1).tolist()
        for j, s in enumerate(chunk):
            t_ok = tp[j] == s[I_TENS]
            o_ok = op[j] == s[I_ONES]
            tok += t_ok
            ook += o_ok
            if reconstruct(tp[j], op[j]) == s[I_VALUE]:
                exact += 1
    return {"exact": exact / n, "tens": tok / n, "ones": ook / n, "n": n}


def train_once(train_s, val_s, args, device, verbose=False) -> tuple[dict, dict]:
    use_workers = args.workers > 0
    train_dl = DataLoader(
        WindNumberDataset(train_s, train=True, mult=args.mult),
        batch_size=args.batch,
        shuffle=True,
        num_workers=args.workers,
        pin_memory=(device == "cuda"),
        persistent_workers=use_workers,  # no respawnea procesos entre epochs
        prefetch_factor=2 if use_workers else None,
        drop_last=True,  # ultimo batch incompleto se descarta (mejor throughput)
        worker_init_fn=_worker_init_fn if use_workers else None,
    )
    model = WindNumberCNN().to(device)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs)
    crit = nn.CrossEntropyLoss()
    scaler = torch.amp.GradScaler("cuda") if (args.amp and device == "cuda") else None

    best_exact = -1.0
    best_state = None
    best_metrics = {}
    for epoch in range(args.epochs):
        model.train()
        tloss = 0.0
        for x, yt, yo in train_dl:
            x = x.to(device, non_blocking=use_workers)
            yt = yt.to(device, non_blocking=use_workers)
            yo = yo.to(device, non_blocking=use_workers)
            opt.zero_grad(set_to_none=True)
            if scaler is not None:
                with torch.amp.autocast("cuda"):
                    tl, ol = model(x)
                    loss = crit(tl, yt) + crit(ol, yo)
                scaler.scale(loss).backward()
                scaler.step(opt)
                scaler.update()
            else:
                tl, ol = model(x)
                loss = crit(tl, yt) + crit(ol, yo)
                loss.backward()
                opt.step()
            tloss += loss.item() * x.size(0)
        sched.step()

        m = evaluate(model, val_s, device)
        if verbose and ((epoch + 1) % 5 == 0 or epoch == args.epochs - 1):
            print(
                f"  epoch {epoch + 1:3d}/{args.epochs}  loss={tloss / len(train_dl.dataset):.4f}"
                f"  exact={m['exact']:.3f} tens={m['tens']:.3f} ones={m['ones']:.3f}"
            )
        if m["exact"] >= best_exact:
            best_exact = m["exact"]
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            best_metrics = m
    return best_state, best_metrics


def export_onnx(state: dict, device: str) -> None:
    model = WindNumberCNN().to(device)
    model.load_state_dict(state)
    model.eval()
    MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)
    dummy = torch.randn(1, 1, CANVAS_H, CANVAS_W, device=device)
    torch.onnx.export(
        model,
        dummy,
        str(MODEL_OUT),
        input_names=["input"],
        output_names=["tens", "ones"],
        dynamic_axes={
            "input": {0: "batch"},
            "tens": {0: "batch"},
            "ones": {0: "batch"},
        },
        opset_version=17,
    )
    import onnx as _onnx

    consolidated = _onnx.load(str(MODEL_OUT))
    _onnx.save_model(consolidated, str(MODEL_OUT), save_as_external_data=False)
    data_file = MODEL_OUT.parent / (MODEL_OUT.name + ".data")
    if data_file.exists():
        data_file.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # Defaults pensados para RTX 5080: batch grande (VRAM de sobra), mult bajo
    # (22k muestras balanceadas), workers paralelos para alimentar la GPU.
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--batch", type=int, default=256)
    parser.add_argument(
        "--mult", type=int, default=2, help="repeticiones con augmentation por epoch"
    )
    parser.add_argument("--kfold", type=int, default=5, help="folds de CV (0 = saltar)")
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="procesos paralelos del DataLoader para augmentation; 0 = single-thread (lento)",
    )
    parser.add_argument(
        "--amp",
        action="store_true",
        help="mixed precision fp16 — exprime los Tensor Cores de la 5080 (otro 2-3x speedup)",
    )
    parser.add_argument("--no-cuda", action="store_true")
    args = parser.parse_args(argv)

    if not LABELS_PATH.exists():
        print(f"FALLO: no existe {LABELS_PATH}.")
        return 1
    print("Cargando muestras (puede tardar ~30s con 22k)...")
    samples = load_samples()
    if len(samples) < 100:
        print(f"FALLO: muy pocas muestras ({len(samples)}).")
        return 1

    # Histograma por valor para verificar balance.
    from collections import Counter

    by_value = Counter(s[I_VALUE] for s in samples)
    minc, maxc = min(by_value.values()), max(by_value.values())
    print(f"Muestras: {len(samples)} | por valor: min {minc}, max {maxc} (balance OK si min≈max)")

    device = "cuda" if (torch.cuda.is_available() and not args.no_cuda) else "cpu"
    if device == "cuda":
        # cuDNN elige el algoritmo optimo en la primera iteracion (10-30% mas).
        torch.backends.cudnn.benchmark = True
    print(f"Device: {device}" + (f" ({torch.cuda.get_device_name(0)})" if device == "cuda" else ""))
    extras = [f"workers={args.workers}", f"batch={args.batch}", f"mult={args.mult}"]
    if args.amp:
        extras.append("amp=fp16")
    print(f"Config: {', '.join(extras)}")

    if args.kfold and args.kfold > 1:
        print(f"\n=== Validacion cruzada {args.kfold}-fold ===")
        accs = {"exact": [], "tens": [], "ones": []}
        for i, (tr, va) in enumerate(stratified_folds(samples, args.kfold)):
            _, m = train_once(tr, va, args, device)
            for k in accs:
                accs[k].append(m[k])
            print(
                f"  fold {i + 1}/{args.kfold} (val n={m['n']}): "
                f"exact={m['exact']:.3f} tens={m['tens']:.3f} ones={m['ones']:.3f}"
            )
        print("  --- media k-fold ---")
        for k in ("exact", "tens", "ones"):
            print(f"    {k}: {np.mean(accs[k]):.3f}")

    print("\n=== Modelo FINAL (split estratificado, exporta el mejor) ===")
    train_s, val_s = stratified_split(samples)
    print(f"  {len(train_s)} train | {len(val_s)} val")
    best_state, m = train_once(train_s, val_s, args, device, verbose=True)
    print(f"  mejor val: exact={m['exact']:.3f} tens={m['tens']:.3f} ones={m['ones']:.3f}")

    if not best_state:
        print("FALLO: no se entreno ningun modelo.")
        return 1
    export_onnx(best_state, device)
    print(f"\nModelo exportado a {MODEL_OUT}")
    print(f"Tamaño: {MODEL_OUT.stat().st_size / 1024:.0f} KB (2 salidas, archivo unico)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
