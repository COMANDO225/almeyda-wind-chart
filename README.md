# ai-dragonbound

Overlay externo con análisis de trayectoria por IA para Dragonbound.

Proyecto **hobby / aprendizaje** sobre cómo identificar trayectorias reales de un juego usando visión por computador + OCR + ML modernos, sin tocar el juego.

## Stack

- **Tauri 2.x** (Rust) — shell de la app, ventanas-marcador flotantes, captura de pantalla.
- **Svelte** — frontend de las ventanas.
- **Python sidecar** — pipeline de visión con PaddleOCR + OpenCV (pre-entrenados, sin training propio en MVP).
- **ONNX Runtime + DirectML** — inferencia GPU portable en Windows (cuando lleguemos a YOLO en Fase 4+).

## Arquitectura de ventanas-marcador

A diferencia de un overlay único que cubre todo el juego, **cada elemento detectable es su propia ventana Tauri pequeña que el usuario coloca sobre el HUD correspondiente**. Más robusta a efectos visuales, performance, y cambios de UI del juego.

| Ventana | Tamaño aprox. | Tipo | Propósito |
|---|---|---|---|
| `control_panel` | 320×400 | Normal con bordes | Selector de mobile, displays de viento+ángulo detectados, controles |
| `marker_wind` | ~60×60 | Transparente, redimensionable con esquineros | Se coloca sobre el círculo del viento del juego. OCR lee el número de magnitud + estima dirección de la aguja |
| `marker_angle` | ~80×30 | Transparente, redimensionable | Se coloca sobre la cajilla "LAST XX YY" del HUD inferior. OCR lee el ángulo actual |
| `corner_top_left` / `corner_bottom_right` | ~24×24 | Mini, transparente, draggable | Definen el rectángulo del área del juego — **solo para saber dónde dibujar la trayectoria**, NO para detección |
| `trajectory_overlay` | tamaño del área del juego | Transparente, click-through | Canvas que renderiza la línea de trayectoria predicha |

**No incluido en MVP**:
- Marcador de barra de fuerza — la potencia entra manual o se ignora por ahora.
- Detector de mobiles — la selección del mobile es manual desde el panel.
- Detector de terreno — se modela manualmente o se asume terreno plano en Fase 3.

## Mecánica del juego (relevante para Fase 3 — física)

- **Fuerza de tiro**: rango 0.0 – 4.0 (100% = 4.0). La barra horizontal del juego tiene 3 marcas internas (~25%, 50%, 75%).
- **Peso de la bala**: difiere por mobile. Un mobile con bala de peso 2.0 puede llegar más lejos que otro con 2.5, porque también cambian otras constantes físicas (gravedad relativa, sensibilidad al viento).
- **Ángulo**: 0–90° leídos del HUD inferior-izquierdo.
- **Viento**: 0–99 (magnitud) + 0–360° (dirección de la aguja).
- **MVP empieza con Armor** (tanque rojo) como mobile más simple antes de pasar a Trico, Turtle, Bigfoot.

## Estructura

```
ai-dragonbound/
├── src-tauri/         # App Tauri (Rust) — Fase 1+
├── src/               # Frontend Svelte — Fase 1+
├── vision/            # Sidecar Python — Fase 0
│   ├── main.py        # CLI detect / serve
│   ├── pipeline.py    # process_frame()
│   ├── detectors/     # wind, angle, power (out-of-scope), mobiles, terrain
│   └── models/
└── assets/
    ├── docs/          # hud_reference.png (guía visual anotada del HUD)
    ├── mobiles/       # Sprites de referencia para template matching
    └── samples/       # Capturas reales del juego + ground_truth.json
```

## ¿Entrenamos modelos?

**No en MVP.** Los detectores son wrappers que orquestan modelos pre-entrenados:
- **PaddleOCR PP-OCRv4** — pre-entrenado por Baidu, descargado on-demand. Lee texto.
- **OpenCV** — algoritmos clásicos (HSV, contornos, Otsu), no es ML.

Solo entrenaríamos custom si PaddleOCR fallara con la fuente del juego (clasificador de dígitos), o si template matching no detectara los mobiles (YOLOv11 fine-tuned). Esto es **opcional, Fase 4+**.

## Plan por fases

Ver el plan completo en `~/.claude/plans/image-3-quiero-desaarrollar-squishy-gosling.md`.

- **Fase 0** (en curso): prototipo de visión Python sobre capturas estáticas — gate de viabilidad.
- **Fase 1**: esqueleto Tauri con las ventanas-marcador (wind, angle, corners, panel, overlay).
- **Fase 2**: integración del sidecar Python con Tauri.
- **Fase 3**: render del overlay + física del Armor (mobile más simple).
- **Fase 4**: mobiles con física especial (Trico, Turtle, Bigfoot, etc.).
- **Fase 5**: polish, hotkeys, calibración asistida.

## Aviso

Software educativo. No usar en partidas competitivas si los TOS del juego lo prohíben.
