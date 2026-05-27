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
  //
  // SHAPE: el marker_wind es CIRCULAR (border-radius:50% + cuadrado
  // forzado al redimensionar). El marker_angle es cuadrado/rectangular libre.
  // Cuando el rect es circular, el detector aplicará máscara circular al
  // PNG antes del OCR para que la zona fuera del círculo no aporte ruido.

  import { onMount } from "svelte";
  import { LogicalSize, PhysicalPosition } from "@tauri-apps/api/dpi";
  import { getCurrentWindow } from "@tauri-apps/api/window";
  import { setMarkerRect, getMarkerRect } from "$lib/ipc";
  import { log } from "$lib/log";

  interface Props {
    name: "wind" | "angle";
    label?: string;
    initialSize?: { w: number; h: number };
  }

  let {
    name,
    label,
    initialSize = name === "wind" ? { w: 100, h: 100 } : { w: 40, h: 36 },
  }: Props = $props();

  /** marker_wind es circular (radar del viento). angle es rectangular. */
  const isCircular = name === "wind";

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
      log.info("marker onMount", { name, initialSize, isCircular, PADDING, MIN });
      if (isCircular && size.w !== size.h) {
        const s = Math.max(size.w, size.h);
        size = { w: s, h: s };
      }
      await syncWindowSize();
      try {
        const persisted = await getMarkerRect(name);
        log.info("rect persisted leído", { persisted });
        if (persisted) {
          let w = Math.max(MIN, persisted.w);
          let h = Math.max(MIN, persisted.h);
          if (isCircular) {
            const s = Math.max(w, h);
            w = h = s;
          }
          size = { w, h };
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

    // Para markers circulares: fuerzo w = h tomando el delta diagonal mayor.
    // Esto evita que el círculo se aplaste a elipse al arrastrar un esquinero.
    if (isCircular) {
      // El tamaño objetivo es el promedio o el mayor entre w y h. Tomamos el
      // mayor para que se sienta responsive al cursor.
      const target = Math.max(w, h);
      // Reajustar shifts si W o H se ajustaron y se cambian.
      if (drag.mode.includes("w")) shiftX += (target - w);
      if (drag.mode.includes("n")) shiftY += (target - h);
      w = h = target;
    }

    if (w < MIN) {
      if (drag.mode.includes("w")) shiftX -= MIN - w;
      w = MIN;
    }
    if (h < MIN) {
      if (drag.mode.includes("n")) shiftY -= MIN - h;
      h = MIN;
    }
    if (isCircular) {
      const m = Math.max(w, h, MIN);
      w = h = m;
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

  const labelText = $derived(label ?? (name === "wind" ? "WIND" : "ANGLE"));
</script>

<svelte:window onpointermove={onMoveDoc} onpointerup={onEnd} onpointercancel={onEnd} />

<div
  class="rect"
  class:circle={isCircular}
  style:--padding="{PADDING}px"
  style:--w="{size.w}px"
  style:--h="{size.h}px"
>
  <div class="body" data-tauri-drag-region role="presentation"></div>

  <!-- Label oculto: el usuario distingue los markers por FORMA (circular =
       wind, rectangular = angle). Y al capturar dataset con F1, el label no
       contamina el PNG resultante. -->
  <!-- (label removido tras feedback del usuario) -->

  <!-- Bordes solo en rect cuadrado (no tienen sentido en círculo). -->
  {#if !isCircular}
    <button class="edge n"  onpointerdown={(e) => onResizeStart(e, "n")}  aria-label="north"></button>
    <button class="edge s"  onpointerdown={(e) => onResizeStart(e, "s")}  aria-label="south"></button>
    <button class="edge w"  onpointerdown={(e) => onResizeStart(e, "w")}  aria-label="west"></button>
    <button class="edge e"  onpointerdown={(e) => onResizeStart(e, "e")}  aria-label="east"></button>
  {/if}

  <!-- Esquineros (siempre presentes, diagonalmente — mantienen w=h en círculo). -->
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
    /* Border y fondo visibles — el usuario tiene que ver el marker para
       posicionarlo. Cuando F1/F2 capturan, el backend Rust hace `hide()` de
       la ventana un instante, captura el juego debajo, y vuelve a `show()`.
       Asi la captura no incluye el marker. */
    border: 1px solid rgba(80, 200, 255, 0.85);
    background: rgba(80, 200, 255, 0.05);
    box-sizing: border-box;
  }

  /* Marker circular para el viento — radar del juego es circular. */
  .rect.circle {
    border-radius: 50%;
  }

  .body {
    position: absolute;
    inset: 0;
    cursor: move;
  }
  /* Body circular para que el cursor "move" solo aparezca dentro del círculo. */
  .rect.circle .body {
    border-radius: 50%;
  }

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
  /* Edges en el borde del rect (visibles para el usuario al hover). El
     backend oculta la ventana antes de capturar, asi que no aparecen en
     el PNG aunque esten dentro del area del rect. */
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
  /* Corners en las esquinas del rect (visibles). El backend oculta la
     ventana antes de capturar, no salen en los PNGs. */
  .nw { top: -2px;    left: -2px;    cursor: nwse-resize; }
  .se { bottom: -2px; right: -2px;   cursor: nwse-resize; }
  .ne { top: -2px;    right: -2px;   cursor: nesw-resize; }
  .sw { bottom: -2px; left: -2px;    cursor: nesw-resize; }

  /* En modo círculo, los esquineros se posicionan a las "esquinas" del
     bounding box cuadrado (no del círculo). Lo dejamos así para que la
     UI siga siendo intuitiva. */

  button:focus { outline: none; }
</style>
