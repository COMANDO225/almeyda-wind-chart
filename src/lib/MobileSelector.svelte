<script lang="ts">
  // MVP: una sola opción (Armor). Se expone como dropdown para que en Fase 4 se
  // pueda agregar más mobiles sin tocar el resto del panel.

  interface Props {
    value: string;
    onChange?: (m: string) => void;
  }

  let { value = $bindable("armor"), onChange }: Props = $props();
  const options = [{ id: "armor", label: "Armor" }];

  function handleChange(e: Event) {
    const v = (e.target as HTMLSelectElement).value;
    value = v;
    onChange?.(v);
  }
</script>

<label class="wrap">
  <span class="lbl">Mobile</span>
  <select value={value} onchange={handleChange}>
    {#each options as opt}
      <option value={opt.id}>{opt.label}</option>
    {/each}
  </select>
</label>

<style>
  .wrap {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    background: rgba(255, 255, 255, 0.04);
    padding: 8px 12px;
    border-radius: 8px;
    border: 1px solid rgba(255, 255, 255, 0.08);
  }
  .lbl {
    color: #b8b8c0;
    font-size: 13px;
    letter-spacing: 0.04em;
  }
  select {
    background: #1a1a20;
    color: #fff;
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 13px;
    outline: none;
  }
</style>
