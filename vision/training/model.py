"""Arquitectura de la CNN de clasificacion de digitos (0-9).

Red pequena (~3 conv + 2 FC, ~60k params) — suficiente para 10 clases con
imagenes de 32x32 en escala de grises. Entrena en segundos en una RTX 5080
y corre en <1 ms por inferencia (ONNX Runtime).

Diseno deliberadamente chico: con ~178 muestras reales (+ augmentation),
un modelo grande haria overfitting. Esta capacidad es la adecuada.
"""
from __future__ import annotations

import torch
import torch.nn as nn

DIGIT_SIZE = 32
NUM_CLASSES = 10


class DigitCNN(nn.Module):
    def __init__(self, num_classes: int = NUM_CLASSES) -> None:
        super().__init__()
        self.features = nn.Sequential(
            # 32x32 -> 16x16
            nn.Conv2d(1, 16, kernel_size=3, padding=1),
            nn.BatchNorm2d(16),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            # 16x16 -> 8x8
            nn.Conv2d(16, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            # 8x8 -> 4x4
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
        )
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Linear(64 * 4 * 4, 128),
            nn.ReLU(inplace=True),
            nn.Dropout(0.3),
            nn.Linear(128, num_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.classifier(self.features(x))
