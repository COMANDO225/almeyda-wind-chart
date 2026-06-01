"""Arquitectura del modelo del NUMERO del viento (multi-cabeza, sin signo).

Mismo backbone que el NumberCNN del angulo pero con 2 cabezas en vez de 3:
  * `tens` (decena, 0..5)  → 6 clases
  * `ones` (unidad, 0..9)  → 10 clases

El viento es siempre positivo (rango 0-50), asi que no hay cabeza de signo.

`forward` devuelve TUPLA `(tens, ones)` de logits SIN softmax. El orden mapea
posicionalmente a `output_names` en el export ONNX y el reader hace softmax
y atan-equivalente (argmax) en numpy.
"""

from __future__ import annotations

import torch
import torch.nn as nn

from vision.detectors.wind_number_preprocess import (
    CANVAS_H,
    CANVAS_W,
    ONES_CLASSES,
    TENS_CLASSES,
)


def _conv_block(cin: int, cout: int) -> nn.Sequential:
    return nn.Sequential(
        nn.Conv2d(cin, cout, kernel_size=3, padding=1),
        nn.BatchNorm2d(cout),
        nn.ReLU(inplace=True),
        nn.MaxPool2d(2),
    )


class WindNumberCNN(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        # 32x64 -> 16x32 -> 8x16 -> 4x8 -> 2x4
        self.features = nn.Sequential(
            _conv_block(1, 16),
            _conv_block(16, 32),
            _conv_block(32, 64),
            _conv_block(64, 128),
        )
        feat_h = CANVAS_H // 16
        feat_w = CANVAS_W // 16
        flat = 128 * feat_h * feat_w
        self.shared = nn.Sequential(
            nn.Flatten(),
            nn.Linear(flat, 256),
            nn.ReLU(inplace=True),
            nn.Dropout(0.3),
        )
        self.head_tens = nn.Linear(256, TENS_CLASSES)
        self.head_ones = nn.Linear(256, ONES_CLASSES)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        z = self.shared(self.features(x))
        return self.head_tens(z), self.head_ones(z)
