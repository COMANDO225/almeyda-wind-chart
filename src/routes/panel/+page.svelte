<script lang="ts">
  import { onMount } from "svelte";
  import { getCurrentWindow } from "@tauri-apps/api/window";
  import WindCompass from "$lib/WindCompass.svelte";
  import MobileSelector from "$lib/MobileSelector.svelte";
  import {
    onWind,
    onAngle,
    getExcludeFromCapture,
    setExcludeFromCapture,
    type WindReading,
    type AngleReading,
  } from "$lib/ipc";

  // marker_wind emite un WindReading con AMBOS campos (value + direction_deg)
  // porque el sidecar corre los 2 flujos internos sobre el mismo frame.
  let windValue = $state<number | null>(null);
  let windDirection = $state<number | null>(null);
  let angle = $state<AngleReading | null>(null);
  let mobile = $state("armor");
  // Si los markers se ocultan de capturas externas (default true).
  // Lo lee del backend en onMount; el usuario puede toggle desde el switch.
  let excludeFromCapture = $state(true);

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
    (async () => {
      excludeFromCapture = await getExcludeFromCapture();
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
  </section>

  <section class="controls">
    <MobileSelector bind:value={mobile} />
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
    height: 100vh;
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
</style>
