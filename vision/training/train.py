"""Entrena la CNN de digitos y exporta a ONNX (Sprint C.3).

Lee `assets/dataset/labeled/{0-9}/*.png` (generado por prepare_dataset.py),
aplica data augmentation, entrena la DigitCNN, evalua, y exporta el modelo
a `vision/models/digit_classifier.onnx`.

Uso:
    .\\.venv\\Scripts\\python.exe -m vision.training.train
    # opciones:
    #   --epochs 40      (default 40)
    #   --batch 64
    #   --no-cuda        forzar CPU

Augmentation (clave para potenciar el dataset chico):
    rotacion +-8 grados, escala +-15%, shear +-12 (simula cursiva),
    brillo/contraste, ruido gaussiano, traslacion. Multiplica las ~178
    muestras reales a miles de variantes efectivas.
"""
from __future__ import annotations

import argparse
import random
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset

from vision.training.model import DIGIT_SIZE, NUM_CLASSES, DigitCNN

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LABELED_DIR = PROJECT_ROOT / "assets" / "dataset" / "labeled"
MODEL_OUT = PROJECT_ROOT / "vision" / "models" / "digit_classifier.onnx"


def _augment(img: np.ndarray, rng: random.Random) -> np.ndarray:
    """Augmentation manual (sin albumentations para evitar dependencia dura).
    img: uint8 grayscale 32x32. Devuelve uint8 32x32."""
    h, w = img.shape
    out = img.copy()

    # Rotacion + escala + traslacion via matriz afin.
    angle = rng.uniform(-8, 8)
    scale = rng.uniform(0.85, 1.15)
    tx = rng.uniform(-2, 2)
    ty = rng.uniform(-2, 2)
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, scale)
    m[0, 2] += tx
    m[1, 2] += ty
    out = cv2.warpAffine(out, m, (w, h), borderValue=0)

    # Shear horizontal (simula cursiva variable).
    shear = rng.uniform(-0.21, 0.21)  # ~ +-12 grados
    ms = np.array([[1, shear, -shear * h / 2], [0, 1, 0]], dtype=np.float32)
    out = cv2.warpAffine(out, ms, (w, h), borderValue=0)

    # Brillo/contraste.
    alpha = rng.uniform(0.8, 1.2)  # contraste
    beta = rng.uniform(-25, 25)  # brillo
    out = np.clip(out.astype(np.float32) * alpha + beta, 0, 255).astype(np.uint8)

    # Ruido gaussiano.
    if rng.random() < 0.5:
        noise = rng.gauss(0, 1) * np.random.randn(h, w) * 12
        out = np.clip(out.astype(np.float32) + noise, 0, 255).astype(np.uint8)

    # Blur leve ocasional.
    if rng.random() < 0.3:
        out = cv2.GaussianBlur(out, (3, 3), 0)

    return out


class DigitDataset(Dataset):
    def __init__(self, samples: list[tuple[Path, int]], train: bool, mult: int = 1):
        self.samples = samples
        self.train = train
        self.mult = mult if train else 1
        self.rng = random.Random(1234)

    def __len__(self) -> int:
        return len(self.samples) * self.mult

    def __getitem__(self, idx: int):
        path, label = self.samples[idx % len(self.samples)]
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            img = np.zeros((DIGIT_SIZE, DIGIT_SIZE), dtype=np.uint8)
        if img.shape != (DIGIT_SIZE, DIGIT_SIZE):
            img = cv2.resize(img, (DIGIT_SIZE, DIGIT_SIZE))
        if self.train:
            img = _augment(img, self.rng)
        tensor = torch.from_numpy(img.astype(np.float32) / 255.0).unsqueeze(0)
        return tensor, label


def load_samples() -> list[tuple[Path, int]]:
    samples = []
    for d in range(10):
        for p in (LABELED_DIR / str(d)).glob("*.png"):
            samples.append((p, d))
    return samples


