<template>
  <div class="tab-content">
    <div class="content-header">
      <h3>{{ t('插件管理', 'Plugin Management') }}</h3>
      <p>{{ t('安装、启用和管理插件包', 'Install, enable, and manage plugin bundles') }}</p>
      <span class="count-pill">{{ t('插件', 'Plugins') }} {{ pluginCount }}</span>
    </div>

    <div class="settings-search">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="11" cy="11" r="8"/>
        <path d="m21 21-4.3-4.3"/>
      </svg>
      <input v-model="searchQuery" type="search" :placeholder="t('搜索插件名称、市场、描述或状态', 'Search plugins by name, marketplace, description, or status')" />
      <button v-if="searchQuery" type="button" @click="searchQuery = ''">{{ t('清除', 'Clear') }}</button>
    </div>

    <section class="marketplace-bar">
      <div class="marketplace-input">
        <input v-model="marketplaceSource" type="text" :placeholder="t('本地路径、Git URL 或 owner/repo', 'Local path, Git URL, or owner/repo')" @keydown.enter="addMarketplace" />
        <button class="btn-primary" :disabled="addingMarketplace || !marketplaceSource.trim()" @click="addMarketplace">
          {{ addingMarketplace ? t('添加中...', 'Adding...') : t('添加市场', 'Add Marketplace') }}
        </button>
      </div>
      <div class="marketplace-actions">
        <button class="btn-secondary" @click="loadAll">{{ t('刷新', 'Refresh') }}</button>
        <button class="btn-secondary" :disabled="upgrading" @click="upgradeMarketplaces">{{ upgrading ? t('刷新中...', 'Refreshing...') : t('刷新 Git 市场', 'Refresh Git Marketplaces') }}</button>
      </div>
    </section>

    <div v-if="loading" class="state-card">{{ t('加载中...', 'Loading...') }}</div>
    <div v-else-if="error" class="state-card error">{{ error }}</div>
    <div v-else-if="marketplaces.length === 0" class="empty-state">
      <span>{{ t('还没有插件市场。添加本地市场路径或 Git 地址后即可安装插件。', 'No marketplaces yet. Add a local marketplace path or Git URL to install plugins.') }}</span>
    </div>

    <div v-else-if="filteredMarketplaces.length === 0" class="empty-state">
      <span>{{ t('没有匹配的插件', 'No matching plugins') }}</span>
    </div>

    <div v-else class="marketplace-list">
      <section v-for="marketplace in filteredMarketplaces" :key="marketplace.name" class="marketplace-card">
        <header class="marketplace-header">
          <div>
            <h4>{{ marketplace.interface?.displayName || marketplace.interface?.display_name || marketplace.name }}</h4>
            <p>{{ marketplace.path }}</p>
          </div>
          <button class="btn-danger" @click="removeMarketplace(marketplace.name)">{{ t('移除市场', 'Remove') }}</button>
        </header>

        <div class="plugins-grid">
          <article v-for="plugin in marketplace.plugins" :key="plugin.id" class="plugin-card" :class="{ installed: plugin.installed, disabled: plugin.installed && !plugin.enabled }">
            <div class="plugin-main">
              <div class="plugin-title">
                <h5>{{ displayName(plugin) }}</h5>
                <span>{{ plugin.name }}@{{ plugin.marketplace_name }}</span>
              </div>
              <p>{{ plugin.interface?.shortDescription || plugin.interface?.short_description || plugin.interface?.longDescription || plugin.interface?.long_description || t('暂无描述', 'No description') }}</p>
              <div class="plugin-meta">
                <span v-if="plugin.local_version">{{ plugin.local_version }}</span>
                <span v-if="plugin.installed">{{ plugin.enabled ? t('已启用', 'Enabled') : t('已禁用', 'Disabled') }}</span>
                <span v-else>{{ t('未安装', 'Not installed') }}</span>
              </div>
            </div>
            <div class="plugin-actions">
              <button class="btn-secondary" @click="openDetail(plugin)">{{ t('详情', 'Details') }}</button>
              <button v-if="!plugin.installed" class="btn-primary" :disabled="busyPlugin === plugin.id" @click="installPlugin(plugin)">
                {{ busyPlugin === plugin.id ? t('安装中...', 'Installing...') : t('安装', 'Install') }}
              </button>
              <button v-else class="btn-secondary" :disabled="busyPlugin === plugin.id" @click="togglePlugin(plugin)">
                {{ plugin.enabled ? t('禁用', 'Disable') : t('启用', 'Enable') }}
              </button>
              <button v-if="plugin.installed" class="btn-danger" :disabled="busyPlugin === plugin.id" @click="uninstallPlugin(plugin)">{{ t('卸载', 'Uninstall') }}</button>
            </div>
          </article>
        </div>
      </section>
    </div>

    <div v-if="selectedDetail" class="detail-backdrop" @click.self="selectedDetail = null">
      <aside class="detail-panel">
        <header class="detail-header">
          <div>
            <h4>{{ displayName(selectedDetail.summary) }}</h4>
            <p>{{ selectedDetail.summary.id }}</p>
          </div>
          <button class="icon-button" @click="selectedDetail = null">×</button>
        </header>

        <p class="detail-description">{{ selectedDetail.description || selectedDetail.summary.interface?.longDescription || selectedDetail.summary.interface?.long_description || t('暂无描述', 'No description') }}</p>

        <div class="detail-section">
          <h5>{{ t('技能', 'Skills') }} {{ selectedDetail.skills.length }}</h5>
          <div v-if="selectedDetail.skills.length === 0" class="muted">{{ t('无插件技能', 'No plugin skills') }}</div>
          <div v-for="skill in selectedDetail.skills" :key="skill.path || skill.name" class="detail-row">
            <span>{{ skill.name }}</span>
            <small>{{ skill.enabled ? t('启用', 'Enabled') : t('禁用', 'Disabled') }}</small>
          </div>
        </div>

        <div class="detail-section">
          <h5>MCP {{ selectedDetail.mcp_servers.length }}</h5>
          <div v-if="selectedDetail.mcp_servers.length === 0" class="muted">{{ t('无插件 MCP', 'No plugin MCP servers') }}</div>
          <div v-for="server in selectedDetail.mcp_servers" :key="server.name" class="detail-row">
            <span>{{ server.name }}</span>
            <small>{{ server.enabled ? t('启用', 'Enabled') : t('禁用', 'Disabled') }}</small>
          </div>
        </div>

        <div class="detail-section">
          <h5>{{ t('声明能力', 'Declared Capabilities') }}</h5>
          <div class="capability-grid">
            <span>{{ t('Apps', 'Apps') }}: {{ countUnknown(selectedDetail.apps) }}</span>
            <span>{{ t('Hooks', 'Hooks') }}: {{ countUnknown(selectedDetail.hooks) }}</span>
          </div>
          <p class="muted">{{ t('Apps 和 Hooks 第一版仅展示声明，暂未接入运行时。', 'Apps and hooks are displayed as metadata in this version.') }}</p>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { pluginsApi, type PluginDetail, type PluginMarketplace, type PluginSummary } from '@/api'
