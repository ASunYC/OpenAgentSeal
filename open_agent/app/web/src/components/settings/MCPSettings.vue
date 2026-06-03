<template>
  <div class="tab-content">
    <div class="content-header">
      <h3>{{ t('MCP 设置', 'MCP Settings') }}</h3>
      <p>{{ t('管理智能体最终可用的 MCP 服务', 'Manage MCP servers available to the agent') }}</p>
      <span class="count-pill">MCP {{ mcpServers.length }}</span>
    </div>

    <div v-if="configPath" class="config-path">
      <span>{{ t('用户配置文件', 'User config file') }}</span>
      <code>{{ configPath }}</code>
    </div>

    <div v-if="loading" class="state-card">
      {{ t('加载中...', 'Loading...') }}
    </div>

    <div v-else-if="error" class="state-card error">
      {{ t('加载失败：', 'Failed to load: ') }}{{ error }}
    </div>

    <div v-else class="mcp-list">
      <div v-for="server in mcpServers" :key="serverKey(server)" class="mcp-card" :class="{ readonly: server.readonly }">
        <div class="mcp-header">
          <div class="mcp-info">
            <h4>{{ server.name }}</h4>
            <div class="mcp-meta">
              <span class="mcp-type">{{ server.type }}</span>
              <span class="source-pill">{{ sourceLabel(server) }}</span>
            </div>
          </div>
          <button class="mcp-status" :class="{ connected: !server.disabled }" :disabled="savingServer === serverKey(server)" @click="toggleServer(server)">
            {{ server.disabled ? t('已禁用', 'Disabled') : t('已启用', 'Enabled') }}
          </button>
        </div>

        <div class="mcp-fields">
          <label>
            <span>{{ t('名称', 'Name') }}</span>
            <input v-model="server.name" type="text" :disabled="server.readonly" />
          </label>
          <label>
            <span>{{ t('类型', 'Type') }}</span>
            <select v-model="server.type" :disabled="server.readonly">
              <option value="stdio">stdio</option>
              <option value="streamable_http">streamable_http</option>
              <option value="http">http</option>
              <option value="sse">sse</option>
            </select>
          </label>
          <label v-if="server.type === 'stdio'">
            <span>{{ t('命令', 'Command') }}</span>
            <input v-model="server.command" type="text" placeholder="npx" :disabled="server.readonly" />
          </label>
          <label v-else>
            <span>URL</span>
            <input v-model="server.url" type="text" placeholder="https://example.com/mcp" :disabled="server.readonly" />
          </label>
          <label>
            <span>{{ t('参数', 'Args') }}</span>
            <textarea v-model="server.argsText" rows="3" placeholder="-y&#10;@modelcontextprotocol/server-memory" :disabled="server.readonly"></textarea>
          </label>
          <label class="wide">
            <span>{{ t('环境变量', 'Env') }}</span>
            <textarea v-model="server.envText" rows="2" placeholder="KEY=value" :disabled="server.readonly"></textarea>
          </label>
        </div>

        <div class="mcp-actions">
          <button class="btn-secondary" @click="validateServer(server)">{{ t('检查', 'Check') }}</button>
          <button v-if="server.readonly" class="btn-secondary" @click="copyPluginServer(server)">{{ t('复制为用户 MCP', 'Copy as user MCP') }}</button>
          <button v-else class="btn-danger" @click="deleteServer(server)">{{ t('删除', 'Delete') }}</button>
        </div>
      </div>

      <button class="add-mcp" @click="addServer">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="12" y1="5" x2="12" y2="19" />
          <line x1="5" y1="12" x2="19" y2="12" />
        </svg>
        <span>{{ t('添加 MCP 服务器', 'Add MCP Server') }}</span>
      </button>

      <div class="footer-actions">
        <button class="btn-secondary" @click="loadConfig">{{ t('重新加载', 'Reload') }}</button>
        <button class="btn-primary" :disabled="saving" @click="saveConfig">
          {{ saving ? t('保存中...', 'Saving...') : t('保存用户 MCP 配置', 'Save User MCP Config') }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { mcpApi, type MCPServerConfig } from '@/api'
import { useSettingsStore } from '@/stores/settings'

interface EditableMCPServer extends MCPServerConfig {
  argsText: string
  envText: string
}

const settingsStore = useSettingsStore()
const mcpServers = ref<EditableMCPServer[]>([])
const configPath = ref('')
const loading = ref(false)
const saving = ref(false)
const savingServer = ref<string | null>(null)
const error = ref<string | null>(null)

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

function serverKey(server: EditableMCPServer) {
  return `${server.source || 'user'}:${server.plugin_id || ''}:${server.name}`
}

function sourceLabel(server: EditableMCPServer) {
  return server.source === 'plugin'
    ? `${t('插件', 'Plugin')}: ${server.plugin_id || '-'}`
    : t('用户配置', 'User config')
}

function toEnvText(env?: Record<string, string>) {
  return Object.entries(env ?? {}).map(([key, value]) => `${key}=${value}`).join('\n')
}

function parseEnv(text: string): Record<string, string> {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .reduce<Record<string, string>>((env, line) => {
      const index = line.indexOf('=')
      if (index > 0) {
        env[line.slice(0, index).trim()] = line.slice(index + 1).trim()
      }
      return env
    }, {})
}

function toEditable(server: MCPServerConfig): EditableMCPServer {
  return {
    ...server,
    original_name: server.original_name || server.name,
    type: server.type || 'stdio',
    args: server.args ?? [],
    env: server.env ?? {},
    disabled: server.disabled ?? false,
    source: server.source || 'user',
    readonly: server.readonly ?? server.source === 'plugin',
    argsText: (server.args ?? []).join('\n'),
    envText: toEnvText(server.env),
  }
}

function toPayload(server: EditableMCPServer): MCPServerConfig {
  return {
    ...server,
    name: server.name.trim(),
    original_name: server.original_name || server.name.trim(),
    type: server.type || 'stdio',
    command: server.command?.trim(),
    url: server.url?.trim(),
    args: server.argsText
      .split('\n')
      .map((arg) => arg.trim())
      .filter(Boolean),
    env: parseEnv(server.envText),
    disabled: server.disabled ?? false,
  }
}

async function loadConfig() {
  loading.value = true
  error.value = null
  try {
    const data = await mcpApi.getConfig()
    if (!data.success) {
      throw new Error(data.error || 'Failed to load MCP config')
    }
    configPath.value = data.path
    mcpServers.value = data.servers.map(toEditable)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function toggleServer(server: EditableMCPServer) {
  const nextDisabled = !server.disabled
  if (server.readonly && server.plugin_id) {
    savingServer.value = serverKey(server)
    try {
      const result = await mcpApi.setPluginServerEnabled(server.plugin_id, server.name, !nextDisabled)
      if (!result.success) {
        throw new Error(result.error || 'Failed to update plugin MCP server')
      }
      server.disabled = nextDisabled
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e))
    } finally {
      savingServer.value = null
    }
    return
  }
  server.disabled = nextDisabled
}

function validateServer(server: EditableMCPServer) {
  const payload = toPayload(server)
  if (!payload.name) {
    alert(t('名称不能为空。', 'Name is required.'))
    return
  }
  if (payload.type === 'stdio' && !payload.command) {
    alert(t('stdio 类型需要命令。', 'stdio servers require a command.'))
    return
  }
  if (payload.type !== 'stdio' && !payload.url) {
    alert(t('HTTP/SSE 类型需要 URL。', 'HTTP/SSE servers require a URL.'))
    return
  }
  alert(t('配置格式看起来正常。', 'The config shape looks valid.'))
}

function deleteServer(server: EditableMCPServer) {
  if (confirm(t('确定删除这个 MCP 服务器吗？', 'Delete this MCP server?'))) {
    mcpServers.value = mcpServers.value.filter((item) => item !== server)
  }
}

function copyPluginServer(server: EditableMCPServer) {
  const copy = toEditable({
    ...toPayload(server),
    name: `${server.name}-copy`,
    original_name: `${server.name}-copy`,
    source: 'user',
    plugin_id: null,
    readonly: false,
    disabled: true,
  })
  mcpServers.value.push(copy)
}

function addServer() {
  mcpServers.value.push(toEditable({
    name: `server-${mcpServers.value.length + 1}`,
    type: 'stdio',
    command: '',
    args: [],
    env: {},
    disabled: true,
    source: 'user',
  }))
}

async function saveConfig() {
  const servers = mcpServers.value
    .filter((server) => !server.readonly && server.source !== 'plugin')
    .map(toPayload)
    .filter((server) => server.name)
  const names = new Set<string>()
  for (const server of servers) {
    if (names.has(server.name)) {
      alert(t('MCP 服务器名称不能重复。', 'MCP server names must be unique.'))
      return
    }
    names.add(server.name)
  }

  saving.value = true
  try {
    const result = await mcpApi.saveConfig(servers)
    if (!result.success) {
      alert(result.error || t('保存失败。', 'Save failed.'))
      return
    }
    await loadConfig()
    alert(t('MCP 配置已保存。重启或重新加载会话后生效。', 'MCP config saved. Restart or reload the session to apply it.'))
  } catch (e) {
    alert(e instanceof Error ? e.message : String(e))
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  void loadConfig()
})
</script>

<style scoped>
.tab-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.content-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 4px 16px;
  align-items: start;
  margin-bottom: 8px;
}

