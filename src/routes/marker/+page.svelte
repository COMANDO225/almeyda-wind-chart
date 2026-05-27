<script lang="ts">
  import { page } from "$app/state";
  import MarkerFrame from "$lib/MarkerFrame.svelte";

  const name = $derived(
    (page.url.searchParams.get("name") ?? "wind") as "wind" | "angle",
  );

  const label = $derived(name === "wind" ? "WIND" : "ANGLE");
</script>

<MarkerFrame {name} {label} />
