# CONTEXT.md — Documento técnico extenso

> Para la guía rápida, ver `CLAUDE.md`. Este archivo profundiza en
> decisiones, bugs resueltos, aprendizajes y rationale técnico. Pensado
> para una persona (o Claude) que llega al proyecto sin contexto y necesita
> entender no solo el "qué" sino el "por qué".

---

## 1. Visión del proyecto

### 1.1 Qué construye

Un **overlay externo** (no extensión, no mod, no memoria) para el juego
**Dragonbound** (cliente web). La app captura por pantalla las regiones donde
el juego muestra el HUD (medidor de viento + ángulo de tiro) y las muestra
en un panel propio con un compás de viento estilo dial.

El objetivo a largo plazo es agregar:
1. Detección de potencia.
2. Detección de la posición de los mobiles (avatares de los jugadores).
3. Cálculo de la trayectoria parabólica que se renderizaría como un overlay
   sobre el juego, considerando la física específica de cada mobile
   (Trico, Turtle, Bigfoot, Armor, etc.).

### 1.2 Por qué este enfoque (externo, no mod)

El usuario eligió:
- **No tocar el cliente del juego** (es un proyecto de aprendizaje sobre CV+IA,
  no de cheating).
- **No usar LLMs en runtime** — para que el sistema sea escalable y predecible
  sin dependencias de APIs externas.
- **Usar tecnología SOTA local** (RapidOCR, Tauri 2, ONNX Runtime).

### 1.3 No es producción

Está aclarado en el README, CLAUDE.md y aquí: **NO usar en partidas
competitivas** si los TOS del juego lo prohíben. Es para aprendizaje y
exploración técnica.

---

## 2. Estado actual (snapshot a la fecha del último commit)

### 2.1 Lo que funciona ✅

- **3 ventanas Tauri** se abren: panel + marker_wind + marker_angle.
- **Panel transparente** con compás SVG estilo dial (negro mate + marcas
  naranjas + aguja roja con destello).
- **Markers con arquitectura "ventana sigue al rect"**:
  - El usuario arrastra el cuerpo del rect → la ventana entera se mueve
    vía `data-tauri-drag-region`.
  - El usuario tira de los handles (4 bordes + 4 esquineros) → JS
    recalcula `size` y llama `win.setSize() + setPosition()`.
  - Resize es estable (no más bug de "volar hacia arriba" — usamos
    `e.movementX/Y` acumulado en lugar de `e.screenX/Y - startScreenY`).
- **Loop de detección a 4 FPS** automático al abrir.
- **Sidecar Python** arranca correctamente desde el venv del proyecto.
- **OCR validado offline** contra la captura
  `02_aero_trico-vs-armor_a77_p75_w02.png` — lee `77` (ángulo) y `2`
  (viento) con confidencia razonable.
- **Logs unificados** Svelte + Rust en
  `%LOCALAPPDATA%\com.aidragonbound.app\logs\ai-dragonbound.log` vía
  `tauri-plugin-log`.
- **Persistencia** del tamaño del rect entre sesiones con `tauri-plugin-store`.
- **Cerrar el panel mata toda la app** (Ctrl+C-like UX).

### 2.2 Lo que falta validar

- **End-to-end con marker en vivo sobre la pantalla**: que el usuario
  arrastre el marker_wind sobre el HUD del juego (o cualquier número), y
  que el panel actualice el compás con el valor leído. Esta es **la
  prueba de resiliencia OCR** del MVP. Cuando se haga, marcará Fase 1 como
  cerrada.

### 2.3 Out of scope para Fase 1

- Marcador de barra de fuerza (potencia) — el usuario lo sacó del scope.
- Esquineros TL+BR del área de juego — para Fase 3 (render de trayectoria).
- Detección de mobiles en pantalla — Fase 4.
- Más mobiles aparte de Armor — Fase 4.
- Empaquetar Python como sidecar standalone con PyInstaller — Fase 2.
- Hotkeys globales, wizard de calibración — Fase 5.

---

## 3. Stack y decisiones

### 3.1 Por qué Tauri 2, no Electron / WPF / PyQt

- **vs Electron**: Tauri produce binarios ~10× más pequeños (~15 MB vs
  ~150 MB), arranca más rápido, mejor soporte de ventanas transparentes
  click-through en Windows.
