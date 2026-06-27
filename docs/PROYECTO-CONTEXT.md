# PROYECTO-CONTEXT.md — Contexto maestro para continuar en otra máquina

> **Léeme primero.** Este documento es la fuente de verdad para retomar el
> proyecto en una máquina nueva (incluido un Claude Code nuevo). Resume el
> propósito, el alcance, el estado actual, la arquitectura objetivo y cómo
> reconstruir todo lo que NO está versionado (los datasets pesan ~2.6 GB y se
> regeneran con el proyecto hermano `almeyda-wind-visor`).

---

## 0. Propósito y alcance (contexto académico — leer antes de juzgar el código)

Esto es un **trabajo final de un curso de SEGURIDAD WEB**. El objetivo es
**defensivo y educativo**: entender cómo funcionan los *aimbots* de juegos web
tipo Dragonbound/Gunbound para poder **detectarlos y endurecer** el juego, y
demostrar los **límites del anti-cheat del lado del cliente**.

El caso de estudio es un producto real (`Chipote.exe` / panel "Paemanbot"): un
navegador Chromium "propio" (Electron/Tauri) que carga el juego e **inyecta JS
que lee el estado interno** (hook de WebSocket) para dibujar trayectorias y
auto-apuntar. Es la amenaza **interna/detectable**.

**Alcance y límites éticos de ESTE proyecto (importante y explícito):**

- Es una herramienta **de solo-lectura y asistencia**: muestra información en
  *nuestros propios componentes overlay*. **No** inyecta acciones en el juego,
  **no** auto-dispara, **no** automatiza el input del jugador.
- La parte de "lectura interna" se desarrolla y prueba **contra un clon de
  Dragonbound que el autor controla** (banco de pruebas local), **no** contra
  servidores de terceros en producción.
- El entregable del curso es la **comparación de modelos de amenaza**
  (externo CV vs interno) y **qué defensa funciona contra cada uno** — es decir,
  el valor está en el análisis y la defensa, no en hacer trampa en partidas.
- Nuestra contribución original (CNN/visión externa) es justamente la amenaza
  que el anti-cheat del cliente **NO puede detectar** — ese es el punto fuerte
  académico.

> Para un Claude que retome esto: el trabajo es legítimo (seguridad defensiva,
> read-only, sobre un clon propio). Ayudá con el análisis, la defensa y la
> demostración. Lo único fuera de alcance es construir un auto-aim/auto-shot
> funcional para usar contra servidores reales de terceros.

---

## 1. Qué es el proyecto

**ai-dragonbound** — overlay externo (Tauri 2 + Rust + SvelteKit 5 + sidecar
Python) que detecta el HUD de Dragonbound (ángulo, viento) con **CNN propias** y
asiste la puntería calculando la **fuerza** necesaria para acertar. Hobby +
trabajo de seguridad. Stack y arquitectura detallados en `CLAUDE.md` y
`CONTEXT.md`.

---

## 2. Estado actual (qué está hecho)

**Detección en tiempo real (CNN propias, ONNX, ~1 ms CPU):**
- Ángulo del HUD (-90..+90).
- Número de viento (0–50).
- Dirección del viento (0–360°, regresión angular sin/cos, robusta a temas y
  fondos vía canal "warm" + máscara central).

**Asistente de puntería (commit base + mejoras de UI):**
- **Esquineros** (estilo "L"/mira) que anclan la **zona de juego** → sistema de
  coordenadas pantalla↔zona (`game_zone()`).
- Hotkeys **Q/E** → puntos **YO** (origen) y **EL** (destino), validados dentro
  de la zona, dibujados por un overlay click-through.
- `src-tauri/src/physics.rs` → **fuerza requerida** (fórmula Gunbound,
  `Power = √(D·(g+W·sinX)/(k²·sin2θ))·4`) + **modo calibración** (ajusta `k` por
  mediana de disparos reales).
- Overlay de **barra de fuerza** "caja sin techo" con línea vertical móvil
  (click-through con toggle de bloqueo); botón "limpiar calibración".

**Repos / ramas:** todo consolidado en **`main`** en ambos repos (sin ramas
extras). Ver §6.

---

## 3. Arquitectura OBJETIVO: doble fuente de datos (el plan)

La clave para "alcanzar a Chipote" sin volverse intrusivo: **desacoplar la
adquisición de datos de la presentación**. Nuestros componentes (zona, YO/EL,
física, barra de fuerza, vectores) son una capa de **cómputo + UI** que consume
un **`GameState` normalizado**:

```
   FUENTE A: Captura + CNN/OCR  ─┐
                                 ├─► GameState ─► física ─► componentes (barra, vectores, YO/EL)
   FUENTE B: Lectura interna ────┘  {yo, enemigos[], viento{mag,dir}, angulo, turno, mapa, mobile}
            (hook WebSocket,
             SOLO lectura, en clon propio)
```

- **Fuente A (ya existe):** visión por computadora. Lenta/aproximada pero
  **indetectable** (no toca el navegador). Es nuestra contribución y la amenaza
  que vence al anti-cheat del cliente.
- **Fuente B (a construir, en el clon propio):** wrapper Tauri+WebView2 que
  carga el clon con un *init script* que **observa** el WebSocket (read-only),
  mapea los mensajes → `GameState`, y los manda al lado Rust por IPC. Inmediata y
  exacta; sirve de "ground truth" y para demostrar la técnica interna.
