<script lang="ts">
  import { onMount } from "svelte";
  import { getCurrentWindow } from "@tauri-apps/api/window";
  import WindCompass from "$lib/WindCompass.svelte";
  import MobileSelector from "$lib/MobileSelector.svelte";
  import {
    onWind,
    onAngle,
    onForce,
    onPoints,
    getPoints,
    clearPoints,
    getLock,
    setLock,
    getCalibration,
    addCalibrationSample,
    fitCalibration,
    clearCalibration,
    getExcludeFromCapture,
    setExcludeFromCapture,
    type WindReading,
    type AngleReading,
    type ForceReading,
    type Points,
    type CalibInfo,
  } from "$lib/ipc";

  // marker_wind emite un WindReading con AMBOS campos (value + direction_deg)
  // porque el sidecar corre los 2 flujos internos sobre el mismo frame.
  let windValue = $state<number | null>(null);
  let windDirection = $state<number | null>(null);
  let angle = $state<AngleReading | null>(null);
  let mobile = $state("armor");
  // Fuerza recomendada (0.0–4.0) que computa el backend. null = sin dato aun.
  let force = $state<ForceReading | null>(null);
  // Bloqueo del overlay de la barra de fuerza: true = click-through (jugable
  // debajo), false = se puede mover/redimensionar.
  let powerBarLocked = $state(false);
  // Puntos YO/EL marcados con Q/E.
  let points = $state<Points>({ yo: null, el: null });
  // Estado de calibración del Armor.
  let calib = $state<CalibInfo>({ samples: 0, k: 0, wind_factor: 1 });
  let calibForce = $state(2.0);
  let calibHit = $state(true);
  let calibMsg = $state("");
  // Si los markers se ocultan de capturas externas (default true).
  // Lo lee del backend en onMount; el usuario puede toggle desde el switch.
  let excludeFromCapture = $state(true);

  const forceText = $derived.by(() => {
    const v = force?.value;
    if (v === null || v === undefined) return "--";
    if (force && !force.reachable) return "∞";
    return v.toFixed(2);
  });

  async function togglePowerBarLock() {
    const next = !powerBarLocked;
    powerBarLocked = next; // UI optimista
    try {
      await setLock("power_bar", next);
    } catch (e) {
      powerBarLocked = !next;
      console.error("set_lock(power_bar) fallo:", e);
    }
  }

  const pointsText = $derived(
    `${points.yo ? "YO✓" : "YO·"}  ${points.el ? "EL✓" : "EL·"}`,
  );

  async function onClearPoints() {
    try {
      await clearPoints();
    } catch (e) {
      console.error("clear_points fallo:", e);
    }
  }

  async function onRegisterSample() {
    calibMsg = "";
    try {
      calib = await addCalibrationSample(calibForce, calibHit);
      calibMsg = `Muestra registrada (${calib.samples}).`;
    } catch (e) {
      calibMsg = String(e);
    }
  }

  async function onFit() {
    calibMsg = "";
    try {
      calib = await fitCalibration();
      calibMsg = `Ajustado: k=${calib.k.toFixed(2)}.`;
    } catch (e) {
      calibMsg = String(e);
    }
  }

  async function onClearCalibration() {
    if (!confirm("Borrar todas las muestras de calibracion del Armor y resetear k al valor base?")) {
      return;
    }
    calibMsg = "";
    try {
      calib = await clearCalibration();
      calibMsg = "Calibracion limpiada.";
    } catch (e) {
      calibMsg = String(e);
    }
  }

  // Ángulo a 2 cifras como el viento: magnitud con padStart(2,'0') preservando
  // el signo. 5→"05", 90→"90", -9→"-09", -26→"-26". "--" si no hay lectura.
  const angleText = $derived.by(() => {
    const v = angle?.value;
    if (v === null || v === undefined) return "--";
    const sign = v < 0 ? "-" : "";
    return sign + String(Math.abs(v)).padStart(2, "0");
  });

  async function toggleExcludeFromCapture() {
    const next = !excludeFromCapture;
    excludeFromCapture = next; // UI optimista
    try {
      await setExcludeFromCapture(next);
    } catch (e) {
      // si falla, revertimos
      excludeFromCapture = !next;
      console.error("set_exclude_from_capture fallo:", e);
    }
  }

  onMount(() => {
    let unWind: (() => void) | undefined;
    let unAngle: (() => void) | undefined;
    let unForce: (() => void) | undefined;
    let unPoints: (() => void) | undefined;
    (async () => {
      excludeFromCapture = await getExcludeFromCapture();
      powerBarLocked = await getLock("power_bar");
      points = await getPoints();
      calib = await getCalibration();
      unForce = await onForce((f) => (force = f));
      unPoints = await onPoints((p) => (points = p));
      unWind = await onWind((w) => {
        if (w.value !== null && w.value !== undefined) {
          windValue = w.value;
        }
        if (w.direction_deg !== null && w.direction_deg !== undefined) {
          windDirection = w.direction_deg;
        }
      });
      unAngle = await onAngle((a) => (angle = a));
    })();
    return () => {
      unWind?.();
      unAngle?.();
      unForce?.();
      unPoints?.();
    };
  });

  async function closeApp() {
    await getCurrentWindow().close();
  }