- **vs WPF/WinUI**: multiplataforma (si más adelante Linux/Mac), mejor
  frontend (web stack), npm ecosystem.
- **vs PyQt**: distribución más limpia, separación cleanly UI de visión.

### 3.2 Por qué SvelteKit + TypeScript

- Templates oficiales de `create-tauri-app` ofrecen Svelte / React / Vue.
- Svelte 5 con runes es lo más nuevo y limpio. Runtime es chico.
- TypeScript: standard profesional, errors en build, mejor DX.
- SvelteKit (no Svelte vanilla) porque maneja routing — útil para 3
  ventanas distintas con URLs distintas (`/panel`, `/marker?name=wind`,
  `/marker?name=angle`).

### 3.3 Por qué RapidOCR v3 (no PaddleOCR / Tesseract / EasyOCR)

**Investigado en 2026**, comparando con 5 alternativas:

| Tool | Tamaño | Velocidad | Accuracy dígitos | Veredicto |
|---|---|---|---|---|
| PaddleOCR PP-OCRv5 | ~700 MB | Medio | ⭐⭐⭐⭐⭐ | Mejor precisión pero pesado |
| **RapidOCR v3** | ~200 MB | Rápido | ⭐⭐⭐⭐ | **Elegido** |
| Surya | ~700 MB | Lento | ⭐⭐⭐⭐ | Overkill |
| EasyOCR | ~500 MB | Lento | ⭐⭐ | Confusión $/dígitos |
| Tesseract | ~50 MB | Rápido | ⭐⭐ con fuente pixelada | Falla |

RapidOCR v3 usa los **mismos modelos** de PaddleOCR (PP-OCRv4 mobile)
pero portados a ONNX Runtime — accuracy equivalente, 1.5-2× más rápido,
sin la pesadez de `paddlepaddle`. Soporta GPU vía DirectML en Windows.

### 3.4 Por qué `xcap` (no `windows-capture`, no `mss`)

- `windows-capture` (envoltura de Windows.Graphics.Capture API): mejor
  performance teórica, pero API más compleja.
- `mss` (Python): solo Python, sería sidecar overhead.
- **`xcap`** (Rust): cross-platform, API simple
  (`Monitor::all() → capture_image()`), ~5-15 ms por captura, suficiente
  para 4 FPS.

### 3.5 Por qué un sidecar Python (no Rust puro)

- OCR de calidad (PaddleOCR/RapidOCR) en Rust es inmaduro.
- OpenCV + numpy + pydantic en Python es battle-tested.
- IPC stdio JSON es liviano (~5 ms overhead).
- En Fase 2 empaquetaremos con PyInstaller dentro del bundle Tauri →
  invisible para el usuario final.

### 3.6 Por qué `log` (no `tracing`)

Originalmente usé `tracing` + `tracing-subscriber::fmt().init()`. Pero
`tauri-plugin-log` también inicializa un global logger del crate `log`, y
los dos sistemas chocan: panic `"attempted to set a logger after the
logging system was already initialized"`.

Solución: reemplazar `tracing::*!` por `log::*!` en todo el código Rust y
dejar que `tauri-plugin-log` sea el subscriber global. Más simple, mismo
resultado.

---

## 4. Bugs resueltos importantes

### 4.1 El problema del mínimo de Windows (~112 px)

**Síntoma**: el usuario no podía hacer los markers tan pequeños como el
HUD del juego (el "77" amarillo es ~30 px). Aunque ponía `minWidth: 1`
en `tauri.conf.json`, las ventanas no bajaban de ~112×40.

**Causa raíz**: Windows tiene una constante `SM_CXMIN` = ~112 px que el
SO impone vía `WM_GETMINMAXINFO` a TODAS las ventanas top-level, ignorando
el `minWidth` de la app. Documentado por Microsoft.

**Solución**: refactorizar a "ventana grande invisible + rect interno
visible" (Opción A discutida con el usuario). La ventana mide siempre
**rect + 2×PADDING** (mínimo del SO si rect es chico). El rect VISIBLE
puede ser de 6×6 si queremos — queda chico dentro de una ventana mínima
112×112 que es transparente y no se ve.

