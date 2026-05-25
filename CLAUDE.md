# CLAUDE.md — Guía rápida para Claude en este repo

Este archivo lo lee Claude al inicio de cada sesión. **Para contexto técnico
profundo (decisiones, bugs resueltos, aprendizajes), ver `CONTEXT.md`.**

## TL;DR

**ai-dragonbound** es un overlay externo en Tauri que detecta el HUD del juego
*Dragonbound* (ángulo de tiro, viento) con OCR y lo muestra en un panel
flotante con un compás de viento. Proyecto **hobby / aprendizaje**, NO producción.

Estado actual: **Fase 1 MVP funcional** — la app abre 3 ventanas (panel +
2 markers redimensionables), el loop captura cada 250 ms, el sidecar Python
RapidOCR lee los dígitos, y los eventos llegan al panel. Falta validar el
end-to-end con marker sobre el juego en vivo.

## Stack

| Capa | Tech | Versión |
|---|---|---|
| App shell | Tauri 2.x + SvelteKit 5 + TypeScript + Vite 6 | mainline |
| Rust core | tokio, xcap, image, anyhow, log + tauri-plugin-log + tauri-plugin-store | ver `src-tauri/Cargo.toml` |
| Frontend | Svelte 5 (runes obligatorias: `$state`, `$derived`, `$props`) | 5.x |
| OCR | **RapidOCR v3** (PaddleOCR PP-OCRv4 sobre ONNX Runtime) + opencv-python | ver `vision/requirements.txt` |
| Build (Win) | Rust + Build Tools 2026 (MSVC v143) + Windows SDK | — |

**Política**: nada de LLMs externos, solo modelos pre-entrenados locales.

## Arquitectura

Tauri lanza **3 ventanas** independientes, todas always-on-top y transparentes:

- `control_panel` (320×420) — compás de viento estilo dial + selector "Armor" + display de ángulo.
- `marker_wind` (300×300 ventana INVISIBLE) — adentro tiene un **rect interno** celeste 80×80 (drag/resize manual con esquineros).
- `marker_angle` (220×220 ventana INVISIBLE) — adentro **rect interno** 40×36.

**Concepto clave de los markers**: la ventana exterior está siempre vacía;
solo el rect interno es visible. Al arrastrar el cuerpo del rect, el
`data-tauri-drag-region` mueve la **ventana entera**. Al tirar de los handles,
JS recalcula `size` y llama `win.setSize() + setPosition()`. El rect siempre
vive en (PADDING=10, PADDING=10) dentro de su ventana.

**Por qué este diseño**: Windows impone un mínimo nativo (~112 px) para
ventanas top-level. Si la ventana fuera el rect mismo, no podría ir más
chica que 112×112. Con esta arquitectura el rect VISIBLE puede ser de 6×6
si querés (al ras del HUD del juego).

## Flujo de datos OCR (4 FPS)

```
Cada 250 ms en Tokio:
1. Rust lee local_rect de cada marker (en AppState, en coords del DOM dentro
   de su ventana, ej. x=10, y=10, w=40, h=36).
2. local_to_absolute(window_label, local_rect): suma window.outer_position()
   + scale_factor para obtener un Rect ABSOLUTO en pixels físicos de pantalla.
3. xcap captura esa región → PNG bytes.
4. Mando JSON {"type":"frame","detector":"wind|angle","frame_id":N,"png_b64":...}
   por stdin al sidecar Python.
5. Python (vision/main.py serve) decodifica el PNG, llama detectors.wind.detect()
   o detectors.angle.detect(), y devuelve JSON.
6. Rust deserializa, emite evento Tauri "detection:wind" o "detection:angle"
   al frontend.
7. Panel Svelte actualiza el compás (número + aguja rotada) y el display ángulo.
```

## Estructura de archivos (lo esencial)