</script>

<main class="panel" data-tauri-drag-region>
  <header data-tauri-drag-region>
    <h1>ai-dragonbound</h1>
    <button class="close" onclick={closeApp} aria-label="cerrar">×</button>
  </header>

  <section class="compass-wrap">
    <WindCompass value={windValue} directionDeg={windDirection} />
  </section>

  <section class="info">
    <div class="row">
      <span class="lbl">Ángulo</span>
      <span class="val">{angleText}°</span>
    </div>
    <div class="row">
      <span class="lbl">Fuerza</span>
      <span class="val">{forceText}</span>
    </div>
  </section>

  <section class="controls">
    <MobileSelector bind:value={mobile} />
    <label class="toggle" title="Bloquea el overlay de la barra de fuerza: activa el click-through para poder arrastrar la barra real del juego debajo. Desbloquéalo para reposicionar el overlay.">
      <input
        type="checkbox"
        checked={powerBarLocked}
        onchange={togglePowerBarLock}
      />
      <span class="toggle-track"><span class="toggle-knob"></span></span>
      <span class="toggle-label">Barra de fuerza bloqueada (click-through)</span>
    </label>

    <div class="points">
      <span class="points-state">{pointsText}</span>
      <button class="mini" onclick={onClearPoints}>Limpiar YO/EL</button>
    </div>
    <p class="hint">Q = punto YO (origen) · E = punto EL (destino)</p>

    <details class="calib">
      <summary>Calibración Armor · {calib.samples} muestras · k={calib.k.toFixed(1)}</summary>
      <div class="calib-body">
        <label class="calib-row">
          <span>Fuerza usada</span>
          <input type="number" min="0" max="4" step="0.05" bind:value={calibForce} />
        </label>
        <label class="calib-row checkbox">
          <input type="checkbox" bind:checked={calibHit} />
          <span>¿Pegó?</span>
        </label>
        <div class="calib-actions">
          <button class="mini" onclick={onRegisterSample}>Registrar muestra</button>
          <button class="mini" onclick={onFit}>Ajustar k</button>
          <button class="mini danger" onclick={onClearCalibration} title="Borra todas las muestras y vuelve a k base">Limpiar</button>
        </div>
        {#if calibMsg}<p class="calib-msg">{calibMsg}</p>{/if}
      </div>
    </details>
    <label class="toggle" title="Cuando esta activo, los markers SON visibles en capturas externas (streams, screenshots). Por defecto se ocultan para no contaminar el frame del OCR.">
      <input
        type="checkbox"
        checked={!excludeFromCapture}
        onchange={toggleExcludeFromCapture}
      />
      <span class="toggle-track"><span class="toggle-knob"></span></span>
      <span class="toggle-label">Markers visibles en capturas</span>
    </label>
  </section>

  <footer data-tauri-drag-region>
    <span>Captura activa · 4 FPS</span>
  </footer>
</main>

<style>
  .panel {
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 14px;
    min-height: 100vh;
    box-sizing: border-box;
    background: rgba(15, 15, 22, 0.82);
    backdrop-filter: blur(12px);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 14px;
    color: #f0f0f0;
  }
  header {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  header h1 {
    margin: 0;
    font-size: 13px;
    font-weight: 500;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #c8c8d0;
    opacity: 0.7;
  }
  .close {
    background: transparent;
    color: #b0b0b8;
    border: none;
    font-size: 22px;
    line-height: 1;
    cursor: pointer;
    padding: 0 6px;
    border-radius: 4px;
  }
  .close:hover {
    background: rgba(255, 255, 255, 0.08);
    color: #fff;
  }
  .compass-wrap {
    display: flex;
    justify-content: center;
    margin: 4px 0;
  }
  .info {
    display: flex;
    justify-content: center;
    gap: 8px;
  }
  .row {
    display: flex;
    align-items: baseline;
    gap: 10px;
    background: rgba(255, 255, 255, 0.04);
    padding: 8px 14px;
    border-radius: 8px;
    border: 1px solid rgba(255, 255, 255, 0.08);
  }
  .lbl {
    color: #b8b8c0;
    font-size: 12px;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
  .val {
    color: #fff;
    font-size: 22px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    /* Ancho fijo para que el contenedor no salte entre "5", "-26", "90".
       Cubre el caso mas ancho ("-26°") + tabular-nums (dígitos isométricos). */
    display: inline-block;
    min-width: 3.2em;
    text-align: right;
  }
  footer {
    margin-top: auto;
    font-size: 10px;
    color: #888;
    text-align: center;
    letter-spacing: 0.05em;
  }
  .controls {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .toggle {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 11px;
    color: #c8c8d0;
    cursor: pointer;
    padding: 6px 10px;
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 6px;
    user-select: none;
  }
  .toggle input {
    /* checkbox nativo oculto — usamos el track/knob como UI */
    position: absolute;
    opacity: 0;
    pointer-events: none;
  }
  .toggle-track {
    position: relative;
    width: 30px;
    height: 16px;
    background: rgba(255, 255, 255, 0.1);
    border-radius: 999px;
    transition: background 150ms ease;
    flex-shrink: 0;
  }
  .toggle-knob {
    position: absolute;
    top: 2px;
    left: 2px;
    width: 12px;
    height: 12px;
    background: #e8e8ec;
    border-radius: 50%;
    transition: transform 150ms ease;
  }
  .toggle input:checked + .toggle-track {
    background: rgba(120, 200, 130, 0.65);
  }
  .toggle input:checked + .toggle-track .toggle-knob {
    transform: translateX(14px);
  }
  .toggle-label {
    flex: 1;
  }

  .points {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }
  .points-state {
    font-size: 12px;
    font-variant-numeric: tabular-nums;
    letter-spacing: 0.04em;
    color: #d8d8e0;
  }
  .hint {
    margin: -4px 0 0;
    font-size: 10px;
    color: #888;
    text-align: center;
  }
  .mini {
    background: rgba(255, 255, 255, 0.06);
    color: #e8e8ec;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 6px;
    font-size: 11px;
    padding: 5px 9px;
    cursor: pointer;
  }
  .mini:hover {
    background: rgba(255, 255, 255, 0.12);
  }
  .mini.danger {
    color: #ffb4a8;
    border-color: rgba(255, 80, 70, 0.35);
  }
  .mini.danger:hover {
    background: rgba(255, 80, 70, 0.15);
    border-color: rgba(255, 80, 70, 0.55);
  }
  .calib {
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 11px;
    color: #c8c8d0;
  }
  .calib summary {
    cursor: pointer;
    user-select: none;
  }
  .calib-body {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-top: 8px;
  }
  .calib-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }
  .calib-row.checkbox {
    justify-content: flex-start;
  }
  .calib-row input[type="number"] {
    width: 70px;
    background: rgba(0, 0, 0, 0.3);
    color: #fff;
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 4px;
    padding: 3px 6px;
    font-size: 12px;
  }
  .calib-actions {
    display: flex;
    gap: 8px;
  }
  .calib-msg {
    margin: 0;
    font-size: 10px;
    color: #9fd0a0;
  }
</style>