Después una **segunda refinación**: el usuario propuso que la ventana
"siga" al rect. Drag rect = drag ventana. Resize rect = resize ventana.
Esto es lo que está implementado actualmente.

### 4.2 El resize "volaba hacia arriba"

**Síntoma**: al tirar del handle NW (esquinero superior izquierdo) del
rect, la ventana se iba volando hacia arriba sin parar hasta salirse de
la pantalla.

**Causa**: usaba `dy = e.screenY - drag.startScreenY` (delta acumulado
desde el inicio del drag). Pero al llamar `setPosition()` durante el
drag, Windows reposiciona el cursor relativo al handle, lo que altera
`screenY` en el siguiente evento. Resultado: dy crece sin control,
setPosition mueve más la ventana, ciclo realimentado.

**Solución**: usar `e.movementX/Y` (delta entre eventos consecutivos,
inmune a teletransportes de cursor) acumulado en `drag.accumDx/Dy`. Y
para `setPosition`, usar la posición **inicial** de la ventana
(`drag.startWinX`) + shift acumulado, no la posición actual.

### 4.3 El conflicto data-tauri-drag-region vs resize handles

**Síntoma**: los handles de resize no funcionaban — el click los
ignoraba y arrastraba la ventana entera.

**Causa**: Tauri intercepta los clicks en `data-tauri-drag-region` a
nivel **nativo** (Win32 API), antes de que el evento llegue al DOM. Si
ponemos `data-tauri-drag-region` en el contenedor padre de los handles,
los handles nunca reciben `pointerdown`.

**Solución**: separar la zona de drag de los handles. El frame del
marker tiene una sub-zona `.body` con `data-tauri-drag-region` (que cubre
el interior del rect dejando 4-6 px de gap), y los handles viven en ese
gap exterior.

### 4.4 El sidecar Python rechazaba frames "sin config"

**Síntoma**: el log spameaba `[serve] frame recibido sin config —
descartado`.

**Causa**: el código antiguo de `cmd_serve` esperaba un mensaje
`{"type":"config","config":{...}}` antes de procesar frames. Pero el
backend Rust nunca lo manda — Rust envía directamente el PNG
**ya recortado** al ROI del marker.

**Solución**: simplificar `cmd_serve` para procesar frames directamente.
Cada mensaje trae `detector: "wind"|"angle"` y el PNG. El sidecar no
necesita config global. Más simple y elegante.

### 4.5 RapidOCR no detectaba la fuente pixelada del juego

**Síntoma**: el detector de cajas de RapidOCR (PP-OCRv4 det) devolvía
"text detection result is empty" sobre el "77" amarillo del HUD.

**Causa**: PP-OCRv4 det está entrenado para texto de documentos
(fuentes legibles, fondos limpios). Las fuentes cartoon/pixeladas del
juego no son reconocidas como texto por el detector.

**Solución**: skip detection y usar **rec-only mode** —
`engine(img, use_det=False, use_rec=True)`. Como nosotros ya recortamos
la ROI al texto, no necesitamos detección. Para casos donde la imagen
tenga múltiples dígitos separados (`77`), usar el detector full con
fallback al rec-only si falla.

### 4.6 El recognizer leía "7" en lugar de "77"

**Síntoma**: RapidOCR leía solo un dígito del par "77" del juego.

**Causa**: el recorte horizontal era muy ajustado e incluía solo el
primer 7. El segundo "7" caía afuera del ROI.

**Solución**: en el flujo offline (test contra captura), ampliar el
recorte horizontal. En el flujo real (marker del usuario), el usuario
mismo redimensiona el marker para que cubra ambos dígitos.

### 4.7 El preprocesado Otsu destruía números con poco contraste

**Síntoma**: el "02" verde sobre fondo dorado del medidor de viento no
se leía con Otsu (binarizaba mal).

**Solución**: implementar **multi-strategy preprocessing**. `read_digits`
prueba 5+ estrategias (Otsu, Otsu invertido, adaptive threshold,
brightness threshold, máscaras de color amarillo/verde) y un sistema de
**voto por consenso** elige el valor con mayor suma de scores. Resistente
a fondos complejos y falsos positivos.

### 4.8 La ventana exterior tapaba clicks al juego

