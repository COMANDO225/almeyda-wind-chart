<script lang="ts">
  // Overlay de la BARRA DE FUERZA. Se coloca encima de la barra de poder del
  // juego (0.0–4.0). Forma "caja sin techo": bordes inferior + laterales, sin
  // techo ni fondo. Una linea vertical indica la fuerza RECOMENDADA que el
  // sistema computa (centro por defecto, 0.5 de la barra).
  //
  // Igual que los markers, la VENTANA sigue al rect (drag mueve la ventana,
  // resize la agranda/encoge). Cuando el panel lo BLOQUEA, Rust activa el
  // click-through: el mouse pasa al juego y los handles dejan de recibir hover
  // (por eso solo aparecen al pasar el cursor — invisibles cuando esta
  // bloqueado y se puede jugar la barra real debajo).

  import { onMount } from "svelte";
  import { LogicalSize, PhysicalPosition } from "@tauri-apps/api/dpi";
  import { getCurrentWindow } from "@tauri-apps/api/window";
  import { getMarkerRect, setMarkerRect, onForce } from "$lib/ipc";
  import { log } from "$lib/log";

  const win = getCurrentWindow();
  const PADDING = 10;
  const MIN = 20;

  let size = $state({ w: 240, h: 60 });
  /** Fraccion 0..1 de la barra donde va la linea (fuerza/4). Centro por defecto. */
  let forceFrac = $state(0.5);

  type Mode = "n" | "s" | "e" | "w" | "nw" | "ne" | "sw" | "se";
  let drag: {
    mode: Mode;
    startW: number;
    startH: number;
    startWinX: number;
    startWinY: number;
    scale: number;
    accumDx: number;
    accumDy: number;
  } | null = null;

  onMount(() => {
    let unForce: (() => void) | undefined;
    (async () => {
      await syncWindowSize();
      try {
        const persisted = await getMarkerRect("power_bar");
        if (persisted) {
          size = { w: Math.max(MIN, persisted.w), h: Math.max(MIN, persisted.h) };
          await syncWindowSize();
        }
        await pushLocal();
      } catch (e) {
        log.error("power_bar restore fallo", { err: String(e) });
      }
      unForce = await onForce((f) => {
        forceFrac = f.value === null ? 0.5 : Math.min(1, Math.max(0, f.value / 4));
      });
    })();
    return () => unForce?.();
  });

  async function syncWindowSize() {
    await win.setSize(new LogicalSize(size.w + PADDING * 2, size.h + PADDING * 2));
  }

  async function onResizeStart(e: PointerEvent, mode: Mode) {
    e.preventDefault();
    e.stopPropagation();
    try {
      (e.target as Element).setPointerCapture(e.pointerId);
    } catch {}
    const pos = await win.outerPosition();
    const scale = await win.scaleFactor();
    drag = {
      mode,
      startW: size.w,
      startH: size.h,
      startWinX: pos.x,
      startWinY: pos.y,
      scale,
      accumDx: 0,
      accumDy: 0,
    };
  }

  async function onMoveDoc(e: PointerEvent) {
    if (!drag) return;
    drag.accumDx += e.movementX;
    drag.accumDy += e.movementY;
    const dx = drag.accumDx;
    const dy = drag.accumDy;

    let w = drag.startW;
    let h = drag.startH;
    let shiftX = 0;
    let shiftY = 0;

    if (drag.mode.includes("e")) w = drag.startW + dx;
    if (drag.mode.includes("w")) {
      w = drag.startW - dx;
      shiftX = dx;
    }
    if (drag.mode.includes("s")) h = drag.startH + dy;
    if (drag.mode.includes("n")) {
      h = drag.startH - dy;
      shiftY = dy;
    }

    if (w < MIN) {
      if (drag.mode.includes("w")) shiftX -= MIN - w;
      w = MIN;
    }
    if (h < MIN) {
      if (drag.mode.includes("n")) shiftY -= MIN - h;
      h = MIN;
    }
    size = { w, h };
    await syncWindowSize();
    if (shiftX || shiftY) {
      await win.setPosition(
        new PhysicalPosition(
          drag.startWinX + Math.round(shiftX * drag.scale),
          drag.startWinY + Math.round(shiftY * drag.scale),
        ),
      );
    }
  }

  async function onEnd(e: PointerEvent) {
    if (!drag) return;
    try {
      (e.target as Element).releasePointerCapture(e.pointerId);
    } catch {}
    drag = null;
    await pushLocal();
  }

  async function pushLocal() {
    try {
      await setMarkerRect("power_bar", {
        x: PADDING,
        y: PADDING,
        w: Math.round(size.w),
        h: Math.round(size.h),
      });
    } catch (e) {
      log.error("power_bar push rect fallo", { err: String(e) });
    }
  }
