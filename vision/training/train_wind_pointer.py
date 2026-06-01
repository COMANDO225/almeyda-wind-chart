"""Entrena la CNN del PUNTERO del viento y exporta a ONNX.

Lee `assets/dataset/raw/wind_pointer/*.png` + `labels_wind_pointer.json`
(angulo float 0-360°, etiquetado con `label_wind_pointer.py`) y entrena un
modelo de regresion angular (sin, cos). Exporta a
`vision/models/wind_pointer.onnx` (1 entrada, 1 salida vector unitario 2D,
opset 17, archivo unico).

AUGMENTATION CLAVE — rotaciones random CON ajuste del label: rotamos la
imagen θ grados (cv2 antihorario para angles+) y RESTAMOS θ al label
(porque nuestra convencion es horario, asi que rotar antihorario en
pantalla *resta* angulo en proyecto). Esto multiplica el dataset por ~N
"vistas" del mismo recorte cubriendo todo el rango 360° — con 100 capturas
reales tenemos efectivamente miles de variantes.

Color/brillo/contraste agresivos para resistir filtros de torneo (la forma
del puntero es invariante, solo cambia la capa de color).

Uso:
    .\\.venv\\Scripts\\python.exe -m vision.training.train_wind_pointer
        # --epochs 120 --batch 64 --mult 30 --kfold 5 --no-cuda
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

from vision.detectors.wind_pointer_preprocess import (
    CANVAS,
    angle_to_xy,
    angular_distance,
    to_canvas,
    xy_to_angle,
)
from vision.training.wind_pointer_model import WindPointerCNN

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RAW_DIR = PROJECT_ROOT / "assets" / "dataset" / "raw" / "wind_pointer"
LABELS_PATH = PROJECT_ROOT / "assets" / "dataset" / "labels_wind_pointer.json"
MODEL_OUT = PROJECT_ROOT / "vision" / "models" / "wind_pointer.onnx"


def _augment(
    canvas_uint8: np.ndarray, angle_deg: float, rng: random.Random
) -> tuple[np.ndarray, float]:
    """Rotacion random + ajuste del label + jitter de brillo/contraste/ruido.

    cv2.getRotationMatrix2D(angle=+rot) rota ANTIHORARIO en coords de pantalla.
    Nuestra convencion del angulo es HORARIA (0=derecha, 90=abajo crece horario).
    Entonces si rotamos la imagen +rot, el puntero en la nueva imagen apunta a
    `angle_deg - rot` en nuestra convencion.
    """
    h, w = canvas_uint8.shape
    out = canvas_uint8.copy()

    # 1) Rotacion random CHICA: el dataset sintetico ya cubre 360° denso (cada
    #    5°), asi que solo llenamos el hueco entre angulos generados (±3°). Una
    #    rotacion grande aqui rotaria el radar/digitos a poses irreales (el radar
    #    no rota en el juego) y desperdiciaria capacidad. El ajuste de label se
    #    mantiene: rotar la imagen +rot resta rot al angulo (convencion horaria).
    rot = rng.uniform(-3.0, 3.0)
    m = cv2.getRotationMatrix2D((w / 2, h / 2), rot, 1.0)
    out = cv2.warpAffine(out, m, (w, h), borderValue=0)
    new_angle = (angle_deg - rot) % 360.0

    # 2) Jitter agresivo de brillo/contraste — resiliencia a filtros de torneo.
    alpha = rng.uniform(0.65, 1.35)
    beta = rng.uniform(-40, 40)
    out = np.clip(out.astype(np.float32) * alpha + beta, 0, 255).astype(np.uint8)

    if rng.random() < 0.5:
        noise = np.random.randn(h, w) * 12.0
        out = np.clip(out.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    if rng.random() < 0.3:
        out = cv2.GaussianBlur(out, (3, 3), 0)

    return out, new_angle


def _worker_init_fn(worker_id: int) -> None:
    """Re-siembra el rng del dataset por worker (sin esto los N workers harian
    la misma secuencia de augmentation y la diversidad caeria a 1/N)."""
    info = torch.utils.data.get_worker_info()
    if info is not None:
        info.dataset.rng = random.Random(1234 + worker_id)
        np.random.seed(1234 + worker_id)


class PointerDataset(Dataset):
    def __init__(self, samples: list[tuple[np.ndarray, float]], train: bool, mult: int = 1):
        self.samples = samples
        self.train = train
        self.mult = mult if train else 1
        self.rng = random.Random(1234)

    def __len__(self) -> int:
        return len(self.samples) * self.mult

    def __getitem__(self, idx: int):
        canvas, angle = self.samples[idx % len(self.samples)]
        if self.train:
            canvas, angle = _augment(canvas, angle, self.rng)
        x = torch.from_numpy(canvas.astype(np.float32) / 255.0).unsqueeze(0)
        sin_v, cos_v = angle_to_xy(angle)
        y = torch.tensor([sin_v, cos_v], dtype=torch.float32)
        return x, y


def load_samples() -> list[tuple[np.ndarray, float]]:
    labels = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    labels = {k: float(v) for k, v in labels.items()}
    samples = []
    skipped = 0
    for fname, angle in labels.items():
        path = RAW_DIR / fname
        if not path.exists():
            skipped += 1
            continue
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            skipped += 1
            continue
        samples.append((to_canvas(img), angle))
    if skipped:
        print(f"  ({skipped} muestras saltadas: archivo ausente o ilegible)")
    return samples


def _strat_key(s: tuple[np.ndarray, float]) -> int:
    """Estrato para split balanceado: octante angular (0-7)."""
    return int((s[1] % 360.0) // 45.0)


def stratified_folds(samples: list, k: int, seed: int = 42):
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


def stratified_split(samples: list, val_frac=0.15, seed=42):
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


def _angular_loss(pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    """1 - cos(theta_pred - theta_true). pred y target son vectores unitarios.

    cos(a-b) = sin(a)sin(b) + cos(a)cos(b) = pred · target (cuando |pred|=|target|=1).
    Loss en [0, 2], 0 = perfecto, 2 = 180° de error. Suave y diferenciable.
    """
    cos_diff = (pred * target).sum(dim=1)
    return (1.0 - cos_diff).mean()


@torch.no_grad()
def evaluate(model: nn.Module, samples: list, device: str) -> dict:
    model.eval()
    if not samples:
        return {"mean_err_deg": 0.0, "median_err_deg": 0.0, "p90_err_deg": 0.0, "n": 0}
    batch = (
        torch.from_numpy(np.stack([s[0].astype(np.float32) / 255.0 for s in samples]))
        .unsqueeze(1)
        .to(device)
    )
    pred = model(batch).cpu().numpy()
    errs = []
    for i, (_, true_angle) in enumerate(samples):
        sin_v, cos_v = float(pred[i, 0]), float(pred[i, 1])
        pred_angle = xy_to_angle(sin_v, cos_v)
        errs.append(angular_distance(pred_angle, true_angle))
    errs_np = np.array(errs)
    return {
        "mean_err_deg": float(errs_np.mean()),
        "median_err_deg": float(np.median(errs_np)),
        "p90_err_deg": float(np.percentile(errs_np, 90)),
        "n": len(samples),
    }


def train_once(train_s, val_s, args, device, verbose=False) -> tuple[dict, dict]:
    use_workers = args.workers > 0
    train_dl = DataLoader(
        PointerDataset(train_s, train=True, mult=args.mult),
        batch_size=args.batch,
        shuffle=True,
        num_workers=args.workers,
        pin_memory=(device == "cuda"),
        persistent_workers=use_workers,
        prefetch_factor=2 if use_workers else None,
        drop_last=True,
        worker_init_fn=_worker_init_fn if use_workers else None,
    )
    model = WindPointerCNN().to(device)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs)
    scaler = torch.amp.GradScaler("cuda") if (args.amp and device == "cuda") else None

    best_err = float("inf")
    best_state = None
    best_metrics = {}
    for epoch in range(args.epochs):
        model.train()
        tloss = 0.0
        for x, y in train_dl:
            x = x.to(device, non_blocking=use_workers)
            y = y.to(device, non_blocking=use_workers)
            opt.zero_grad(set_to_none=True)
            if scaler is not None:
                with torch.amp.autocast("cuda"):
                    loss = _angular_loss(model(x), y)
                scaler.scale(loss).backward()
                scaler.step(opt)
                scaler.update()
            else:
                loss = _angular_loss(model(x), y)
                loss.backward()
                opt.step()
            tloss += loss.item() * x.size(0)
        sched.step()

        m = evaluate(model, val_s, device)
        if verbose and ((epoch + 1) % 10 == 0 or epoch == args.epochs - 1):
            print(
                f"  epoch {epoch + 1:3d}/{args.epochs}  loss={tloss / len(train_dl.dataset):.4f}"
                f"  mean={m['mean_err_deg']:.2f}°  median={m['median_err_deg']:.2f}°"
                f"  p90={m['p90_err_deg']:.2f}°"
            )
        if m["mean_err_deg"] < best_err:
            best_err = m["mean_err_deg"]
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            best_metrics = m
    return best_state, best_metrics


def export_onnx(state: dict, device: str) -> None:
    model = WindPointerCNN().to(device)
    model.load_state_dict(state)
    model.eval()
    MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)
    dummy = torch.randn(1, 1, CANVAS, CANVAS, device=device)
    torch.onnx.export(
        model,
        dummy,
        str(MODEL_OUT),
        input_names=["input"],
        output_names=["sincos"],
        dynamic_axes={"input": {0: "batch"}, "sincos": {0: "batch"}},
        # opset 18 (no 17 como los otros modelos): el forward normaliza el
        # vector (sin,cos) con torch.norm → genera un nodo que el conversor a
        # opset 17 no sabe traducir y tiraba un traceback feo (aunque exportaba
        # igual en 18). onnxruntime >=1.20 soporta 18 sin problema.
        opset_version=18,
    )
    import onnx as _onnx

    consolidated = _onnx.load(str(MODEL_OUT))
    _onnx.save_model(consolidated, str(MODEL_OUT), save_as_external_data=False)
    data_file = MODEL_OUT.parent / (MODEL_OUT.name + ".data")
    if data_file.exists():
        data_file.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # Defaults para dataset sintetico DENSO (cada 5°): mult bajo (ya hay
    # cobertura 360°), batch grande, workers paralelos para alimentar la GPU.
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--batch", type=int, default=256)
    parser.add_argument(
        "--mult", type=int, default=3, help="repeticiones con augmentation por epoch"
    )
    parser.add_argument("--kfold", type=int, default=5, help="folds de CV (0 = saltar)")
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="procesos paralelos del DataLoader; 0 = single-thread (lento)",
    )
    parser.add_argument(
        "--amp",
        action="store_true",
        help="mixed precision fp16 — exprime los Tensor Cores (2-3x speedup)",
    )
    parser.add_argument("--no-cuda", action="store_true")
    args = parser.parse_args(argv)

    if not LABELS_PATH.exists():
        print(f"FALLO: no existe {LABELS_PATH}. Etiqueta primero con label_wind_pointer.")
        return 1
    print("Cargando muestras...")
    samples = load_samples()
    if len(samples) < 20:
        print(f"FALLO: muy pocas muestras ({len(samples)}). Captura mas con F3.")
        return 1
    # Histograma por octante para chequear cobertura angular.
    octs = [0] * 8
    for s in samples:
        octs[_strat_key(s)] += 1
    print(f"Muestras: {len(samples)} | por octante (0-45°,45-90°,...): {octs}")

    device = "cuda" if (torch.cuda.is_available() and not args.no_cuda) else "cpu"
    if device == "cuda":
        torch.backends.cudnn.benchmark = True
    print(f"Device: {device}" + (f" ({torch.cuda.get_device_name(0)})" if device == "cuda" else ""))
    extras = [f"workers={args.workers}", f"batch={args.batch}", f"mult={args.mult}"]
    if args.amp:
        extras.append("amp=fp16")
    print(f"Config: {', '.join(extras)}")

    if args.kfold and args.kfold > 1:
        print(f"\n=== Validacion cruzada {args.kfold}-fold ===")
        accs = {"mean": [], "median": [], "p90": []}
        for i, (tr, va) in enumerate(stratified_folds(samples, args.kfold)):
            _, m = train_once(tr, va, args, device)
            accs["mean"].append(m["mean_err_deg"])
            accs["median"].append(m["median_err_deg"])
            accs["p90"].append(m["p90_err_deg"])
            print(
                f"  fold {i + 1}/{args.kfold} (val n={m['n']}): "
                f"mean={m['mean_err_deg']:.2f}° median={m['median_err_deg']:.2f}° "
                f"p90={m['p90_err_deg']:.2f}°"
            )
        print("  --- media k-fold ---")
        print(f"    mean error:   {np.mean(accs['mean']):.2f}°")
        print(f"    median error: {np.mean(accs['median']):.2f}°")
        print(f"    p90 error:    {np.mean(accs['p90']):.2f}°")

    print("\n=== Modelo FINAL (split estratificado, exporta el mejor) ===")
    train_s, val_s = stratified_split(samples)
    print(f"  {len(train_s)} train | {len(val_s)} val")
    best_state, m = train_once(train_s, val_s, args, device, verbose=True)
    print(
        f"  mejor val: mean={m['mean_err_deg']:.2f}° median={m['median_err_deg']:.2f}° "
        f"p90={m['p90_err_deg']:.2f}°"
    )

    if not best_state:
        print("FALLO: no se entreno ningun modelo.")
        return 1
    export_onnx(best_state, device)
    print(f"\nModelo exportado a {MODEL_OUT}")
    print(f"Tamaño: {MODEL_OUT.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
