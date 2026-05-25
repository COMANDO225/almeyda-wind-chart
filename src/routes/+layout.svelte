<script lang="ts">
  let { children } = $props();
</script>

{@render children()}

<style>
  :global(html),
  :global(body) {
    background: transparent !important;
  }
</style>
