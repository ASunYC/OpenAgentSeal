<template>
  <Teleport to="body">
    <div v-if="open" class="operational-dialog-backdrop" @mousedown.self="cancel">
      <section
        ref="dialog"
        class="operational-dialog"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="titleId"
        :aria-describedby="descriptionId"
        @keydown="onKeydown"
      >
        <header>
          <p class="eyebrow">{{ eyebrow }}</p>
          <h3 :id="titleId">{{ title }}</h3>
          <p :id="descriptionId">{{ description }}</p>
        </header>

        <label v-if="confirmationPhrase" class="field">
          <span>{{ t('输入确认短语', 'Type the confirmation phrase') }}</span>
          <code>{{ confirmationPhrase }}</code>
          <input ref="firstInput" v-model="confirmation" autocomplete="off" spellcheck="false" />
        </label>

        <label v-if="sensitiveLabel" class="field">
          <span>{{ sensitiveLabel }}</span>
          <textarea ref="sensitiveInput" v-model="sensitiveValue" autocomplete="off" spellcheck="false" />
          <small>{{ t('仅发送一次；不会保存到浏览器存储。', 'Sent once and never saved to browser storage.') }}</small>
        </label>

        <label v-if="requireReauthentication" class="field">
          <span>{{ t('确认用户在场', 'Confirm user presence') }}</span>
          <code>REAUTHENTICATE</code>
          <input
            ref="reauthInput"
            v-model="reauthentication"
            type="text"
            autocomplete="off"
            spellcheck="false"
          />
          <small>{{ t('将轮换现有短期会话；关闭后立即清除。', 'Rotates the existing short-lived session and is cleared on close.') }}</small>
        </label>

        <p class="dialog-error" role="alert" aria-live="assertive">{{ error }}</p>
        <footer>
          <button type="button" class="secondary" :disabled="busy" @click="cancel">{{ t('取消', 'Cancel') }}</button>
          <button type="button" class="danger" :disabled="!ready || busy" @click="confirm">
            {{ busy ? t('处理中…', 'Working…') : confirmLabel }}
          </button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useSettingsStore } from '@/stores/settings'

const props = withDefaults(defineProps<{
  open: boolean
  title: string
  description: string
  confirmLabel: string
  eyebrow?: string
  confirmationPhrase?: string
  sensitiveLabel?: string
  requireReauthentication?: boolean
  busy?: boolean
  error?: string
}>(), {
  eyebrow: 'Operator action',
  confirmationPhrase: '',
  sensitiveLabel: '',
  requireReauthentication: true,
  busy: false,
  error: '',
})

const emit = defineEmits<{
  cancel: []
  confirm: [payload: { reauthentication: string; sensitiveValue: string }]
}>()

const settingsStore = useSettingsStore()
const dialog = ref<HTMLElement | null>(null)
const firstInput = ref<HTMLInputElement | null>(null)
const reauthInput = ref<HTMLInputElement | null>(null)
const sensitiveInput = ref<HTMLTextAreaElement | null>(null)
const confirmation = ref('')
const reauthentication = ref('')
const sensitiveValue = ref('')
let restoreFocus: HTMLElement | null = null
const uniqueId = Math.random().toString(36).slice(2)
const titleId = `operational-title-${uniqueId}`
const descriptionId = `operational-description-${uniqueId}`

const ready = computed(() => (
  (!props.confirmationPhrase || confirmation.value === props.confirmationPhrase)
  && (!props.sensitiveLabel || sensitiveValue.value.trim().length > 0)
  && (!props.requireReauthentication || reauthentication.value === 'REAUTHENTICATE')
))

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

function focusable(): HTMLElement[] {
  if (!dialog.value) return []
  return [...dialog.value.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')]
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && !props.busy) {
    event.preventDefault()
    cancel()
    return
  }
  if (event.key !== 'Tab') return
  const items = focusable()
  if (items.length === 0) return
  const first = items[0]
  const last = items.at(-1) ?? first
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

function clearSensitive(): void {
  confirmation.value = ''
  reauthentication.value = ''
  sensitiveValue.value = ''
}

function cancel(): void {
  if (props.busy) return
  clearSensitive()
  emit('cancel')
}

function confirm(): void {
  if (!ready.value || props.busy) return
  emit('confirm', { reauthentication: reauthentication.value, sensitiveValue: sensitiveValue.value })
}

watch(() => props.open, async open => {
  if (open) {
    restoreFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    await nextTick()
    ;(firstInput.value ?? sensitiveInput.value ?? reauthInput.value ?? focusable()[0])?.focus()
  } else {
    clearSensitive()
    restoreFocus?.focus()
    restoreFocus = null
  }
})

onBeforeUnmount(() => {
  clearSensitive()
  restoreFocus?.focus()
})
</script>

<style scoped>
.operational-dialog-backdrop { position: fixed; inset: 0; z-index: 80; display: grid; place-items: center; padding: 20px; background: rgba(23, 27, 32, .58); }
.operational-dialog { width: min(100%, 470px); padding: 24px; border: 1px solid var(--border-color); border-radius: 18px; background: var(--panel-bg, #f8f9fa); color: var(--text-primary); box-shadow: 0 24px 70px rgba(20, 24, 29, .24), inset 0 1px rgba(255,255,255,.55); }
header { margin-bottom: 20px; }
.eyebrow { margin: 0 0 7px; color: #b44d3a; font: 650 11px/1.2 ui-monospace, SFMono-Regular, Consolas, monospace; letter-spacing: .08em; text-transform: uppercase; }
h3 { margin: 0 0 8px; font-size: 19px; letter-spacing: -.02em; }
header p:last-child { margin: 0; color: var(--text-muted); font-size: 13px; line-height: 1.55; }
.field { display: grid; gap: 7px; margin-top: 16px; color: var(--text-secondary); font-size: 12px; }
code { width: fit-content; padding: 4px 7px; border-radius: 6px; background: var(--hover-bg); color: var(--text-primary); }
input, textarea { min-width: 0; padding: 10px 11px; border: 1px solid var(--border-color); border-radius: 9px; background: var(--input-bg, rgba(255,255,255,.7)); color: var(--text-primary); }
textarea { min-height: 78px; resize: vertical; }
input:focus, textarea:focus { outline: 2px solid color-mix(in srgb, #2d766e 42%, transparent); outline-offset: 2px; }
small { color: var(--text-muted); line-height: 1.45; }
.dialog-error { min-height: 18px; margin: 12px 0 0; color: #b43c32; font-size: 12px; }
footer { display: flex; justify-content: flex-end; gap: 9px; margin-top: 16px; }
button { min-height: 38px; padding: 0 14px; border: 1px solid var(--border-color); border-radius: 9px; cursor: pointer; font-weight: 650; transition: transform .16s ease, background .16s ease; }
button:active:not(:disabled) { transform: translateY(1px); }
button:disabled { cursor: not-allowed; opacity: .46; }
.secondary { background: transparent; color: var(--text-secondary); }
.danger { border-color: #a84b3b; background: #a84b3b; color: white; }
@media (prefers-reduced-motion: reduce) { button { transition: none; } }
</style>
