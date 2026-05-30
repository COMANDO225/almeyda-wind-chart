"""Arquitectura de la CNN de NUMERO COMPLETO (1-2 digitos + signo).

Backbone convolucional compartido + 3 cabezas softmax (sign / tens / ones).
Patron SVHN multi-digito adaptado a 2 posiciones. Lee el numero entero del
recorte del HUD sin segmentar digitos (lo que rompia el modelo viejo).

El flatten del mapa final (no global pooling) conserva la posicion gruesa
izquierda/derecha — clave para que las cabezas razonen sobre el right-align
(unidades a la derecha, decena a su izquierda, signo global).

`forward` devuelve una TUPLA `(sign, tens, ones)` de logits SIN softmax
(igual que el modelo viejo exporta `logits`); el softmax se hace en el reader.
El orden de la tupla mapea posicionalmente a `output_names` en el export ONNX.
"""

from __future__ import annotations

import torch
import torch.nn as nn

from vision.detectors.number_preprocess import (
    CANVAS_H,
    CANVAS_W,
    ONES_CLASSES,
    SIGN_CLASSES,
    TENS_CLASSES,
)


def _conv_block(cin: int, cout: int) -> nn.Sequential:
    return nn.Sequential(
        nn.Conv2d(cin, cout, kernel_size=3, padding=1),
        nn.BatchNorm2d(cout),
        nn.ReLU(inplace=True),
        nn.MaxPool2d(2),
    )


class NumberCNN(nn.Module):
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
        self.head_sign = nn.Linear(256, SIGN_CLASSES)
        self.head_tens = nn.Linear(256, TENS_CLASSES)
        self.head_ones = nn.Linear(256, ONES_CLASSES)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        z = self.shared(self.features(x))
        return self.head_sign(z), self.head_tens(z), self.head_ones(z)
