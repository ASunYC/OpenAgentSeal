<template>
  <form class="access-prompt" @submit.prevent="connect">
    <div>
      <p>LOCAL OPERATOR ACCESS</p>
      <h4>{{ t('建立短期运营会话', 'Establish a short-lived operational session') }}</h4>
      <span>{{ t('输入宿主或管理员提供的一次性 capability。成功后会立即消费，且不会保存到浏览器。', 'Enter the one-time capability supplied by the host or administrator. It is consumed immediately and never saved by the browser.') }}</span>
    </div>
    <label>
      <span>{{ t('一次性 capability（仅写入）', 'One-time capability (write-only)') }}</span>
      <input v-model="capability" type="password" autocomplete="off" spellcheck="false" minlength="32" required />
    </label>
    <p role="alert" aria-live="assertive">{{ error }}</p>
    <button type="submit" :disabled="busy || capability.length < 32">{{ busy ? t('建立中…', 'Establishing…') : t('建立会话', 'Establish session') }}</button>
  </form>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { bootstrapOperationalSession, provideOperationalBootstrapCapability } from '@/api/autonomics'
import { useSettingsStore } from '@/stores/settings'

const emit = defineEmits<{ connected: [] }>()
const settingsStore = useSettingsStore()
const capability = ref('')
const busy = ref(false)
const error = ref('')

function t(zh: string, en: string): string { return settingsStore.t(zh, en) }
async function connect(): Promise<void> {
  const supplied = capability.value
  capability.value = ''
  busy.value = true; error.value = ''
  try {
    provideOperationalBootstrapCapability(supplied)
    await bootstrapOperationalSession()
    emit('connected')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t('无法建立运营会话', 'Could not establish the operational session')
  } finally { busy.value = false }
}
onBeforeUnmount(() => { capability.value = '' })
</script>

<style scoped>
.access-prompt { display: grid; grid-template-columns: 1.3fr 1fr auto; align-items: end; gap: 16px; padding: 18px; border: 1px solid #b47a2f; border-left-width: 3px; border-radius: 10px; background: color-mix(in srgb, #b47a2f 7%, transparent); }
.access-prompt div { align-self: center; } .access-prompt p { min-height: 16px; margin: 0; color: #a34538; font-size: 11px; } .access-prompt div p { color: #8a641e; font: 700 10px ui-monospace, monospace; letter-spacing: .08em; } h4 { margin: 5px 0; } .access-prompt div span, label span { color: var(--text-muted); font-size: 11px; line-height: 1.45; } label { display: grid; gap: 6px; } input { min-width: 0; padding: 9px 10px; border: 1px solid var(--border-color); border-radius: 8px; background: var(--input-bg, rgba(255,255,255,.6)); color: var(--text-primary); } button { min-height: 38px; padding: 0 13px; border: 0; border-radius: 8px; background: #2d766e; color: white; cursor: pointer; font-weight: 650; } button:disabled { cursor: not-allowed; opacity: .5; }
@media (max-width: 720px) { .access-prompt { grid-template-columns: minmax(0, 1fr); align-items: stretch; } }
</style>