</script>

<svelte:window onpointermove={onMoveDoc} onpointerup={onEnd} onpointercancel={onEnd} />

<div
  class="box"
  style:--padding="{PADDING}px"
  style:--w="{size.w}px"
  style:--h="{size.h}px"
  style:--frac={forceFrac}
>
  <div class="body" data-tauri-drag-region role="presentation"></div>

  <!-- "Techo" abierto: cuadraditos en la punta de cada borde lateral. -->
  <div class="cap left"></div>
  <div class="cap right"></div>

  <!-- Linea vertical = fuerza recomendada. -->
  <div class="force-line"></div>

  <button class="edge w" onpointerdown={(e) => onResizeStart(e, "w")} aria-label="west"></button>
  <button class="edge e" onpointerdown={(e) => onResizeStart(e, "e")} aria-label="east"></button>
  <button class="edge n" onpointerdown={(e) => onResizeStart(e, "n")} aria-label="north"></button>
  <button class="edge s" onpointerdown={(e) => onResizeStart(e, "s")} aria-label="south"></button>
  <button class="corner nw" onpointerdown={(e) => onResizeStart(e, "nw")} aria-label="nw"></button>
  <button class="corner ne" onpointerdown={(e) => onResizeStart(e, "ne")} aria-label="ne"></button>
  <button class="corner sw" onpointerdown={(e) => onResizeStart(e, "sw")} aria-label="sw"></button>
  <button class="corner se" onpointerdown={(e) => onResizeStart(e, "se")} aria-label="se"></button>
</div>

<style>
  :global(html), :global(body) {
    margin: 0;
    padding: 0;
    background: transparent;
    overflow: hidden;
  }

  /* "Caja sin techo": bordes inferior + laterales, sin techo, sin fondo. */
  .box {
    position: fixed;
    left: var(--padding);
    top: var(--padding);
    width: var(--w);
    height: var(--h);
    border: 2px solid rgba(255, 210, 80, 0.95);
    border-top: none;
    background: transparent;
    box-sizing: border-box;
  }

  .body {
    position: absolute;
    inset: 0;
    cursor: move;
  }

  /* Cuadraditos en la punta superior de cada borde lateral. */
  .cap {
    position: absolute;
    top: -2px;
    width: 7px;
    height: 7px;
    background: rgba(255, 210, 80, 0.95);
    pointer-events: none;
  }
  .cap.left {
    left: -2px;
  }
  .cap.right {
    right: -2px;
  }

  /* Linea vertical de fuerza recomendada. */
  .force-line {
    position: absolute;
    top: 0;
    bottom: 0;
    left: calc(var(--frac) * 100%);
    width: 2px;
    transform: translateX(-1px);
    background: rgba(120, 230, 255, 0.95);
    box-shadow: 0 0 6px rgba(120, 230, 255, 0.7);
    transition: left 120ms ease-out;
    pointer-events: none;
  }

  /* Handles: invisibles salvo al pasar el cursor. Cuando el overlay esta
     bloqueado (click-through), el hover no dispara y quedan ocultos. */
  .edge,
  .corner {
    position: absolute;
    background: transparent;
    border: 0;
    padding: 0;
    margin: 0;
    z-index: 2;
  }
  .corner {
    width: 10px;
    height: 10px;
    background: rgba(255, 210, 80, 0.95);
    border: 1px solid rgba(0, 0, 0, 0.8);
    opacity: 0;
    transition: opacity 120ms;
  }
  .box:hover .corner {
    opacity: 1;
  }
  .edge.n { top: -6px;    left: 6px;   right: 6px;  height: 9px; cursor: ns-resize; }
  .edge.s { bottom: -6px; left: 6px;   right: 6px;  height: 9px; cursor: ns-resize; }
  .edge.w { top: 6px;     bottom: 6px; left: -6px;  width: 9px;  cursor: ew-resize; }
  .edge.e { top: 6px;     bottom: 6px; right: -6px; width: 9px;  cursor: ew-resize; }
  .nw { top: -3px;    left: -3px;    cursor: nwse-resize; }
  .se { bottom: -3px; right: -3px;   cursor: nwse-resize; }
  .ne { top: -3px;    right: -3px;   cursor: nesw-resize; }
  .sw { bottom: -3px; left: -3px;    cursor: nesw-resize; }

  button:focus { outline: none; }
</style>
