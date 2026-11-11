<script setup>
defineProps({ knowledge: { type: Object, required: true }, disabled: Boolean })
defineEmits(['ask'])
const scopeNote = '资料来自课程示例，非品牌官方手册；具体型号参数及保修政策以官方说明为准。'
</script>

<template>
  <aside class="knowledge-card">
    <div class="card-heading">
      <div><h2>内置知识库</h2><p>直接提问，无需上传文件</p></div>
    </div>
    <ul class="knowledge-files">
      <li v-for="file in knowledge.files" :key="file.filename">{{ file.filename.replace(/\.txt$/i, '') }}</li>
    </ul>
    <p v-if="knowledge.ready" class="feedback">已收录 {{ knowledge.files.length }} 份资料</p>
    <p v-else class="feedback">知识库暂未就绪，稍后刷新查看。</p>
    <h2 class="example-title">可以这样问</h2>
    <button class="example-question" :disabled="disabled"
      @click="$emit('ask', '扫地机器人吸力下降，应该先检查什么？')">吸力下降，先检查什么？</button>
    <button class="example-question" :disabled="disabled"
      @click="$emit('ask', '日常应该如何清理主刷和滤网？')">主刷和滤网怎么保养？</button>
    <p class="scope-note">{{ knowledge.scope_note || scopeNote }}</p>
  </aside>
</template>
