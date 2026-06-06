<template>
  <div class="tab-content">
    <div class="content-header">
      <h3>{{ t('移动端连接', 'Mobile Access') }}</h3>
      <p>{{ t('通过局域网手机壳控制这台电脑上的 OpenAgentSeal', 'Control this workstation from a mobile shell on the same network') }}</p>
    </div>

    <section class="settings-card">
      <div class="card-heading">
        <div>
          <h4>{{ t('配对入口', 'Pairing') }}</h4>
          <span>{{ t('配对码有效期为 3 分钟', 'Pairing codes expire after 3 minutes') }}</span>
        </div>
        <div class="card-actions">
          <button class="refresh-button" :disabled="loading" @click="loadAccessInfo">
            {{ loading ? t('刷新中...', 'Refreshing...') : t('刷新', 'Refresh') }}
          </button>
          <button class="primary-button" :disabled="pairingLoading" @click="createPairingCode">
            {{ pairingLoading ? t('生成中...', 'Generating...') : t('生成配对码', 'Generate Code') }}
          </button>
        </div>
      </div>

      <div v-if="pairingCode" class="pairing-panel">
        <div class="pairing-code-block">
          <img v-if="qrDataUrl" :src="qrDataUrl" :alt="t('移动端配对二维码', 'Mobile pairing QR code')" />
          <div>
            <span>{{ t('配对码', 'Code') }}</span>
            <strong>{{ pairingCode.code }}</strong>
            <small>
              {{ pairingSecondsLeft > 0
                ? t(`${pairingSecondsLeft} 秒后过期`, `Expires in ${pairingSecondsLeft}s`)
                : t('配对码已过期', 'Pairing code expired') }}
            </small>
          </div>
        </div>
        <div class="pairing-actions">
          <button class="copy-button" @click="copyText(pairingCode.mobile_url)">
            {{ copiedText === pairingCode.mobile_url ? t('已复制', 'Copied') : t('复制链接', 'Copy Link') }}
          </button>
          <span>{{ t('手机扫码会自动填入配对码', 'Scanning fills the pairing code automatically') }}</span>
        </div>
      </div>

      <div v-if="accessInfo" class="state-line" :class="{ success: accessInfo.remote_enabled }">
        {{ accessInfo.remote_enabled ? t('局域网监听已开启', 'LAN listener is enabled') : t('当前仅本机可访问', 'Currently local-only') }}
        · {{ accessInfo.bind_host }}
      </div>

      <div class="mobile-link-list">
        <div v-for="url in displayUrls" :key="url" class="mobile-link-item">
          <span>{{ url }}</span>
          <button @click="copyText(url)">
            {{ copiedText === url ? t('已复制', 'Copied') : t('复制', 'Copy') }}
          </button>
        </div>
      </div>

      <p v-if="!displayUrls.length" class="state-line">
        {{ t('暂无可用链接，点击刷新或生成配对码。', 'No link yet. Refresh or generate a pairing code.') }}
      </p>
      <p v-if="error" class="state-line error">{{ error }}</p>
    </section>

    <section class="settings-card">
      <div class="card-heading">
        <h4>{{ t('已配对设备', 'Paired Devices') }}</h4>
        <span>{{ accessInfo?.paired_devices.length || 0 }}</span>
      </div>

      <div v-if="accessInfo?.paired_devices.length" class="device-list">
        <div v-for="device in accessInfo.paired_devices" :key="device.id" class="device-item">
          <div>
            <strong>{{ device.name }}</strong>
            <p>{{ t('最近连接', 'Last seen') }} {{ formatDate(device.last_seen_at) || '-' }}</p>
          </div>
          <div class="device-actions">
            <span :class="{ active: device.enabled }">{{ device.enabled ? t('启用', 'Enabled') : t('停用', 'Disabled') }}</span>
            <button
              class="revoke-button"
              :disabled="revokingDeviceId === device.id"
              @click="revokeDevice(device.id, device.name)"
            >
              {{ revokingDeviceId === device.id ? t('撤销中…', 'Revoking…') : t('撤销', 'Revoke') }}
            </button>
          </div>
        </div>
      </div>
      <p v-else class="state-line">
        {{ t('还没有移动设备完成配对。', 'No mobile device has paired yet.') }}
      </p>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import QRCode from 'qrcode'
import { mobileApi, type MobileAccessInfo, type MobilePairingCode } from '@/api'
import { useSettingsStore } from '@/stores/settings'

const settingsStore = useSettingsStore()
const accessInfo = ref<MobileAccessInfo | null>(null)
const pairingCode = ref<MobilePairingCode | null>(null)
const loading = ref(false)
const pairingLoading = ref(false)
const error = ref('')
const qrDataUrl = ref('')
const pairingSecondsLeft = ref(0)
const copiedText = ref('')
const revokingDeviceId = ref('')
let pairingTimer: number | undefined
let copiedTimer: number | undefined

const displayUrls = computed(() => {
  if (pairingCode.value?.mobile_urls?.length) {
    const lanUrls = pairingCode.value.mobile_urls.filter(url => !url.includes('127.0.0.1'))
    return lanUrls.length ? lanUrls : pairingCode.value.mobile_urls
  }
  return accessInfo.value?.lan_urls?.length ? accessInfo.value.lan_urls : accessInfo.value?.local_urls || []
})

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

function formatDate(value?: string): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