import { useSettingsStore } from '@/stores/settings'

const settingsStore = useSettingsStore()
const marketplaces = ref<PluginMarketplace[]>([])
const selectedDetail = ref<PluginDetail | null>(null)
const marketplaceSource = ref('')
const loading = ref(false)
const addingMarketplace = ref(false)
const upgrading = ref(false)
const busyPlugin = ref<string | null>(null)
const error = ref<string | null>(null)
const searchQuery = ref('')

const pluginCount = computed(() => marketplaces.value.reduce((count, marketplace) => count + marketplace.plugins.length, 0))
const filteredMarketplaces = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) return marketplaces.value
  return marketplaces.value
    .map((marketplace) => {
      const marketplaceName = marketplace.interface?.displayName || marketplace.interface?.display_name || marketplace.name
      const marketplaceHaystack = [marketplace.name, marketplaceName, marketplace.path].filter(Boolean).join(' ').toLowerCase()
      if (marketplaceHaystack.includes(query)) return marketplace
      const plugins = marketplace.plugins.filter((plugin) => pluginMatchesQuery(plugin, query))
      return { ...marketplace, plugins }
    })
    .filter((marketplace) => marketplace.plugins.length > 0)
})

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

function displayName(plugin: PluginSummary) {
  return plugin.interface?.displayName || plugin.interface?.display_name || plugin.name
}

