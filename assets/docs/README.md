# HUD reference

`hud_reference.png` es la captura anotada por el usuario indicando dónde está
cada elemento del HUD que debe leer el pipeline de visión.

| Etiqueta en la imagen | Detector responsable |
|---|---|
| **NÚMERO FUERZA DEL VIENTO** (verde dentro del círculo arriba) | `vision/detectors/wind.py::_read_magnitude` |
| **ÁNGULO DEL VIENTO** (flecha pequeña roja DENTRO del mismo círculo) | `vision/detectors/wind.py::_detect_pointer_direction` |
| **NÚMERO DE ÁNGULO** (amarillo grande en cajilla `LAST XX YY` HUD inferior-izq) | `vision/detectors/angle.py` |
| **BARRA DE FUERZA DE TIRO** (rectángulo horizontal HUD inferior-derecha) | `vision/detectors/power.py` |
| **NÚMERO DE TIEMPO** (rojo grande arriba-derecha + cartel azul sobre mobile activo) | **Ignorado** — es el timer del turno |

Las ROIs concretas (coordenadas en píxeles) viven en `assets/samples/example.roi.json`
y deben re-calibrarse para la resolución real de la pestaña del navegador.