.content-header h3 {
  margin: 0 0 4px;
  color: var(--text-primary);
  font-size: 16px;
  font-weight: 600;
}

.content-header p {
  grid-column: 1;
  margin: 0;
  color: var(--text-muted);
  font-size: 13px;
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
  line-height: 1.2;
  white-space: nowrap;
}

.config-path,
.state-card {
  padding: 12px;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: var(--main-bg);
  color: var(--text-secondary);
  font-size: 12px;
}

.config-path {
  display: flex;
  gap: 8px;
  align-items: center;
  min-width: 0;
}

.config-path code {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.state-card.error {
  color: #ef4444;
}

.mcp-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.mcp-card {
  padding: 16px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--main-bg);
}

.mcp-card.readonly {
  background: color-mix(in srgb, var(--main-bg) 92%, var(--primary-color) 8%);
}

.mcp-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.mcp-info {
  min-width: 0;
}

.mcp-info h4 {
  margin: 0 0 6px;
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.mcp-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.mcp-type,
.source-pill {
  display: inline-flex;
  padding: 3px 8px;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  background: var(--hover-bg);
  color: var(--text-secondary);
  font-size: 11px;
  line-height: 1.2;
}

.mcp-status {
  align-self: flex-start;
  padding: 6px 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--hover-bg);
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 12px;
}

