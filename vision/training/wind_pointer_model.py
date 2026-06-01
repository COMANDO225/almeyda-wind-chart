"""Arquitectura del modelo del PUNTERO del viento (regresion angular).

Backbone CNN compacto + cabeza de 2 floats que el `forward` normaliza a
vector unitario (sin, cos). Decodificacion con atan2 en el reader.

Por que (sin, cos) y no regresion directa de grados: el angulo es circular
(359° y 1° estan cerca pero lejos como numeros). El vector unitario evita
ese wrap-around — la loss `1 - cos(theta_pred - theta_true)` es siempre
suave y bien definida.

Input grayscale ~64x64 (forma fija del puntero, color invariante).
"""

from __future__ import annotations

import torch
import torch.nn as nn

from vision.detectors.wind_pointer_preprocess import CANVAS, CHANNELS


def _conv_block(cin: int, cout: int) -> nn.Sequential:
    return nn.Sequential(
        nn.Conv2d(cin, cout, kernel_size=3, padding=1),
        nn.BatchNorm2d(cout),
        nn.ReLU(inplace=True),
        nn.MaxPool2d(2),
    )


class WindPointerCNN(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        # 64 -> 32 -> 16 -> 8 -> 4
        self.features = nn.Sequential(
            _conv_block(CHANNELS, 16),
            _conv_block(16, 32),
            _conv_block(32, 64),
            _conv_block(64, 128),
        )
        flat = 128 * (CANVAS // 16) * (CANVAS // 16)
        self.shared = nn.Sequential(
            nn.Flatten(),
            nn.Linear(flat, 256),
            nn.ReLU(inplace=True),
            nn.Dropout(0.3),
        )
        # 2 floats: (sin, cos). El forward los normaliza a vector unitario.
        self.head = nn.Linear(256, 2)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        v = self.head(self.shared(self.features(x)))
        n = torch.norm(v, dim=1, keepdim=True).clamp(min=1e-6)
        return v / n  # shape (N, 2), |v|=1
