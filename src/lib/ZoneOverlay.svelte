<script lang="ts">
  // Overlay click-through que cubre el monitor primario y dibuja los puntos
  // YO (origen) y EL (destino) marcados con Q/E. La ventana se posiciona en el
  // origen del monitor (lo hace Rust), asi un punto absoluto (px,py) cae en
  // CSS logico en ((px - winX)/scale, (py - winY)/scale).
  //
  // Es donde, en una iteracion futura, se dibujara la curva del disparo.

  import { onMount } from "svelte";
  import { getCurrentWindow } from "@tauri-apps/api/window";
  import { getPoints, onPoints, type Point } from "$lib/ipc";

  const win = getCurrentWindow();

  let yo = $state<Point | null>(null);
  let el = $state<Point | null>(null);
  let winX = $state(0);
  let winY = $state(0);
  let scale = $state(1);

  async function refreshGeom() {
    const p = await win.outerPosition();
    winX = p.x;
    winY = p.y;
    scale = await win.scaleFactor();
  }

  onMount(() => {
    let unPoints: (() => void) | undefined;
    let unMoved: (() => void) | undefined;
    let unResized: (() => void) | undefined;
    (async () => {
      await refreshGeom();
      const pts = await getPoints();
      yo = pts.yo;
      el = pts.el;
      unPoints = await onPoints(async (p) => {
        await refreshGeom();
        yo = p.yo;
        el = p.el;
      });
      unMoved = await win.onMoved(() => refreshGeom());
      unResized = await win.onResized(() => refreshGeom());
    })();
    return () => {
      unPoints?.();
      unMoved?.();
      unResized?.();
    };
  });

  function cssLeft(pt: Point): number {
    return (pt.x - winX) / scale;
  }
  function cssTop(pt: Point): number {
    return (pt.y - winY) / scale;
  }
</script>

{#if yo}
  <div class="pt yo" style:left="{cssLeft(yo)}px" style:top="{cssTop(yo)}px">
    <span class="lbl">YO</span>
  </div>
{/if}
{#if el}
  <div class="pt el" style:left="{cssLeft(el)}px" style:top="{cssTop(el)}px">
    <span class="lbl">EL</span>
  </div>
{/if}

<style>
  :global(html), :global(body) {
    margin: 0;
    padding: 0;
    background: transparent;
    overflow: hidden;
  }

  .pt {
    position: fixed;
    width: 8px;
    height: 8px;
    margin: -4px 0 0 -4px;
    border-radius: 50%;
    border: 1px solid rgba(0, 0, 0, 0.85);
    pointer-events: none;
  }
  .pt.yo {
    background: rgba(120, 230, 255, 0.95);
    box-shadow: 0 0 6px rgba(120, 230, 255, 0.7);
  }
  .pt.el {
    background: rgba(255, 120, 140, 0.95);
    box-shadow: 0 0 6px rgba(255, 120, 140, 0.7);
  }
  .lbl {
    position: absolute;
    left: 9px;
    top: -5px;
    font: 9px/1.2 system-ui, sans-serif;
    color: #fff;
    background: rgba(0, 0, 0, 0.7);
    padding: 0 3px;
    border-radius: 2px;
    white-space: nowrap;
  }
</style>