**Síntoma esperado**: si la ventana del marker mide 112×112 invisible y
el rect interno 30×30, los otros ~12000 px alrededor interceptan clicks
y no llegan al juego.

**Estado actual**: NO solucionado todavía. La ventana NO es click-through.
Aceptable por ahora — los markers se colocan sobre el HUD del juego, no
sobre zonas clickeables.

**Solución futura**: `setIgnoreCursorEvents(true)` por defecto, con un
mecanismo para detectar hover sobre el rect interno (probable: timer +
GetCursorPos en Rust, dado que cuando es click-through el frontend no
recibe hover events).

---

## 5. Aprendizajes técnicos importantes

### 5.1 SvelteKit + Tauri 2 router

SvelteKit por defecto hace SSR. En Tauri necesitamos SPA mode:
- `src/routes/+layout.ts`: `export const ssr = false; export const prerender = false;`
- `svelte.config.js`: adapter `@sveltejs/adapter-static` con
  `fallback: "index.html"`.
- Sin esto, las ventanas con URLs como `/marker?name=wind` no resuelven.

### 5.2 Capabilities en Tauri 2

Tauri 2 cambió el sistema de permisos vs v1. Ahora hay
`capabilities/default.json` con `permissions: ["core:default", ...]`. Si
una window-level command falla con "permission denied", probablemente
falta un permiso ahí (ej. `core:window:allow-start-resize-dragging`).

### 5.3 `cargo` y el linker MSVC

En Windows, Rust con toolchain MSVC (default y recomendado para Tauri)
necesita **Visual Studio Build Tools** con el workload "Desktop
development with C++". Sin eso, `cargo build` falla con `linker link.exe
not found`. Aunque `link.exe` no esté en el PATH, Rust lo encuentra
automáticamente vía vswhere.

VS 2026 Build Tools se instala en `C:\Program Files (x86)\Microsoft
Visual Studio\18\BuildTools\` (la carpeta `18` es la numeración interna,
no el año).

### 5.4 Tauri 2 + tauri-build embedded config

Si modificás `tauri.conf.json`, Cargo debería detectarlo y recompilar
`ai-dragonbound`. Pero a veces NO lo detecta — entonces hay que borrar
manualmente `src-tauri/target/debug/ai-dragonbound.exe` y la carpeta
`target/debug/build/ai-dragonbound-*/` para forzar rebuild.

### 5.5 Plugin-log de Tauri 2

`tauri-plugin-log` v2 escribe a un archivo unificado en:
- Windows: `%LOCALAPPDATA%\<identifier>\logs\<binary>.log`
- Linux: `~/.config/<identifier>/logs/<binary>.log`

Acepta logs de `log::*!` (Rust) y del crate JS `@tauri-apps/plugin-log`
(frontend). Para que el frontend log con metadata útil (qué ventana,
qué función), creé un helper `src/lib/log.ts` que envuelve y agrega un
`target` automático por ventana (panel, marker_wind, marker_angle).

### 5.6 Tauri abre cargo desde src-tauri/

Cuando `tauri dev` lanza `cargo run`, el `current_dir` del binario es
`src-tauri/`, NO la raíz del proyecto. Eso afecta cualquier código que
busque archivos por path relativo (como `vision/` y `.venv/`).

Solución: implementamos `project_root()` en `src-tauri/src/sidecar.rs`
que sube niveles hasta encontrar `vision/__init__.py` (señal de raíz).

### 5.7 PowerShell y output de cargo

`cargo` escribe sus mensajes de progreso a **stderr** (no stdout). En
PowerShell, esto se mezcla con errores reales y aparece con prefijo
`En línea: X Carácter: Y` (parece error pero no lo es). Ignorar esos —
solo importan las líneas que dicen `error[E...]` o `panicked`.

### 5.8 Default cargo no incluye Cargo.lock en repos

Por convención, **apps** sí commitean Cargo.lock (reproducibilidad).
**libs** no lo hacen. Como nosotros somos app, está en el repo.

---

## 6. Workflows comunes

### 6.1 Setup desde cero (nueva máquina)

```powershell
# Pre-requisitos: Rust toolchain (rustup-init), VS Build Tools con C++, Node 20+, Python 3.13
# Verificar:
rustc --version ; cargo --version ; node --version ; python --version

