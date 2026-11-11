<script setup>
defineProps({ sources: { type: Array, default: () => [] } })
</script>

<template>
  <details v-if="sources.length" class="sources">
    <summary>检索参考资料 · {{ sources.length }} 个片段</summary>
    <p class="source-hint">以下为本次召回的候选资料，可展开核对；不代表回答中的每句话已获验证。</p>
    <div v-for="source in sources" :key="source.id" class="source-item">
      <strong>[{{ source.id }}] {{ source.filename }} · 片段 {{ source.chunk_index + 1 }}</strong>
      <p>{{ source.excerpt }}</p>
    </div>
  </details>
</template>