function pluginMatchesQuery(plugin: PluginSummary, query: string) {
  return [
    plugin.id,
    plugin.name,
    plugin.marketplace_name,
    displayName(plugin),
    plugin.local_version,
    plugin.install_policy,
    plugin.auth_policy,
    plugin.interface?.shortDescription,
    plugin.interface?.short_description,
    plugin.interface?.longDescription,
    plugin.interface?.long_description,
    plugin.interface?.developerName,
    plugin.interface?.developer_name,
    plugin.interface?.category,
    ...(plugin.interface?.capabilities || []),
    ...(plugin.keywords || []),
    plugin.installed ? 'installed 已安装' : 'not installed 未安装',
    plugin.enabled ? 'enabled 已启用' : 'disabled 已禁用',
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
    .includes(query)
}

function countUnknown(value: unknown) {
  if (Array.isArray(value)) return value.length
  if (value && typeof value === 'object') return Object.keys(value as Record<string, unknown>).length
  return 0
}

async function loadAll() {
  loading.value = true
  error.value = null
  try {
    const response = await pluginsApi.list()
    marketplaces.value = response.marketplaces || []
    if (!response.success && response.marketplace_load_errors?.length) {
      error.value = response.marketplace_load_errors.map((item) => item.message).join('\n')
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function addMarketplace() {
  const source = marketplaceSource.value.trim()
  if (!source) return
  addingMarketplace.value = true
  try {
    const result = await pluginsApi.addMarketplace(source)
    if (!result.success) throw new Error(result.error || 'Failed to add marketplace')
    marketplaceSource.value = ''
    await loadAll()
  } catch (e) {
    alert(e instanceof Error ? e.message : String(e))
  } finally {
    addingMarketplace.value = false
  }
}

async function removeMarketplace(name: string) {
  if (!confirm(t('确定移除这个插件市场吗？已安装插件不会被自动卸载。', 'Remove this marketplace? Installed plugins are not automatically uninstalled.'))) return
  try {
    const result = await pluginsApi.removeMarketplace(name)
    if (!result.success) throw new Error(result.error || 'Failed to remove marketplace')
    await loadAll()
  } catch (e) {
    alert(e instanceof Error ? e.message : String(e))
  }
}

async function upgradeMarketplaces() {
  upgrading.value = true
  try {
    const result = await pluginsApi.upgradeMarketplaces()
    if (!result.success) throw new Error(result.error || 'Failed to refresh marketplaces')
    await loadAll()
  } catch (e) {
    alert(e instanceof Error ? e.message : String(e))
  } finally {
    upgrading.value = false
  }
}

async function installPlugin(plugin: PluginSummary) {
  busyPlugin.value = plugin.id
  try {
    const result = await pluginsApi.install(plugin.name, plugin.marketplace_name)
    if (!result.success) throw new Error(result.error || 'Failed to install plugin')
    await loadAll()
  } catch (e) {
    alert(e instanceof Error ? e.message : String(e))
  } finally {
    busyPlugin.value = null
  }
}

async function uninstallPlugin(plugin: PluginSummary) {
  if (!confirm(t('确定卸载这个插件吗？', 'Uninstall this plugin?'))) return
  busyPlugin.value = plugin.id
  try {
    const result = await pluginsApi.uninstall(plugin.id)
    if (!result.success) throw new Error(result.error || 'Failed to uninstall plugin')
    if (selectedDetail.value?.summary.id === plugin.id) selectedDetail.value = null
    await loadAll()
  } catch (e) {
    alert(e instanceof Error ? e.message : String(e))
  } finally {
    busyPlugin.value = null
  }
}

async function togglePlugin(plugin: PluginSummary) {
  busyPlugin.value = plugin.id
  try {
    const result = await pluginsApi.setEnabled(plugin.id, !plugin.enabled)
    if (!result.success) throw new Error(result.error || 'Failed to update plugin')
    await loadAll()
  } catch (e) {
    alert(e instanceof Error ? e.message : String(e))
  } finally {
    busyPlugin.value = null
  }
}

async function openDetail(plugin: PluginSummary) {
  try {
    const response = await pluginsApi.read(plugin.id)
    if (!response.success) throw new Error(response.error || 'Failed to read plugin')
    selectedDetail.value = response.plugin
  } catch (e) {
    alert(e instanceof Error ? e.message : String(e))
  }
}

onMounted(() => {
  void loadAll()
})
</script>

<style scoped>
.tab-content {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.content-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 4px 16px;
  align-items: start;
}

.content-header h3,
.marketplace-header h4,
.plugin-title h5,
.detail-header h4,
.detail-section h5 {
  margin: 0;
  color: var(--text-primary);
}

.content-header h3 {
  font-size: 16px;
  font-weight: 600;
}

.content-header p,
.marketplace-header p,
.plugin-title span,
.plugin-card p,
.detail-header p,
.muted,
.detail-description {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
}

.count-pill {
  grid-column: 2;
  grid-row: 1 / span 2;
  padding: 5px 10px;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  background: var(--hover-bg);
  color: var(--text-secondary);
  font-size: 12px;
  white-space: nowrap;
}

.settings-search {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--main-bg);
}

.settings-search svg {
  width: 16px;
  height: 16px;
  color: var(--text-muted);
  flex: 0 0 auto;
}

.settings-search input {
  flex: 1;
  min-width: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--text-primary);
  font-size: 13px;
}

.settings-search button {
  flex: 0 0 auto;
  border: 0;
  background: transparent;
  color: var(--primary-color);
  cursor: pointer;
  font-size: 12px;
}

.marketplace-bar,
.marketplace-card,
.plugin-card,
.state-card,
.empty-state,
.detail-panel {
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--main-bg);
}

.marketplace-bar {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
}

.marketplace-input,
.marketplace-actions {
  display: flex;
  gap: 8px;
}

.marketplace-input input {
  flex: 1;
  min-width: 0;
  padding: 9px 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--input-bg, var(--main-bg));
  color: var(--text-primary);
}