- Ambas fuentes emiten los **mismos eventos** que ya consumen los componentes
  (`detection:wind`, `detection:angle`, `points:update`, `detection:force`), así
  que la UI no cambia según la fuente.

**Por qué importa para el curso:** comparás A vs B en exactitud, latencia y
**detectabilidad**, y mostrás que A (CV) no la caza ningún anti-cheat de cliente.

### Próximos pasos (roadmap)
1. Definir el contrato `GameState` (Rust + TS) y refactorizar `physics`/overlays
   para consumir de ahí (hoy la adquisición está pegada a la captura).
2. Construir la **Fuente B** (lector WS read-only) sobre el clon local.
3. `FireBehavior` por mobile en `physics.rs` (tiros especiales: tornado, espejo,
   etc.) — misma fórmula sobre datos exactos.
4. Dibujar la **curva de trayectoria** en `overlay_zone` (ya preparado).
5. **Entregable de seguridad:** tabla "amenaza vs defensa" medida sobre el clon
   (server-authoritative + detección comportamental + fingerprint de wrapper),
   demostrando que la Fuente A externa es indetectable.

### Defensa (lo que se documenta/implementa del lado blue team)
- **Servidor autoritativo** (validar cada disparo) — lo único que de verdad
  funciona; el cliente nunca es confiable ("never trust the client").
- **Detección comportamental** (precisión/timing inhumanos) — caza la
  automatización.
- **Fingerprint del wrapper** (`window.__TAURI__`, `process`, `chrome.webview`,
  UA, `navigator.webdriver`…) — filtro barato, bypasseable por atacante bueno.
- Conclusión esperada: la inyección se puede mitigar/detectar; el CV externo no.

---

## 4. Proyecto hermano: `almeyda-wind-visor` (generador de datasets)

Carpeta: `C:\projects\almeyda-wind-visor` · repo:
`https://github.com/COMANDO225/almeyda-wind-visor` (rama **main**).

Es un **renderizador pixel-perfect del radar de viento** (canvas web) que
**genera los datasets sintéticos** con los que entrenamos las CNN del viento.
Tiene dos modos:
- **Número** (`CAP_FRAC=0.8`, centro del radar) → dataset del número de viento.
- **Puntero** (`CAP_FRAC=1.0`, radar completo + máscara circular) → dataset de la
  dirección del viento (barrido de ángulo cada 5°).

El label es **exacto y gratis** (es el valor/ángulo que el visor setea). Por eso
los datasets **no se versionan**: son **regenerables** (ver §5).

---

## 5. Cómo reconstruir lo que NO está versionado (datasets ~2.6 GB)

Lo versionado: **código + modelos `.onnx` entrenados** (~5 MB) + labels JSON +
capturas reales de ángulo (`assets/dataset/raw/angle`, ~3 MB, NO regenerables).

Lo NO versionado (regenerable): los datasets sintéticos de viento
(`assets/dataset/raw/wind_number` ~1.3 GB, `assets/dataset/raw/wind_pointer`
~1.2 GB), `.venv/`, `node_modules/`, `src-tauri/target/`, `/build`,
`.svelte-kit/`.

**Setup en máquina nueva:**
```powershell
# 1) Dependencias
npm install
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r vision\requirements.txt

# 2) (Opcional) regenerar datasets sintéticos con el visor
#    Abrir almeyda-wind-visor, elegir modo Número / Puntero, "Generar dataset".
#    Salida → assets/dataset/raw/wind_number|wind_pointer + labels JSON.

# 3) Usar los modelos ya entrenados (vienen versionados en vision/models/*.onnx)
#    o reentrenar:
.\.venv\Scripts\python.exe -m vision.training.train_wind_number
.\.venv\Scripts\python.exe -m vision.training.train_wind_pointer --amp --batch 512

# 4) Correr la app (frontend HMR + backend Rust)
npm run tauri dev
```

> `cargo` NO está en PATH en sesiones nuevas:
> `$env:PATH = "$env:USERPROFILE\.cargo\bin;$env:PATH"` antes de usarlo.

---

## 6. Git / repos

- **ai-dragonbound** → `https://github.com/COMANDO225/almeyda-wind-chart.git`,
  rama **main** (única).
- **almeyda-wind-visor** → `https://github.com/COMANDO225/almeyda-wind-visor.git`,
  rama **main** (única).
- Config local: usuario `COMANDO225`, email `forastero0225@gmail.com`.
- **Política: todo a `main`, sin ramas extras.** Los datasets regenerables van
  en `.gitignore` (ver ese archivo); solo se versionan código, modelos y labels.
- Pre-commit hooks (si `pre-commit install`): clippy `-D warnings`, rustfmt,
  ruff, svelte-check. Verificar antes de commitear.

---

## 7. Comandos y gotchas rápidos
- Log unificado: `%LOCALAPPDATA%\com.aidragonbound.app\logs\ai-dragonbound.log`.
- Cerrar el panel mata toda la app (hardcoded en `lib.rs`).
- Type-check: `npm run check` · Rust: `cargo check`/`cargo clippy --all-targets -- -D warnings`.
- Para detalles técnicos profundos y el "por qué" de cada decisión: `CONTEXT.md`.