```
ai-dragonbound/
├── CLAUDE.md / CONTEXT.md / README.md
├── package.json / vite.config.js / svelte.config.js / tsconfig.json
├── src/                                  ← frontend Svelte 5
│   ├── app.html
│   ├── lib/
│   │   ├── ipc.ts                        ← wrappers invoke/listen
│   │   ├── log.ts                        ← logging unificado al backend
│   │   ├── WindCompass.svelte            ← compás SVG estilo imagen 7
│   │   ├── MarkerFrame.svelte            ← rect interno con drag/resize manual
│   │   └── MobileSelector.svelte
│   └── routes/
│       ├── +layout.svelte / +layout.ts (SPA, no SSR)
│       ├── +page.svelte                  ← redirect a /panel
│       ├── panel/+page.svelte            ← UI principal
│       └── marker/+page.svelte           ← parametrizado por ?name=wind|angle
├── src-tauri/                            ← backend Rust
│   ├── Cargo.toml / tauri.conf.json / build.rs
│   ├── capabilities/default.json         ← permisos Tauri 2
│   ├── icons/
│   └── src/
│       ├── main.rs / lib.rs              ← bootstrap
│       ├── state.rs                      ← AppState + comandos rect + plugin-store
│       ├── capture.rs                    ← xcap → PNG bytes
│       ├── sidecar.rs                    ← spawn venv Python + IPC stdio JSON
│       └── loop_.rs                      ← Tokio 4 FPS
├── vision/                               ← sidecar Python
│   ├── main.py                           ← CLI: detect (imagen) y serve (stdio)
│   ├── pipeline.py                       ← (legacy, no usado en flujo Tauri)
│   ├── types.py                          ← pydantic models compartidos
│   ├── detectors/
│   │   ├── _ocr.py                       ← singleton RapidOCR + read_digits multi-strategy
│   │   ├── wind.py / angle.py            ← detectores con preprocesado por color
│   │   ├── power.py / mobiles.py / terrain.py  ← stubs (futuro)
│   └── scripts/
│       └── test_capture_02.py            ← test offline contra captura real
└── assets/
    ├── docs/hud_reference.png            ← guía visual anotada del HUD
    └── samples/                          ← screenshots reales (excluidos de git)
        ├── ground_truth.json             ← anotaciones manuales (sí commiteado)
        └── _debug/                       ← outputs de OCR strategies (gitignored)
```

## Comandos comunes

Desde la raíz `C:\projects\ai-dragonbound` (recordar que **`cargo` no está
en el PATH** de sesiones nuevas — añadir
`$env:PATH = "$env:USERPROFILE\.cargo\bin;$env:PATH"`):

```powershell
# Setup inicial (una vez)
npm install
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r vision\requirements.txt

# Desarrollo (frontend HMR + backend Rust recompile)
npm run tauri dev

# Test offline del sidecar OCR
$env:PYTHONIOENCODING = 'utf-8'
$env:VISION_DEBUG_DIR = "$PWD\assets\samples\_debug"
.\.venv\Scripts\python.exe -m vision.scripts.test_capture_02

# Tail log unificado en vivo
Get-Content "$env:LOCALAPPDATA\com.aidragonbound.app\logs\ai-dragonbound.log" -Wait -Tail 30

# Type-check
cd src-tauri ; cargo check ; cd ..
npm run check

# Linters
cd src-tauri ; cargo clippy --all-targets -- -D warnings ; cargo fmt ; cd ..

# Build instalador (.msi/.exe)
npm run tauri build
```

## Convenciones

- **Rust 2021**, `cargo fmt` + `clippy --all-targets`. Sin `unwrap()` fuera de
  tests/setup. Usar `?` con `anyhow::Result`. Logs con `log::info!` /
  `log::warn!` / `log::error!` (NO `tracing::*` — chocó con plugin-log).
- **Svelte 5**: runes obligatorias. Sin `$:` reactivos viejos. Sin `export let`,
  usar `$props()`.
- **Python**: type hints obligatorios. `ruff` para format+lint. pydantic para
  modelos compartidos con Tauri via JSON.
- **Comentarios**: minimal — solo el "por qué", no el "qué". Nombres descriptivos
  evitan comentarios.
- **Commits**: español, presente imperativo ("añade compás SVG", no "añadiendo").

## Tips para futuras sesiones

1. **El log unificado** está en `%LOCALAPPDATA%\com.aidragonbound.app\logs\ai-dragonbound.log`.
   Lleva logs de Svelte (`webview:...`) y Rust (`ai_dragonbound_lib::...`)
   en el mismo archivo con timestamp.
2. **`cargo` no está en PATH** por defecto en sesiones nuevas de PowerShell.
   Siempre `$env:PATH = "$env:USERPROFILE\.cargo\bin;$env:PATH"` antes.
3. **El sidecar Python necesita el venv del proyecto**. Si `.venv/` no existe
   o le faltan deps, `sidecar.rs` cae a `python` global y los detectores
   fallan silenciosamente. Verificar primero con `Test-Path .venv\Scripts\python.exe`.
4. **El loop de detección spamea logs** si los markers tienen rect 0×0 o si
   el sidecar no responde. Mirar el log y filtrar.
5. **Las capturas estáticas en `assets/samples/`** están en `.gitignore` por
   privacidad. Solo el `ground_truth.json` y `example.roi.json` van al repo.
6. **Cerrar el panel mata toda la app** — está hardcoded en `lib.rs`
   (`on_window_event` con `CloseRequested` + `app.exit(0)`).
7. **Cuando dudes del estado o de las decisiones técnicas**, leer `CONTEXT.md`
   antes de proponer cambios — ahí está el "por qué" de TODO.

## Aviso

Software educativo. NO usar en partidas competitivas si los TOS del juego lo prohíben.
