<script lang="ts">
  import { goto } from "$app/navigation";
  import { onMount } from "svelte";

  // Ruta raíz — redirige a /panel. Las 3 ventanas reales de Tauri apuntan
  // directamente a /panel y /marker?name=... así que este redirect es solo
  // un fallback por seguridad.
  onMount(() => {
    goto("/panel", { replaceState: true });
  });
</script>