.state-card,
.empty-state {
  padding: 28px;
  color: var(--text-muted);
  text-align: center;
}

.state-card.error {
  color: #ef4444;
}

.marketplace-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.marketplace-card {
  padding: 14px;
}

.marketplace-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.marketplace-header h4 {
  font-size: 14px;
}

.marketplace-header p {
  margin-top: 4px;
  max-width: 560px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.plugins-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 10px;
}

.plugin-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px;
}

.plugin-card.installed {
  border-color: color-mix(in srgb, var(--primary-color) 55%, var(--border-color));
}

.plugin-card.disabled {
  opacity: 0.72;
}

.plugin-main {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.plugin-title h5 {
  font-size: 14px;
  overflow-wrap: anywhere;
}

.plugin-card p {
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.plugin-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.plugin-meta span,
.capability-grid span {
  padding: 3px 8px;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  background: var(--hover-bg);
  color: var(--text-secondary);
  font-size: 11px;
}

.plugin-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.btn-primary,
.btn-secondary,
.btn-danger,
.icon-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 8px 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--main-bg);
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 13px;
}

.btn-primary {
  border-color: var(--primary-color);
  background: var(--primary-color);
  color: #fff;
}

.btn-danger {
  color: #ef4444;
}

.btn-primary:disabled,
.btn-secondary:disabled,
.btn-danger:disabled {
  opacity: 0.6;
  cursor: wait;
}

.detail-backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  justify-content: flex-end;
  background: rgba(0, 0, 0, 0.24);
}

.detail-panel {
  width: min(520px, 92vw);
  height: 100%;
  padding: 18px;
  overflow: auto;
  border-radius: 0;
  box-shadow: -20px 0 50px rgba(0, 0, 0, 0.18);
}

.detail-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.icon-button {
  width: 34px;
  height: 34px;
  padding: 0;
  font-size: 22px;
}

.detail-description {
  margin-bottom: 16px;
  line-height: 1.55;
}

.detail-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 14px 0;
  border-top: 1px solid var(--border-color);
}

.detail-section h5 {
  font-size: 13px;
}

.detail-row {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 13px;
}

.detail-row span {
  min-width: 0;
  overflow-wrap: anywhere;
}

.detail-row small {
  color: var(--text-muted);
  white-space: nowrap;
}

.capability-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

@media (max-width: 720px) {
  .marketplace-input,
  .marketplace-actions,
  .marketplace-header {
    flex-direction: column;
  }
}
</style>