git clone https://github.com/COMANDO225/almeyda-wind-chart.git
cd almeyda-wind-chart
npm install
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r vision\requirements.txt

# Cargo no está en PATH de sesiones nuevas:
$env:PATH = "$env:USERPROFILE\.cargo\bin;$env:PATH"

npm run tauri dev
```

### 6.2 Modificar el panel (frontend Svelte)

- Vite HMR detecta cambios y recarga automáticamente.
- Los cambios al CSS son instantáneos.
- Cambios a la lógica del componente: el frontend recarga, pero el estado
  Svelte (`$state`) se resetea. Persistir lo importante en backend.

### 6.3 Modificar el backend Rust

- El watcher de `tauri dev` detecta cambios a archivos `.rs` y recompila.
- Recompilación incremental ~3-10 segundos.
- Si el binario no se relanza automáticamente, `Stop-Process -Name ai-dragonbound`.

### 6.4 Modificar el sidecar Python

- Como es un subprocess, NO hay HMR. Hay que matar la app y relanzar.
- Para testear cambios al detector sin Tauri: usar `vision/scripts/test_capture_02.py`.

### 6.5 Debug: ver qué lee el OCR

```powershell
$env:VISION_DEBUG_DIR = "$PWD\assets\samples\_debug"
$env:PYTHONIOENCODING = 'utf-8'
.\.venv\Scripts\python.exe -m vision.scripts.test_capture_02
```

Esto guarda imágenes intermedias de cada strategy (`_ocr_angle_otsu.png`,
`_ocr_wind_green_mask.png`, etc.) en `assets/samples/_debug/`. Inspectar
visualmente para ver dónde falla el preprocesado.

### 6.6 Tail logs de la app en vivo

```powershell
Get-Content "$env:LOCALAPPDATA\com.aidragonbound.app\logs\ai-dragonbound.log" -Wait -Tail 30
```

Cada vez que el frontend o backend emite un log, aparece en vivo. Los
logs vienen formateados con `target=` que identifica el origen (`frontend.marker_wind`,
`ai_dragonbound_lib::loop_`, etc.).

---

## 7. Mecánica del juego (relevante para Fase 3+)

- **Fuerza de tiro**: rango 0.0 – 4.0 (100% = 4.0). La barra horizontal del
  juego tiene 3 marcas internas (~25%, 50%, 75%).
- **Peso de la bala**: difiere por mobile. Un mobile con bala de peso 2.0
  puede llegar más lejos que otro con 2.5 porque también cambian otras
  constantes (gravedad relativa, sensibilidad al viento).
- **Ángulo**: 0–90° en la cajilla `LAST XX YY` del HUD inferior-izq. El YY
  amarillo grande es el ángulo actual, XX el anterior.
- **Viento**: magnitud 0–99 + dirección 0–360° (aguja del círculo superior).
- **MVP arranca con Armor** (tanque rojo, el mobile más simple).

Componentes del HUD que **ignoramos**:
- Timer del turno (número rojo grande arriba-derecha + cartel azul sobre
  mobile activo). Ambos son el mismo timer.
- Mensajes de bonus/penalización (aparecen y desaparecen).
- Lista de turnos, oro, experiencia.
- Efectos especiales (tornado, drone, thunder) — las ROIs pequeñas los evitan.

---

## 8. Roadmap por fases

- **Fase 0** ✅ — Pipeline de visión Python validado sobre capturas estáticas.
- **Fase 1** 🚧 95% completo — Tauri + 3 ventanas + compás + markers
  redimensionables + loop a 4 FPS + sidecar Python conectado + OCR
  validado offline. **Falta**: validar end-to-end y resolver problemas de
  precisión con cursiva / cambios de tema (ver 8.bis).
- **Fase 8.bis (refactor de precisión)** 👇 — ver detalle abajo.
- **Fase 2** — Empaquetar el sidecar Python con PyInstaller como
  `external binary` de Tauri, para que el instalador final sea un único
  `.msi/.exe` sin requerir venv del usuario.
- **Fase 3** — Esquineros TL+BR del área de juego + overlay click-through
  + render de la parábola del Armor con física calibrada empíricamente
  (gravedad, peso 0.0–4.0, factor de viento).
- **Fase 4** — Catálogo de mobiles con física especial (Trico [3 proyectiles
  girando], Turtle [2 disparos de agua en sinusoide], Bigfoot [perdigones
  secuenciales], etc.) + detección automática del mobile activo (template
  matching).
- **Fase 5** — Polish: hotkeys globales (F8 = pausa, F9 = recalibrar),
  wizard de calibración primera-vez, instalador `.msi` firmado, click-through
  inteligente sobre los markers.

---

## 8.bis. Refactor de precisión (decidido al cierre del MVP)

Tras probar en juego real, identificamos limitaciones:
- Confusión en lectura de **ángulo** (cursiva del juego confunde RapidOCR).
- Falsa orientación del **puntero del viento** cuando la aguja no es roja saturada.
- **Dependencia frágil** de masks yellow/green: con temas del juego
  (Halloween, Navidad, etc.) los colores cambian y se rompe.

Decisión acordada con el usuario:

### Sprint A — Refactor UI y separación de responsabilidades (~1 día)

1. **marker_wind circular** (`border-radius: 50%`). En Rust `capture.rs`,
   aplicar máscara circular al PNG antes de mandarlo al detector para que
   la zona fuera del círculo quede negra y no aporte ruido.
2. **Sub-marker NÚMERO** dentro del círculo del viento — cuadrado pequeño
   que solo lee el dígito central, no se mezcla con el puntero.
3. **Detector PUNTERO independiente** — opera sobre el círculo completo
   con **geometría pura** (sin colores): asimetría radial / Hough lines /
   momento de bordes. Inmune a cambios de tema.
4. **Filtrar el "°"** en el detector de ángulo por ratio de bounding box
   (width/height < 0.5 = no es dígito).

### Sprint B — OCR robusto sin colores (~1-2 días, si A no alcanza)

1. Eliminar `_strategy_yellow` y `_strategy_green` de `_ocr.py`. Reemplazar
   por edges adaptativos (Canny) + contour-based segmentation +
   binarización local (no Otsu global).
2. **Segmentación dígito por dígito** antes de OCR: separar `77` en dos
   imágenes individuales, leer cada una.
3. **Deskewing** por carácter (shear inverso) para corregir la cursiva.

### Sprint C — CNN custom que reemplaza RapidOCR (~3-5 días)

Decisión del usuario: **reemplazo total**, no fallback. Razones:
- RapidOCR pesa ~200 MB. Una CNN para 10 clases (0-9) pesa ~5 MB.
- RapidOCR es ~50-200 ms por inferencia. CNN ~1 ms.
- RapidOCR está entrenado para texto general; nuestro problema son
  10 clases con augmentation razonable.

**Dataset**: usuario va a recolectar **30-50 capturas variadas** en
distintos temas, lo que da ~150-400 dígitos reales etiquetados. Con
augmentation (rotación ±5°, scale ±10%, brightness, **shear para
cursiva**, noise) son ~1500-4000 muestras efectivas — suficiente para
~98% accuracy.

Pasos:
1. **`Sprint C.1`** — Hotkey global F1 (`tauri-plugin-global-shortcut`)
   que captura el contenido visible de cada marker y lo guarda en
   `assets/dataset/raw/{ts}_{detector}.png`. Permite recolectar mientras
   jugás.
2. **`Sprint C.2`** — Tool de etiquetado (`vision/scripts/label_digits.py`):
   abre cada captura, segmenta por contornos, muestra cada dígito y espera
   tecla `0-9` para etiquetar (o ESC para descartar). Guarda en
   `assets/dataset/labeled/{label}/{hash}.png`.
3. **`Sprint C.3`** — Entrenamiento (`vision/training/train.py`):
   - Arquitectura: 3 capas conv (16, 32, 64 filters) + 2 FC + softmax(10).
     ~50k params.
   - Augmentation con `albumentations`.
   - Split 80/10/10 train/val/test.
   - Optimizer Adam, ~30 epochs, target 98%+ test accuracy.
   - Export a `vision/models/digit_classifier.onnx` con `torch.onnx.export`.
4. **`Sprint C.4`** — Drop-in en `_ocr.py`:
   - Reemplazar `_ocr_text_with_score` por inferencia ONNX Runtime sobre la
     CNN.
   - Misma firma de `read_digits()` para que `detectors/{wind,angle}.py`
     no cambien.
   - Quitar `rapidocr` y `paddlepaddle` de `requirements.txt`.

### Criterios de éxito del refactor

- En vivo (no offline), apuntar marker sobre el HUD del juego en
  cualquier tema y leer correctamente ángulo y viento >= 95% de los
  turnos.
- Inferencia total (captura + CNN + emit) < 50 ms por frame (vs ~200 ms
  hoy con RapidOCR).
- Bundle final ~150 MB menos (sin paddle / rapidocr).

---

## 9. Notas para el usuario al continuar

### 9.1 Si retomás en otra máquina

1. Clonar el repo.
2. Seguir 6.1 (setup desde cero).
3. **Leer este CONTEXT.md primero** y CLAUDE.md después.
4. La primera ejecución descarga ~15 MB de modelos ONNX automáticamente.
5. Si el sidecar Python no arranca, verificar `.venv\Scripts\python.exe` y
   `python -m vision.main detect --help` directamente.

### 9.2 Antes de tocar código

- Si vas a tocar el frontend Svelte y la app está corriendo,
  **simplemente guardá** — Vite hace HMR. No relanzar.
- Si vas a tocar Rust, el watcher recompila pero a veces hay que matar
  el binario para forzar relaunch.
- Si vas a tocar Python (sidecar), matar la app entera y reiniciar.

### 9.3 Decisiones que NO están cerradas

Estas son las que el usuario y Claude pueden revisitar:
- **Estética del panel**: el compás está bien pero hay observaciones
  estéticas pendientes que mencionó el usuario.
- **Click-through real**: si los markers tapando el juego molesta,
  implementar `setIgnoreCursorEvents` con detección de hover por timer.
- **Más mobiles**: depende de Fase 4 — calibración empírica por mobile.

---

## 10. Apéndice: archivos clave (orden de importancia)

1. **`src-tauri/src/lib.rs`** — bootstrap de la app, plugin-log, plugin-store,
   on_window_event para cerrar todo.
2. **`src-tauri/src/loop_.rs`** — el loop de 4 FPS, conecta marker rects
   con capture + sidecar.
3. **`src-tauri/src/sidecar.rs`** — IPC con Python, busca venv del proyecto.
4. **`src/lib/MarkerFrame.svelte`** — la lógica más compleja del frontend:
   drag/resize con `e.movementX/Y` acumulado y `setSize/setPosition`.
5. **`vision/detectors/_ocr.py`** — el corazón del OCR: singleton +
   multi-strategy + voto por consenso + auto-crop por color.
6. **`vision/main.py`** — CLI `detect` y `serve`. El `serve` es el que usa
   Tauri.
7. **`src-tauri/tauri.conf.json`** — definición de las 3 ventanas con sus
   props (transparent, decorations false, alwaysOnTop, resizable, etc.).
8. **`src-tauri/capabilities/default.json`** — permisos Tauri 2.

---

## 11. Glosario

- **Marker**: ventana flotante transparente con un rect interno visible
  que el usuario coloca sobre un elemento del HUD para que el OCR lo lea.
- **ROI** (Region Of Interest): el rectángulo en pixels que el OCR procesa.
- **rect local**: posición/tamaño del rect interno dentro de su ventana,
  en pixels lógicos del DOM.
- **rect absoluto**: el mismo rect pero en coordenadas físicas de pantalla
  (usado por `xcap` para capturar).
- **Sidecar**: el proceso Python invisible que corre en background y
  procesa frames vía stdio JSON.
- **HUD** (Heads-Up Display): los elementos de UI del juego que muestran
  info (viento, ángulo, mobiles, etc.).
- **rec-only** mode de RapidOCR: pasar la imagen directo al recognizer
  sin pasar por el detector de cajas (más rápido, mejor para texto cartoon).
- **Strategy** en `_ocr.py`: una técnica específica de preprocesado de
  imagen (Otsu, brightness, color mask, etc.) que se prueba en `read_digits`.
- **Vote por consenso**: agrupar las lecturas de OCR por valor numérico,
  sumar los scores, elegir el grupo con mayor suma. Filtra falsos positivos
  de strategies puntuales.
