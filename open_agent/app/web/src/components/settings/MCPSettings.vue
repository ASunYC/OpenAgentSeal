<template>
  <div class="tab-content">
    <div class="content-header">
      <h3>{{ t('MCP 设置', 'MCP Settings') }}</h3>
      <p>{{ t('管理 MCP 服务器配置', 'Manage MCP server configurations') }}</p>
      <span class="count-pill">MCP {{ mcpServers.length }}</span>
    </div>

    <div v-if="configPath" class="config-path">
      <span>{{ t('配置文件', 'Config file') }}</span>
      <code>{{ configPath }}</code>
    </div>

    <div v-if="loading" class="state-card">
      {{ t('加载中...', 'Loading...') }}
    </div>

    <div v-else-if="error" class="state-card error">
      {{ t('加载失败：', 'Failed to load: ') }}{{ error }}
    </div>

    <div v-else class="mcp-list">
      <div v-for="server in mcpServers" :key="server.name" class="mcp-card">
        <div class="mcp-header">
          <div class="mcp-info">
            <h4>{{ server.name }}</h4>
            <span class="mcp-type">{{ server.type }}</span>
          </div>
          <button class="mcp-status" :class="{ connected: !server.disabled }" @click="toggleServer(server)">
            {{ server.disabled ? t('已禁用', 'Disabled') : t('已启用', 'Enabled') }}
          </button>
        </div>

        <div class="mcp-fields">
          <label>
            <span>{{ t('名称', 'Name') }}</span>
            <input v-model="server.name" type="text" />
          </label>
          <label>
            <span>{{ t('类型', 'Type') }}</span>
            <select v-model="server.type">
              <option value="stdio">stdio</option>
              <option value="streamable_http">streamable_http</option>
              <option value="http">http</option>
              <option value="sse">sse</option>
            </select>
          </label>
          <label v-if="server.type === 'stdio'">
            <span>{{ t('命令', 'Command') }}</span>
            <input v-model="server.command" type="text" placeholder="npx" />
          </label>
          <label v-else>
            <span>URL</span>
            <input v-model="server.url" type="text" placeholder="https://example.com/mcp" />
          </label>
          <label>
            <span>{{ t('参数', 'Args') }}</span>
            <textarea v-model="server.argsText" rows="3" placeholder="-y&#10;@modelcontextprotocol/server-memory"></textarea>
          </label>
          <label class="wide">
            <span>{{ t('环境变量', 'Env') }}</span>
            <textarea v-model="server.envText" rows="2" placeholder="KEY=value"></textarea>
          </label>
        </div>

        <div class="mcp-actions">
          <button class="btn-secondary" @click="validateServer(server)">{{ t('检查', 'Check') }}</button>
          <button class="btn-danger" @click="deleteServer(server)">{{ t('删除', 'Delete') }}</button>
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
          {{ saving ? t('保存中...', 'Saving...') : t('保存配置', 'Save Config') }}
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
const error = ref<string | null>(null)

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
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

function toggleServer(server: EditableMCPServer) {
  server.disabled = !server.disabled
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

function addServer() {
  mcpServers.value.push(toEditable({
    name: `server-${mcpServers.value.length + 1}`,
    type: 'stdio',
    command: '',
    args: [],
    env: {},
    disabled: true,
  }))
}

async function saveConfig() {
  const servers = mcpServers.value.map(toPayload).filter((server) => server.name)
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
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 12px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--main-bg);
  color: var(--text-muted);
  font-size: 13px;
}

.config-path code {
  min-width: 0;
  color: var(--text-primary);
  word-break: break-all;
}

.state-card {
  justify-content: center;
  min-height: 120px;
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

.mcp-header,
.mcp-actions,
.footer-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.mcp-header {
  margin-bottom: 14px;
}

.mcp-info {
  display: flex;
  align-items: center;
  gap: 12px;
}

.mcp-info h4 {
  margin: 0;
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 600;
}

.mcp-type {
  padding: 2px 8px;
  border-radius: 6px;
  background: var(--hover-bg);
  color: var(--text-muted);
  font-size: 11px;
}

.mcp-status {
  padding: 5px 10px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--hover-bg);
  color: var(--text-muted);
  cursor: pointer;
  font-size: 12px;
}

.mcp-status.connected {
  border-color: #10b981;
  background: #10b981;
  color: #fff;
}

.mcp-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 14px;
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
  min-width: 0;
  padding: 9px 10px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--input-bg);
  color: var(--text-primary);
  font: inherit;
  resize: vertical;
}

.btn-secondary,
.btn-danger,
.btn-primary,
.add-mcp {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border-radius: 8px;
  cursor: pointer;
}

.btn-secondary,
.btn-danger,
.btn-primary {
  padding: 8px 12px;
  border: 1px solid var(--border-color);
  font-size: 12px;
}

.btn-secondary {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.btn-danger {
  border-color: #ef4444;
  background: transparent;
  color: #ef4444;
}

.btn-primary {
  border-color: var(--primary-color);
  background: var(--primary-color);
  color: #fff;
}

.btn-primary:disabled {
  cursor: not-allowed;
  opacity: 0.65;
}

.add-mcp {
  width: 100%;
  padding: 16px;
  border: 1px dashed var(--border-color);
  background: var(--main-bg);
  color: var(--text-muted);
}

.add-mcp:hover {
  border-color: var(--primary-color);
  color: var(--primary-color);
}

.add-mcp svg {
  width: 18px;
  height: 18px;
}

.footer-actions {
  justify-content: flex-end;
  margin-top: 4px;
}
</style>
