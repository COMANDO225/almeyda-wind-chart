<script lang="ts">
  import { page } from "$app/state";
  import CornerMarker from "$lib/CornerMarker.svelte";
  import type { CornerName } from "$lib/ipc";

  const name = $derived((page.url.searchParams.get("name") ?? "tl") as CornerName);
</script>

<CornerMarker {name} />
