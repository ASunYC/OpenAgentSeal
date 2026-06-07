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

        <label class="toggle-item">
          <div>
            <strong>{{ t('\u4e0a\u4e0b\u6587\u81ea\u52a8\u538b\u7f29', 'Auto context compaction') }}</strong>
            <p>{{ t('\u4e3b\u52a8\u5c06\u8f83\u957f\u4f1a\u8bdd\u4e34\u65f6\u538b\u7f29\u6210\u53ef\u68c0\u7d22\u6458\u8981\uff1b\u8d85\u8fc7\u5f53\u524d\u6a21\u578b\u4e0a\u9650\u65f6\u59cb\u7ec8\u4f1a\u81ea\u52a8\u4fdd\u62a4', 'Automatically compact long conversations into retrievable temporary summaries; overflow protection always runs when the current model limit would be exceeded') }}</p>
          </div>
          <input v-model="settings.autoContextCompaction" type="checkbox" />
        </label>
      </div>

      <label class="field compaction-limit">
        <span>{{ t('\u672a\u77e5\u6a21\u578b\u9ed8\u8ba4\u4e0a\u4e0b\u6587\uff08Token\uff09', 'Default context for unknown models (tokens)') }}</span>
        <input
          v-model.number="settings.contextCompactionTokenLimit"
          type="number"
          min="8000"
          max="500000"
          step="1000"
        />
        <small>{{ t('\u4ec5\u5728\u65e0\u6cd5\u8bc6\u522b\u6a21\u578b\u4e0a\u4e0b\u6587\u65f6\u4f7f\u7528\uff1b\u5df2\u8bc6\u522b\u6216\u624b\u52a8\u8bbe\u7f6e\u7684\u6a21\u578b\u4f18\u5148', 'Used only when model context cannot be detected; detected or manually configured model values take priority') }}</small>
      </label>
    </section>

    <section class="settings-card">
      <div class="card-heading">
        <div>
          <h4>{{ t('\u8054\u7f51\u641c\u7d22', 'Web Search') }}</h4>
          <span>{{ t('\u4f18\u5148\u4f7f\u7528 API \u641c\u7d22\u63d0\u4f9b\u5546\uff0c\u65e7\u641c\u7d22\u4f5c\u4e3a\u515c\u5e95', 'Prefer API-backed providers, with legacy search as fallback') }}</span>
        </div>
        <div class="card-actions">
          <button class="refresh-button" :disabled="webSearchLoading" @click="loadWebSearchConfig">
            {{ webSearchLoading ? t('\u52a0\u8f7d\u4e2d...', 'Loading...') : t('\u5237\u65b0', 'Refresh') }}
          </button>
          <button class="primary-button" :disabled="webSearchSaving" @click="saveWebSearchConfig">
            {{ webSearchSaving ? t('\u4fdd\u5b58\u4e2d...', 'Saving...') : t('\u4fdd\u5b58', 'Save') }}
          </button>
        </div>
      </div>

      <div v-if="webSearchError" class="state-line error">
        {{ webSearchError }}
      </div>

      <div class="toggle-list compact">
        <label class="toggle-item">
          <div>
            <strong>{{ t('\u542f\u7528\u8054\u7f51\u641c\u7d22', 'Enable web search') }}</strong>
            <p>{{ t('\u667a\u80fd\u4f53\u9700\u8981\u6700\u65b0\u4fe1\u606f\u3001\u65b0\u95fb\u539f\u5730\u5740\u6216\u7f51\u9875\u6765\u6e90\u65f6\u53ef\u4f7f\u7528', 'Allow agents to search when they need current information, news sources, or web citations') }}</p>
          </div>
          <input v-model="webSearchConfig.enabled" type="checkbox" />
        </label>
      </div>

      <div class="field-grid web-grid">
        <label class="field">
          <span>{{ t('\u641c\u7d22\u63d0\u4f9b\u5546', 'Search provider') }}</span>
          <select v-model="webSearchConfig.search_backend">
            <option v-for="provider in searchBackends" :key="provider.value" :value="provider.value">
              {{ provider.label }}
            </option>
          </select>
        </label>

        <label class="field">
          <span>{{ t('\u7f51\u9875\u8bfb\u53d6\u63d0\u4f9b\u5546', 'Page reader') }}</span>
          <select v-model="webSearchConfig.extract_backend">
            <option v-for="provider in extractBackends" :key="provider.value" :value="provider.value">
              {{ provider.label }}
            </option>
          </select>
        </label>

        <label class="field">
          <span>SearXNG URL</span>
          <input
            v-model="webSearchConfig.searxng_url"
            type="text"
            placeholder="http://localhost:8080"
          />
        </label>
      </div>

      <div class="api-key-grid">
        <label v-for="provider in apiKeyProviders" :key="provider.key" class="field">
          <span>{{ provider.label }} API Key</span>
          <input
            v-model="webSearchConfig.api_keys[provider.key]"
            type="password"
            :placeholder="t('\u7559\u7a7a\u8868\u793a\u4e0d\u4fee\u6539', 'Leave blank to keep unchanged')"
            autocomplete="off"
          />
        </label>
      </div>

      <div class="provider-status">
        <div class="status-column">
          <strong>{{ t('\u641c\u7d22\u72b6\u6001', 'Search status') }}</strong>
          <div class="status-list">
            <span
              v-for="provider in searchStatusList"
              :key="provider.name"
              class="provider-pill"
              :class="{ available: provider.available }"
            >
              {{ provider.display_name || provider.name }}
              <small>{{ provider.available ? t('\u53ef\u7528', 'Ready') : t('\u672a\u914d\u7f6e', 'Not configured') }}</small>
            </span>
          </div>
        </div>
        <div class="status-column">
          <strong>{{ t('\u8bfb\u53d6\u72b6\u6001', 'Reader status') }}</strong>
          <div class="status-list">
            <span
              v-for="provider in extractStatusList"
              :key="provider.name"
              class="provider-pill"
              :class="{ available: provider.available }"
            >
              {{ provider.display_name || provider.name }}
              <small>{{ provider.available ? t('\u53ef\u7528', 'Ready') : t('\u672a\u914d\u7f6e', 'Not configured') }}</small>
            </span>
          </div>
        </div>
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
import { computed, onMounted, reactive, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { api, webSearchApi, type WebSearchConfig, type WebSearchProviderStatus } from '@/api'
import { useSettingsStore } from '@/stores/settings'

const settingsStore = useSettingsStore()
const { settings } = storeToRefs(settingsStore)
const appVersion = ref('')
const releaseDate = ref('')
const versionLoading = ref(false)
const versionError = ref('')
const webSearchLoading = ref(false)
const webSearchSaving = ref(false)
const webSearchError = ref('')
const searchStatus = ref<Record<string, WebSearchProviderStatus>>({})
const extractStatus = ref<Record<string, WebSearchProviderStatus>>({})
const webSearchConfig = reactive<WebSearchConfig>({
  enabled: true,
  search_backend: 'auto',
  extract_backend: 'auto',
  searxng_url: '',
  api_keys: {
    serper: '',
    brave: '',
    tavily: '',
    jina: '',
    exa: '',
    firecrawl: '',
  },
})

const searchBackends = [
  { value: 'auto', label: 'Auto' },
  { value: 'firecrawl', label: 'Firecrawl' },
  { value: 'tavily', label: 'Tavily' },
  { value: 'exa', label: 'Exa' },
  { value: 'brave', label: 'Brave Search' },
  { value: 'serper', label: 'Serper' },
  { value: 'jina', label: 'Jina' },
  { value: 'searxng', label: 'SearXNG' },
  { value: 'ddgs', label: 'DuckDuckGo' },
  { value: 'duckduckgo_html', label: 'DuckDuckGo HTML' },
  { value: 'legacy_bing', label: 'Legacy Bing (fallback)' },
]

const extractBackends = [
  { value: 'auto', label: 'Auto' },
  { value: 'jina', label: 'Jina Reader' },
  { value: 'firecrawl', label: 'Firecrawl' },
  { value: 'built_in', label: 'Built-in reader' },
]

const apiKeyProviders = [
  { key: 'firecrawl', label: 'Firecrawl' },
  { key: 'tavily', label: 'Tavily' },
  { key: 'exa', label: 'Exa' },
  { key: 'brave', label: 'Brave' },
  { key: 'serper', label: 'Serper' },
  { key: 'jina', label: 'Jina' },
]

const searchStatusList = computed(() => providerStatusList(searchStatus.value))
const extractStatusList = computed(() => providerStatusList(extractStatus.value))

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

function providerStatusList(status: Record<string, WebSearchProviderStatus>) {
  return Object.values(status).sort((a, b) => {
    if (a.available !== b.available) return a.available ? -1 : 1
    return (a.display_name || a.name).localeCompare(b.display_name || b.name)
  })
}

function applyWebSearchConfig(config: WebSearchConfig) {
  webSearchConfig.enabled = config.enabled
  webSearchConfig.search_backend = config.search_backend || 'auto'
  webSearchConfig.extract_backend = config.extract_backend || 'auto'
  webSearchConfig.searxng_url = config.searxng_url || ''
  const keys = { ...webSearchConfig.api_keys, ...(config.api_keys || {}) }
  webSearchConfig.api_keys = keys
}

async function loadWebSearchConfig() {
  webSearchLoading.value = true
  webSearchError.value = ''
  try {
    const result = await webSearchApi.getConfig()
    if (!result.success) {
      throw new Error(result.error || 'Failed to load web search config')
    }
    applyWebSearchConfig(result.config)
    searchStatus.value = result.search_status || {}
    extractStatus.value = result.extract_status || {}
  } catch (error) {
    webSearchError.value = error instanceof Error ? error.message : String(error)
  } finally {
    webSearchLoading.value = false
  }
}

async function saveWebSearchConfig() {
  webSearchSaving.value = true
  webSearchError.value = ''
  try {
    const result = await webSearchApi.saveConfig({
      enabled: webSearchConfig.enabled,
      search_backend: webSearchConfig.search_backend,
      extract_backend: webSearchConfig.extract_backend,
      searxng_url: webSearchConfig.searxng_url,
      api_keys: { ...webSearchConfig.api_keys },
    })
    if (!result.success) {
      throw new Error(result.error || 'Failed to save web search config')
    }
    applyWebSearchConfig(result.config)
    searchStatus.value = result.search_status || {}
    extractStatus.value = result.extract_status || {}
  } catch (error) {
    webSearchError.value = error instanceof Error ? error.message : String(error)
  } finally {
    webSearchSaving.value = false
  }
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
  void loadWebSearchConfig()
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

.card-heading > div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
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

.card-actions {
  display: flex;
  flex-shrink: 0;
  flex-direction: row !important;
  align-items: center;
  gap: 8px !important;
}

.field-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.field-grid.web-grid {
  grid-template-columns: repeat(3, minmax(180px, 1fr));
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

.field small {
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.45;
}

.compaction-limit {
  max-width: 320px;
}

.compaction-limit input:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.field select,
.field input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: var(--hover-bg);
  color: var(--text-primary);
  font-size: 13px;
  box-sizing: border-box;
}

.field select:focus,
.field input:focus {
  outline: none;
  border-color: var(--primary-color);
}

.api-key-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.toggle-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.toggle-list.compact {
  gap: 0;
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

.primary-button {
  padding: 7px 14px;
  border: 1px solid var(--primary-color);
  border-radius: 8px;
  background: var(--primary-color);
  color: #ffffff;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
}

.refresh-button:hover:not(:disabled),
.primary-button:hover:not(:disabled) {
  transform: translateY(-1px);
}

.refresh-button:disabled,
.primary-button:disabled {
  opacity: 0.7;
  cursor: default;
}

.provider-status {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.status-column {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--hover-bg);
}

.status-column strong {
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 600;
}

.status-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.provider-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  padding: 6px 8px;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  background: var(--main-bg);
  color: var(--text-muted);
  font-size: 12px;
}

.provider-pill.available {
  border-color: color-mix(in srgb, var(--primary-color) 45%, var(--border-color));
  color: var(--primary-color);
  background: color-mix(in srgb, var(--primary-color) 8%, var(--main-bg));
}

.provider-pill small {
  color: inherit;
  opacity: 0.76;
  font-size: 11px;
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
  .api-key-grid,
  .about-grid,
  .provider-status {
    grid-template-columns: 1fr;
  }

  .card-heading {
    align-items: flex-start;
    flex-direction: column;
  }

  .card-actions {
    width: 100%;
    justify-content: flex-end;
  }
}
</style>
