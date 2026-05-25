<script lang="ts">
  // Compás de viento estilo imagen 7 del usuario: fondo negro mate, 12 marcas
  // radiales naranjas, "Wind" arriba, número grande en rectángulo gris, aguja
  // roja con destello apuntando 0–360° (0 = derecha, 90 = abajo).

  interface Props {
    value: number | null;
    directionDeg: number | null;
  }

  let { value, directionDeg }: Props = $props();

  // Display: muestra "--" si no hay valor todavía.
  const display = $derived(value === null ? "--" : String(value));
  const angle = $derived(directionDeg ?? 0);
  const ticks = Array.from({ length: 16 }, (_, i) => i * 22.5);
</script>

<div class="compass" style:--angle="{angle}deg">
  <div class="ring">
    {#each ticks as deg}
      <div class="tick" style:transform="rotate({deg}deg) translateY(-44%)"></div>
    {/each}
  </div>
  <div class="needle"></div>
  <div class="center">
    <div class="label">Wind</div>
    <div class="value-box">
      <span class="value">{display}</span>
    </div>
  </div>
</div>

<style>
  .compass {
    --size: 200px;
    --bg: #0d0d10;
    --tick: #f08020;
    --tick-dim: #5a2e10;
    --needle: #ff3a1f;

    position: relative;
    width: var(--size);
    height: var(--size);
    border-radius: 50%;
    background:
      radial-gradient(circle at 50% 50%, #16161c 0%, #0a0a0d 70%, #050507 100%);
    box-shadow:
      inset 0 0 0 2px rgba(255, 255, 255, 0.04),
      0 8px 24px rgba(0, 0, 0, 0.5),
      0 1px 0 rgba(255, 255, 255, 0.07);
  }

  .ring {
    position: absolute;
    inset: 0;
  }
  .tick {
    position: absolute;
    top: 50%;
    left: 50%;
    width: 4px;
    height: 14px;
    margin-left: -2px;
    margin-top: -7px;
    border-radius: 2px;
    background: var(--tick);
    transform-origin: 50% 50%;
    box-shadow: 0 0 6px rgba(240, 128, 32, 0.5);
  }

  .needle {
    position: absolute;
    top: 50%;
    left: 50%;
    width: 50%;
    height: 4px;
    margin-top: -2px;
    transform-origin: 0% 50%;
    transform: rotate(var(--angle));
    transition: transform 150ms ease-out;
    pointer-events: none;
  }
  .needle::before {
    content: "";
    position: absolute;
    inset: 0;
    background: linear-gradient(
      90deg,
      transparent 0%,
      transparent 35%,
      var(--needle) 60%,
      #ffd28a 100%
    );
    border-radius: 2px;
    filter: drop-shadow(0 0 4px rgba(255, 58, 31, 0.7));
  }
  .needle::after {
    content: "";
    position: absolute;
    right: -6px;
    top: -3px;
    width: 0;
    height: 0;
    border-left: 10px solid #ffd28a;
    border-top: 5px solid transparent;
    border-bottom: 5px solid transparent;
    filter: drop-shadow(0 0 6px rgba(255, 58, 31, 0.8));
  }

  .center {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    pointer-events: none;
  }
  .label {
    color: #e8e8ec;
    font-size: 14px;
    letter-spacing: 0.06em;
    margin-bottom: 4px;
    font-weight: 500;
    opacity: 0.9;
  }
  .value-box {
    background: rgba(40, 40, 46, 0.85);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 6px;
    padding: 4px 18px;
    min-width: 64px;
    text-align: center;
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05);
  }
  .value {
    color: #fff;
    font-size: 32px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    line-height: 1;
  }
</style>
