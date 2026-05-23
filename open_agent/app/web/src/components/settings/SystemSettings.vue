<template>
  <div class="tab-content">
    <div class="content-header">
      <h3>{{ t('\u7cfb\u7edf\u8bbe\u7f6e', 'System Settings') }}</h3>
      <p>{{ t('\u8c03\u6574\u5916\u89c2\u3001\u8bed\u8a00\u548c\u6838\u5fc3\u884c\u4e3a', 'Adjust appearance, language, and core behavior') }}</p>
    </div>

    <section class="settings-card">
      <div class="card-heading">
        <h4>{{ t('\u5916\u89c2', 'Appearance') }}</h4>
        <span>{{ t('\u66f4\u6539\u4f1a\u81ea\u52a8\u4fdd\u5b58', 'Changes are saved automatically') }}</span>
      </div>

      <div class="field-grid">
        <label class="field">
          <span>{{ t('\u4e3b\u9898', 'Theme') }}</span>
          <select v-model="settings.theme">
            <option value="light">{{ t('\u6d45\u8272', 'Light') }}</option>
            <option value="dark">{{ t('\u6df1\u8272', 'Dark') }}</option>
            <option value="system">{{ t('\u7cfb\u7edf', 'System') }}</option>
          </select>
        </label>

        <label class="field">
          <span>{{ t('\u8bed\u8a00', 'Language') }}</span>
          <select v-model="settings.language">
            <option value="zh-CN">{{ t('\u4e2d\u6587', 'Chinese') }}</option>
            <option value="en-US">{{ t('\u82f1\u6587', 'English') }}</option>
          </select>
        </label>

        <label class="field">
          <span>{{ t('\u5b57\u4f53\u5927\u5c0f', 'Font Size') }}</span>
          <select v-model="settings.fontSize">
            <option value="small">{{ t('\u5c0f', 'Small') }}</option>
            <option value="medium">{{ t('\u4e2d', 'Medium') }}</option>
            <option value="large">{{ t('\u5927', 'Large') }}</option>
          </select>
        </label>
      </div>
    </section>

    <section class="settings-card">
      <div class="card-heading">
        <h4>{{ t('\u884c\u4e3a', 'Behavior') }}</h4>
        <span>{{ t('\u63a7\u5236\u751f\u6210\u548c\u4fdd\u5b58\u65b9\u5f0f', 'Control generation and persistence behavior') }}</span>
      </div>

      <div class="toggle-list">
        <label class="toggle-item">
          <div>
            <strong>{{ t('\u6d41\u5f0f\u8f93\u51fa', 'Streaming output') }}</strong>
            <p>{{ t('\u5728\u804a\u5929\u754c\u9762\u6e10\u8fdb\u663e\u793a\u52a9\u624b\u56de\u590d', 'Show assistant messages progressively in the chat UI') }}</p>
          </div>
          <input v-model="settings.streamResponse" type="checkbox" />
        </label>

        <label class="toggle-item">
          <div>
            <strong>{{ t('\u81ea\u52a8\u4fdd\u5b58', 'Auto Save') }}</strong>
            <p>{{ t('\u8bbe\u7f6e\u53d8\u66f4\u540e\u7acb\u5373\u4fdd\u5b58', 'Persist settings immediately after changes') }}</p>
          </div>
          <input v-model="settings.autoSave" type="checkbox" />
        </label>

        <label class="toggle-item">
          <div>
            <strong>{{ t('\u63a8\u7406\u6a21\u5f0f', 'Reasoning mode') }}</strong>
            <p>{{ t('\u5728\u652f\u6301\u65f6\u542f\u7528\u66f4\u6df1\u5165\u7684\u63a8\u7406\u8def\u5f84', 'Enable the more deliberate reasoning path where supported') }}</p>
          </div>
          <input v-model="settings.useCoT" type="checkbox" />
        </label>
      </div>
    </section>

    <section class="settings-card">
      <div class="card-heading">
        <h4>{{ t('\u5173\u4e8e', 'About') }}</h4>
        <button class="refresh-button" :disabled="versionLoading" @click="loadVersion">
          {{ versionLoading ? t('\u52a0\u8f7d\u4e2d...', 'Loading...') : t('\u5237\u65b0', 'Refresh') }}
        </button>
      </div>

      <div v-if="versionError" class="state-line error">
        {{ versionError }}
      </div>

      <div class="about-grid">
        <div class="about-item">
          <span class="label">{{ t('\u5e94\u7528\u7248\u672c', 'App Version') }}</span>
          <strong>{{ appVersion || '--' }}</strong>
        </div>
        <div class="about-item">
          <span class="label">{{ t('\u53d1\u5e03\u65e5\u671f', 'Release Date') }}</span>
          <strong>{{ releaseDate || '--' }}</strong>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { api } from '@/api'
import { useSettingsStore } from '@/stores/settings'

const settingsStore = useSettingsStore()
const { settings } = storeToRefs(settingsStore)
const appVersion = ref('')
const releaseDate = ref('')
const versionLoading = ref(false)
const versionError = ref('')

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

async function loadVersion() {
  versionLoading.value = true
  versionError.value = ''
  try {
    const result = await api.getVersion()
    if (!result.success) {
      throw new Error(result.error || 'Failed to load version')
    }
    appVersion.value = result.version || ''
    releaseDate.value = result.release_date || ''
  } catch (error) {
    versionError.value = error instanceof Error ? error.message : String(error)
  } finally {
    versionLoading.value = false
  }
}

onMounted(() => {
  void loadVersion()
})
</script>

<style scoped>
.tab-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.content-header h3 {
  margin: 0 0 4px;
  color: var(--text-primary);
  font-size: 16px;
  font-weight: 600;
}

.content-header p {
  margin: 0;
  color: var(--text-muted);
  font-size: 13px;
}

.settings-card {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px;
  border: 1px solid var(--border-color);
  border-radius: 14px;
  background: var(--main-bg);
}

.card-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.card-heading h4 {
  margin: 0;
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 600;
}

.card-heading span {
  color: var(--text-muted);
  font-size: 12px;
}

.field-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.field span {
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 500;
}

.field select {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: var(--hover-bg);
  color: var(--text-primary);
  font-size: 13px;
}

.field select:focus {
  outline: none;
  border-color: var(--primary-color);
}

.toggle-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.toggle-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 0;
  border-bottom: 1px solid rgba(120, 130, 160, 0.16);
}

.toggle-item:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.toggle-item strong {
  display: block;
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 600;
}

.toggle-item p {
  margin: 4px 0 0;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.45;
}

.toggle-item input {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
  accent-color: var(--primary-color);
}

.about-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.about-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 14px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--hover-bg);
}

.label {
  color: var(--text-muted);
  font-size: 12px;
}

.about-item strong {
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 700;
}

.refresh-button {
  padding: 7px 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--hover-bg);
  color: var(--text-primary);
  cursor: pointer;
  font-size: 12px;
}

.refresh-button:disabled {
  opacity: 0.7;
  cursor: default;
}

.state-line {
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--hover-bg);
  color: var(--text-muted);
  font-size: 12px;
}

.state-line.error {
  color: #ef4444;
}

@media (max-width: 1100px) {
  .field-grid,
  .about-grid {
    grid-template-columns: 1fr;
  }
}
</style>