async function loadAccessInfo(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    accessInfo.value = await mobileApi.getAccessInfo()
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

async function createPairingCode(): Promise<void> {
  pairingLoading.value = true
  error.value = ''
  try {
    pairingCode.value = await mobileApi.createPairingCode()
    qrDataUrl.value = await QRCode.toDataURL(pairingCode.value.mobile_url, {
      width: 220,
      margin: 1,
      errorCorrectionLevel: 'M',
      color: {
        dark: '#111827',
        light: '#ffffff',
      },
    })
    startPairingCountdown()
    await loadAccessInfo()
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    pairingLoading.value = false
  }
}

async function copyText(text: string): Promise<void> {
  await navigator.clipboard?.writeText(text).catch(() => undefined)
  copiedText.value = text
  if (copiedTimer !== undefined) window.clearTimeout(copiedTimer)
  copiedTimer = window.setTimeout(() => {
    copiedText.value = ''
  }, 1800)
}

function startPairingCountdown(): void {
  if (pairingTimer !== undefined) window.clearInterval(pairingTimer)
  const update = () => {
    const expiresAt = pairingCode.value ? new Date(pairingCode.value.expires_at).getTime() : 0
    pairingSecondsLeft.value = Math.max(0, Math.ceil((expiresAt - Date.now()) / 1000))
    if (pairingSecondsLeft.value <= 0 && pairingTimer !== undefined) {
      window.clearInterval(pairingTimer)
      pairingTimer = undefined
    }
  }
  update()
  pairingTimer = window.setInterval(update, 1000)
}

async function revokeDevice(deviceId: string, deviceName: string): Promise<void> {
  if (!window.confirm(t(`确定撤销“${deviceName}”的移动端访问吗？`, `Revoke mobile access for "${deviceName}"?`))) {
    return
  }
  revokingDeviceId.value = deviceId
  error.value = ''
  try {
    await mobileApi.revokeDevice(deviceId)
    await loadAccessInfo()
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    revokingDeviceId.value = ''
  }
}

onMounted(() => {
  void loadAccessInfo()
})

onUnmounted(() => {
  if (pairingTimer !== undefined) window.clearInterval(pairingTimer)
  if (copiedTimer !== undefined) window.clearTimeout(copiedTimer)
})
</script>

<style scoped>
.tab-content {
  display: flex;
  padding: 24px;
  flex-direction: column;
  gap: 18px;
}

.content-header h3,
.content-header p,
.card-heading h4,
.card-heading span {
  margin: 0;
}

.content-header h3 {
  color: var(--text-primary);
  font-size: 20px;
}

.content-header p,
.card-heading span {
  margin-top: 5px;
  color: var(--text-secondary);
  font-size: 13px;
}

.settings-card {
  padding: 18px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--main-bg);
}

.card-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.card-heading h4 {
  color: var(--text-primary);
  font-size: 16px;
}

.card-actions {
  display: flex;
  gap: 8px;
}

.refresh-button,
.primary-button {
  min-height: 36px;
  padding: 0 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--main-bg);
  color: var(--text-primary);
  cursor: pointer;
  font-weight: 650;
}

.primary-button {
  border-color: var(--primary-color);
  background: var(--primary-color);
  color: #ffffff;
}

.refresh-button:disabled,
.primary-button:disabled,
.revoke-button:disabled {
  cursor: default;
  opacity: 0.55;
}

.pairing-panel {
  display: flex;
  margin: 16px 0;
  padding: 16px;
  align-items: center;
  justify-content: space-between;
  border: 1px solid color-mix(in srgb, var(--primary-color) 24%, var(--border-color));
  border-radius: 8px;
  background: color-mix(in srgb, var(--primary-color) 8%, var(--main-bg));
}

.pairing-code-block {
  display: flex;
  align-items: center;
  gap: 16px;
}

.pairing-code-block img {
  width: 132px;
  height: 132px;
  padding: 6px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: #ffffff;
}

.pairing-panel span,
.pairing-panel small {
  display: block;
  color: var(--text-secondary);
  font-size: 12px;
}

.pairing-actions {
  display: flex;
  align-items: flex-end;
  flex-direction: column;
  gap: 8px;
}

.pairing-actions > span {
  max-width: 160px;
  text-align: right;
}

.pairing-panel strong {
  display: block;
  margin: 4px 0;
  color: var(--primary-color);
  font-size: 34px;
  letter-spacing: 0.12em;
}

.mobile-link-list,
.device-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.mobile-link-item,
.device-item {
  display: flex;
  gap: 12px;
  padding: 12px;
  align-items: center;
  justify-content: space-between;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--hover-bg);
}

.mobile-link-item span {
  min-width: 0;
  overflow: hidden;
  color: var(--text-primary);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mobile-link-item button,
.copy-button {
  flex: 0 0 auto;
  padding: 8px 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--main-bg);
  color: var(--primary-color);
  cursor: pointer;
}

.device-item strong {
  color: var(--text-primary);
}

.device-item p {
  margin: 4px 0 0;
  color: var(--text-secondary);
  font-size: 12px;
}

.device-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.device-actions > span {
  padding: 4px 8px;
  border-radius: 999px;
  background: var(--hover-bg);
  color: var(--text-secondary);
  font-size: 12px;
}

.device-actions > span.active {
  background: color-mix(in srgb, #22c55e 12%, var(--main-bg));
  color: #16a34a;
}

.revoke-button {
  padding: 7px 10px;
  border: 1px solid color-mix(in srgb, #ef4444 35%, var(--border-color));
  border-radius: 8px;
  background: var(--main-bg);
  color: #dc2626;
  cursor: pointer;
}

.state-line.success {
  color: #16a34a;
}

.state-line {
  margin: 14px 0 0;
  color: var(--text-secondary);
  font-size: 13px;
}

.state-line.error {
  color: #dc2626;
}

@media (max-width: 720px) {
  .pairing-panel {
    align-items: stretch;
    flex-direction: column;
    gap: 14px;
  }

  .pairing-actions {
    align-items: flex-start;
  }

  .pairing-actions > span {
    max-width: none;
    text-align: left;
  }
}
</style>
