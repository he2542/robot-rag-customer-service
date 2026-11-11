<script setup>
defineProps({ modelValue: { type: String, default: '' }, loading: Boolean, ready: Boolean, status: String })
defineEmits(['update:modelValue', 'send'])
</script>

<template>
  <form class="composer" @submit.prevent="$emit('send')">
    <input :value="modelValue" @input="$emit('update:modelValue', $event.target.value)"
      aria-label="咨询问题" maxlength="4000" :disabled="loading || !ready"
      :placeholder="ready ? '描述型号和遇到的问题…' : status" autocomplete="off" />
    <button type="submit" :disabled="loading || !ready || !modelValue.trim()">发送</button>
  </form>
</template>