.mcp-status.connected {
  border-color: var(--primary-color);
  background: var(--primary-color);
  color: #fff;
}

.mcp-status:disabled {
  opacity: 0.6;
  cursor: wait;
}

.mcp-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.mcp-fields label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: var(--text-secondary);
  font-size: 12px;
}

.mcp-fields label.wide {
  grid-column: 1 / -1;
}

.mcp-fields input,
.mcp-fields select,
.mcp-fields textarea {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--input-bg, var(--main-bg));
  color: var(--text-primary);
  font: inherit;
  resize: vertical;
}

.mcp-fields input:disabled,
.mcp-fields select:disabled,
.mcp-fields textarea:disabled {
  opacity: 0.75;
  cursor: not-allowed;
}

.mcp-actions,
.footer-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 12px;
}

.add-mcp,
.btn-secondary,
.btn-danger,
.btn-primary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--main-bg);
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 13px;
}

.add-mcp {
  width: 100%;
  border-style: dashed;
}

.add-mcp svg {
  width: 16px;
  height: 16px;
}

.btn-primary {
  border-color: var(--primary-color);
  background: var(--primary-color);
  color: #fff;
}

.btn-danger {
  color: #ef4444;
}

@media (max-width: 720px) {
  .mcp-fields {
    grid-template-columns: 1fr;
  }
}
</style>
