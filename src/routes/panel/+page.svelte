<script lang="ts">
  import { onMount } from "svelte";
  import { getCurrentWindow } from "@tauri-apps/api/window";
  import WindCompass from "$lib/WindCompass.svelte";
  import MobileSelector from "$lib/MobileSelector.svelte";
  import {
    onWind,
    onAngle,
    setMarkerRect,
    type WindReading,
    type AngleReading,
  } from "$lib/ipc";

  let wind = $state<WindReading | null>(null);
  let angle = $state<AngleReading | null>(null);
  let mobile = $state("armor");

  const angleText = $derived(angle?.value ?? "--");

  onMount(() => {
    let unWind: (() => void) | undefined;
    let unAngle: (() => void) | undefined;
    (async () => {
      unWind = await onWind((w) => (wind = w));
      unAngle = await onAngle((a) => (angle = a));

      // Sincronizar el rect actual de cada marker al state del backend (en
      // caso de que sea la primera ejecución sin posiciones persistidas).
      try {
        await pushMarkerRect("wind");
        await pushMarkerRect("angle");
      } catch (e) {
        console.warn("push initial marker rects falló", e);
      }
    })();
    return () => {
      unWind?.();
      unAngle?.();
    };
  });

  async function pushMarkerRect(name: "wind" | "angle") {
    // El frontend no tiene acceso directo a la ventana hermana; en una
    // próxima iteración el backend Rust monitoreará los movimientos. Por
    // ahora dejamos esta función como hook para futuras llamadas.
    void name;
  }

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
    <WindCompass value={wind?.value ?? null} directionDeg={wind?.direction_deg ?? null} />
  </section>

  <section class="info">
    <div class="row">
      <span class="lbl">Ángulo</span>
      <span class="val">{angleText}°</span>
    </div>
  </section>

  <section class="controls">
    <MobileSelector bind:value={mobile} />
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
  }
  footer {
    margin-top: auto;
    font-size: 10px;
    color: #888;
    text-align: center;
    letter-spacing: 0.05em;
  }
</style>
