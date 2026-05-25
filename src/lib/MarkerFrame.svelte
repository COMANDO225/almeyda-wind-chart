<script lang="ts">
  // Arquitectura: la VENTANA Tauri sigue al rect.
  //   - Drag del cuerpo del rect → data-tauri-drag-region mueve la ventana.
  //   - Resize de handles → recalculamos size y la ventana crece/encoge.
  //   - Para resize desde N/NW/NE/W/SW también reposicionamos la ventana
  //     usando la POSICIÓN INICIAL del drag + delta acumulado de movementX/Y.
  //
  // Por qué movementX/Y y no screenX/Y: cuando movemos la ventana durante
  // un drag, Windows reposiciona el cursor relativo al handle y screenY
  // salta. movementY (delta entre eventos consecutivos) es inmune a eso.

  import { onMount } from "svelte";
  import { LogicalSize, PhysicalPosition } from "@tauri-apps/api/dpi";
  import { getCurrentWindow } from "@tauri-apps/api/window";
  import { setMarkerRect, getMarkerRect } from "$lib/ipc";
  import { log } from "$lib/log";

  interface Props {
    name: "wind" | "angle";
    initialSize?: { w: number; h: number };
  }

  let {
    name,
    initialSize = name === "wind"
      ? { w: 80, h: 80 }
      : { w: 40, h: 36 },
  }: Props = $props();

  const win = getCurrentWindow();

  const PADDING = 10;
  const MIN = 6;

  let size = $state({ ...initialSize });

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
    (async () => {
      log.info("marker onMount", { name, initialSize, PADDING, MIN });
      await syncWindowSize();
      try {
        const persisted = await getMarkerRect(name);
        log.info("rect persisted leído", { persisted });
        if (persisted) {
          size = {
            w: Math.max(MIN, persisted.w),
            h: Math.max(MIN, persisted.h),
          };
          await syncWindowSize();
        }
        await pushLocal();
      } catch (e) {
        log.error("restore size falló", { err: String(e) });
      }
    })();
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
    log.debug("resize start", { mode, startW: size.w, startH: size.h, pos: { x: pos.x, y: pos.y }, scale });
  }

  async function onMoveDoc(e: PointerEvent) {
    if (!drag) return;
    // movementX/Y es el delta entre eventos consecutivos del navegador.
    // Inmune a saltos de cursor por setPosition durante el drag.
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
      // Posición ABSOLUTA = posición inicial + delta. NO usamos la posición
      // actual de la ventana (que podría estar desactualizada por awaits).
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
    log.debug("resize end", { mode: drag.mode, finalSize: { w: size.w, h: size.h }, accum: { dx: drag.accumDx, dy: drag.accumDy } });
    drag = null;
    await pushLocal();
  }

  async function pushLocal() {
    try {
      await setMarkerRect(name, {
        x: PADDING,
        y: PADDING,
        w: Math.round(size.w),
        h: Math.round(size.h),
      });
      log.debug("rect pushed", { x: PADDING, y: PADDING, w: size.w, h: size.h });
    } catch (e) {
      log.error("push rect falló", { err: String(e) });
    }
  }

  const labelText = name === "wind" ? "WIND" : "ANGLE";
</script>

<svelte:window onpointermove={onMoveDoc} onpointerup={onEnd} onpointercancel={onEnd} />

<div
  class="rect"
  style:--padding="{PADDING}px"
  style:--w="{size.w}px"
  style:--h="{size.h}px"
>
  <div class="body" data-tauri-drag-region role="presentation"></div>

  <span class="label">{labelText} {Math.round(size.w)}×{Math.round(size.h)}</span>

  <button class="edge n"  onpointerdown={(e) => onResizeStart(e, "n")}  aria-label="north"></button>
  <button class="edge s"  onpointerdown={(e) => onResizeStart(e, "s")}  aria-label="south"></button>
  <button class="edge w"  onpointerdown={(e) => onResizeStart(e, "w")}  aria-label="west"></button>
  <button class="edge e"  onpointerdown={(e) => onResizeStart(e, "e")}  aria-label="east"></button>

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

  .rect {
    position: fixed;
    left: var(--padding);
    top: var(--padding);
    width: var(--w);
    height: var(--h);
    border: 1px solid rgba(80, 200, 255, 0.95);
    background: rgba(80, 200, 255, 0.06);
    box-sizing: border-box;
  }

  .body {
    position: absolute;
    inset: 0;
    cursor: move;
  }

  /* Label DENTRO del rect, en esquina superior-izquierda. No se sale
     del area visible aunque el rect sea chico. */
  .label {
    position: absolute;
    top: 1px;
    left: 1px;
    font-size: 8px;
    color: rgba(255, 255, 255, 0.95);
    letter-spacing: 0.04em;
    text-transform: uppercase;
    background: rgba(0, 0, 0, 0.75);
    padding: 0 3px;
    border-radius: 2px;
    line-height: 1.2;
    pointer-events: none;
    white-space: nowrap;
    z-index: 5;
  }

  .edge {
    position: absolute;
    background: transparent;
    border: 0;
    padding: 0;
    margin: 0;
    z-index: 2;
  }
  .edge.n { top: -6px;    left: 4px;  right: 4px; height: 8px; cursor: ns-resize; }
  .edge.s { bottom: -6px; left: 4px;  right: 4px; height: 8px; cursor: ns-resize; }
  .edge.w { top: 4px;     bottom: 4px; left: -6px; width: 8px; cursor: ew-resize; }
  .edge.e { top: 4px;     bottom: 4px; right: -6px; width: 8px; cursor: ew-resize; }

  .corner {
    position: absolute;
    width: 9px;
    height: 9px;
    background: rgba(80, 200, 255, 0.95);
    border: 1px solid rgba(0, 0, 0, 0.85);
    padding: 0;
    margin: 0;
    z-index: 3;
  }
  .nw { top: -2px;    left: -2px;    cursor: nwse-resize; }
  .se { bottom: -2px; right: -2px;   cursor: nwse-resize; }
  .ne { top: -2px;    right: -2px;   cursor: nesw-resize; }
  .sw { bottom: -2px; left: -2px;    cursor: nesw-resize; }

  button:focus { outline: none; }
</style>