def split(samples, val_frac=0.15, seed=42):
    rng = random.Random(seed)
    by_class: dict[int, list] = {}
    for s in samples:
        by_class.setdefault(s[1], []).append(s)
    train, val = [], []
    for cls, items in by_class.items():
        rng.shuffle(items)
        n_val = max(1, int(len(items) * val_frac))
        val += items[:n_val]
        train += items[n_val:]
    rng.shuffle(train)
    rng.shuffle(val)
    return train, val


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--batch", type=int, default=64)
    parser.add_argument("--mult", type=int, default=20, help="repeticiones con augmentation por epoch")
    parser.add_argument("--no-cuda", action="store_true")
    args = parser.parse_args(argv)

    samples = load_samples()
    if len(samples) < 20:
        print(f"FALLO: muy pocas muestras ({len(samples)}). Corré prepare_dataset primero.")
        return 1
    train_s, val_s = split(samples)
    print(f"Muestras: {len(samples)} total | {len(train_s)} train | {len(val_s)} val")

    device = "cuda" if (torch.cuda.is_available() and not args.no_cuda) else "cpu"
    print(f"Device: {device}" + (f" ({torch.cuda.get_device_name(0)})" if device == "cuda" else ""))

    train_ds = DigitDataset(train_s, train=True, mult=args.mult)
    val_ds = DigitDataset(val_s, train=False)
    train_dl = DataLoader(train_ds, batch_size=args.batch, shuffle=True, num_workers=0)
    val_dl = DataLoader(val_ds, batch_size=args.batch, shuffle=False, num_workers=0)

    model = DigitCNN().to(device)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs)
    crit = nn.CrossEntropyLoss()

    best_acc = 0.0
    best_state = None
    for epoch in range(args.epochs):
        model.train()
        tloss = 0.0
        for x, y in train_dl:
            x, y = x.to(device), y.to(device)
            opt.zero_grad()
            out = model(x)
            loss = crit(out, y)
            loss.backward()
            opt.step()
            tloss += loss.item() * x.size(0)
        sched.step()

        # Validacion
        model.eval()
        correct = 0
        per_class_ok = [0] * 10
        per_class_tot = [0] * 10
        with torch.no_grad():
            for x, y in val_dl:
                x, y = x.to(device), y.to(device)
                pred = model(x).argmax(1)
                correct += (pred == y).sum().item()
                for yi, pi in zip(y.tolist(), pred.tolist()):
                    per_class_tot[yi] += 1
                    if yi == pi:
                        per_class_ok[yi] += 1
        acc = correct / max(1, len(val_ds))
        if (epoch + 1) % 5 == 0 or epoch == args.epochs - 1:
            print(f"  epoch {epoch + 1:2d}/{args.epochs}  loss={tloss / len(train_ds):.4f}  val_acc={acc:.3f}")
        if acc >= best_acc:
            best_acc = acc
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

    print(f"\nMejor val_acc: {best_acc:.3f}")
    print("Accuracy por digito (val):")
    for d in range(10):
        tot = per_class_tot[d]
        ok = per_class_ok[d]
        pct = ok / tot if tot else 0
        print(f"  {d}: {ok}/{tot}  ({pct:.0%})")

    # Cargar mejor estado y exportar a ONNX.
    if best_state:
        model.load_state_dict(best_state)
    model.eval()
    MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)
    dummy = torch.randn(1, 1, DIGIT_SIZE, DIGIT_SIZE, device=device)
    torch.onnx.export(
        model, dummy, str(MODEL_OUT),
        input_names=["input"], output_names=["logits"],
        dynamic_axes={"input": {0: "batch"}, "logits": {0: "batch"}},
        opset_version=17,
    )

    # El exportador nuevo (PyTorch 2.6+) separa los pesos en un .onnx.data
    # aparte. Consolidamos todo en un unico .onnx para distribuir mas facil.
    import onnx as _onnx

    consolidated = _onnx.load(str(MODEL_OUT))
    _onnx.save_model(consolidated, str(MODEL_OUT), save_as_external_data=False)
    data_file = MODEL_OUT.parent / (MODEL_OUT.name + ".data")
    if data_file.exists():
        data_file.unlink()

    print(f"\nModelo exportado a {MODEL_OUT}")
    print(f"Tamaño: {MODEL_OUT.stat().st_size / 1024:.0f} KB (pesos embebidos, archivo unico)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
