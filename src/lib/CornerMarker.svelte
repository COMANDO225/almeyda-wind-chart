<script lang="ts">
  // Esquinero que ancla una esquina de la ZONA DE JUEGO. La ventana entera es
  // arrastrable (data-tauri-drag-region); el VERTICE que ancla es el CENTRO de
  // la cruz (= centro de la ventana). Cada vez que la ventana se mueve,
  // reportamos ese centro en pixels FISICOS absolutos al backend, que lo
  // persiste y, con ambos esquineros, deriva el rectangulo de la zona.
  //
  // No es redimensionable: solo importa donde esta el vertice. TL marca la
  // esquina superior-izquierda, BR la inferior-derecha.

  import { onMount } from "svelte";
  import { PhysicalPosition } from "@tauri-apps/api/dpi";
  import { getCurrentWindow } from "@tauri-apps/api/window";
  import { getCorner, setCorner, type CornerName } from "$lib/ipc";
  import { log } from "$lib/log";

  interface Props {
    name: CornerName;
  }
  let { name }: Props = $props();

  const win = getCurrentWindow();
  let saveTimer: ReturnType<typeof setTimeout> | null = null;

  /** Centro de la ventana en pixels fisicos absolutos = el vertice de la cruz. */
  async function vertexFromWindow(): Promise<{ x: number; y: number }> {
    const pos = await win.outerPosition();
    const sz = await win.outerSize();
    return {
      x: pos.x + Math.round(sz.width / 2),
      y: pos.y + Math.round(sz.height / 2),
    };
  }

  // Debounce: onMoved dispara muchas veces durante el arrastre; persistir en
  // disco en cada evento seria excesivo. Guardamos 200 ms despues del ultimo.
  function scheduleSave() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(async () => {
      try {
        await setCorner(name, await vertexFromWindow());
      } catch (e) {
        log.error("set_corner fallo", { name, err: String(e) });
      }
    }, 200);
  }

  onMount(() => {
    let unlisten: (() => void) | undefined;
    (async () => {
      log.info("corner onMount", { name });
      try {
        const saved = await getCorner(name);
        if (saved) {
          const sz = await win.outerSize();
          await win.setPosition(
            new PhysicalPosition(
              saved.x - Math.round(sz.width / 2),
              saved.y - Math.round(sz.height / 2),
            ),
          );
        } else {
          // Primera vez: persistir la posicion inicial del tauri.conf.
          scheduleSave();
        }
        unlisten = await win.onMoved(() => scheduleSave());
      } catch (e) {
        log.error("corner restore fallo", { name, err: String(e) });
      }
    })();
    return () => {
      unlisten?.();
      if (saveTimer) clearTimeout(saveTimer);
    };
  });

  const tag = $derived(name === "tl" ? "TL" : "BR");
</script>

<div class="bracket" class:tl={name === "tl"} class:br={name === "br"} data-tauri-drag-region role="presentation">
  <div class="line h"></div>
  <div class="line v"></div>
  <div class="dot"></div>
  <span class="tag">{tag}</span>
</div>

<style>
  :global(html), :global(body) {
    margin: 0;
    padding: 0;
    background: transparent;
    overflow: hidden;
  }

  .bracket {
    position: fixed;
    inset: 0;
    cursor: move;
  }

  /* Esquinero estilo "L" (mira de camara): horizontal corto + vertical corto
     que se encuentran en el VERTICE (centro de la ventana = punto de anclaje).
     TL apunta hacia adentro de la zona (derecha-abajo), BR contraria. */
  .line {
    position: absolute;
    background: rgba(120, 255, 140, 0.95);
    pointer-events: none;
    border-radius: 1px;
    box-shadow: 0 0 4px rgba(120, 255, 140, 0.5);
  }
  /* Largo y grosor de cada brazo de la L. */
  .line.h { height: 4px; width: 26px; }
  .line.v { width: 4px; height: 26px; }

  /* TL: horizontal va a la DERECHA desde el centro,
         vertical va hacia ABAJO desde el centro. */
  .bracket.tl .line.h {
    left: 50%;
    top: 50%;
    transform: translateY(-50%);
  }
  .bracket.tl .line.v {
    top: 50%;
    left: 50%;
    transform: translateX(-50%);
  }

  /* BR: horizontal va a la IZQUIERDA desde el centro,
         vertical va hacia ARRIBA desde el centro. */
  .bracket.br .line.h {
    right: 50%;
    top: 50%;
    transform: translateY(-50%);
  }
  .bracket.br .line.v {
    bottom: 50%;
    left: 50%;
    transform: translateX(-50%);
  }

  /* Punto en el vertice (intersection de las dos lineas). */
  .dot {
    position: absolute;
    left: 50%;
    top: 50%;
    width: 8px;
    height: 8px;
    margin: -4px 0 0 -4px;
    border: 1px solid rgba(0, 0, 0, 0.85);
    background: rgba(120, 255, 140, 1);
    border-radius: 50%;
    pointer-events: none;
    box-shadow: 0 0 6px rgba(120, 255, 140, 0.7);
  }
  /* Tag (TL/BR) en el angulo interior de la L. */
  .tag {
    position: absolute;
    font: 9px/1.2 system-ui, sans-serif;
    color: rgba(255, 255, 255, 0.95);
    background: rgba(0, 0, 0, 0.7);
    padding: 1px 4px;
    border-radius: 2px;
    pointer-events: none;
    user-select: none;
  }
  .bracket.tl .tag {
    top: calc(50% + 8px);
    left: calc(50% + 8px);
  }
  .bracket.br .tag {
    bottom: calc(50% + 8px);
    right: calc(50% + 8px);
  }
</style>
