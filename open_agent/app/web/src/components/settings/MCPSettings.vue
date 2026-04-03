<template>
  <div class="tab-content">
    <div class="content-header">
      <h3>{{ t('MCP 设置', 'MCP Settings') }}</h3>
      <p>{{ t('管理 MCP 服务器配置', 'Manage MCP server configurations') }}</p>
    </div>
    
    <div class="mcp-list">
      <div class="mcp-card" v-for="server in mcpServers" :key="server.name">
        <div class="mcp-header">
          <div class="mcp-info">
            <h4>{{ server.name }}</h4>
            <span class="mcp-type">{{ server.type }}</span>
          </div>
          <div class="mcp-status" :class="{ connected: server.connected }">
            {{ server.connected ? t('已连接', 'Connected') : t('未连接', 'Disconnected') }}
          </div>
        </div>
        <div class="mcp-actions">
          <button class="btn-secondary" @click="editServer(server)">{{ t('编辑', 'Edit') }}</button>
          <button class="btn-secondary" @click="testServer(server)">{{ t('测试', 'Test') }}</button>
          <button class="btn-danger" @click="deleteServer(server)">{{ t('删除', 'Delete') }}</button>
        </div>
      </div>
      
      <div class="add-mcp" @click="addServer">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="12" y1="5" x2="12" y2="19"/>
          <line x1="5" y1="12" x2="19" y2="12"/>
        </svg>
        <span>{{ t('添加 MCP 服务器', 'Add MCP Server') }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useSettingsStore } from '@/stores/settings'

const settingsStore = useSettingsStore()

const mcpServers = ref([
  { name: 'filesystem', type: 'stdio', connected: true },
  { name: 'fetch', type: 'http', connected: false },
])

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

function editServer(server: any) {
  alert(t('编辑功能开发中', 'Edit feature under development'))
}

function testServer(server: any) {
  alert(t('测试功能开发中', 'Test feature under development'))
}

function deleteServer(server: any) {
  if (confirm(t('确定删除?', 'Confirm delete?'))) {
    mcpServers.value = mcpServers.value.filter(s => s.name !== server.name)
  }
}

function addServer() {
  const name = prompt(t('输入服务器名称', 'Enter server name'))
  if (name) {
    mcpServers.value.push({ name, type: 'stdio', connected: false })
  }
}
</script>

<style scoped>
.tab-content { display: flex; flex-direction: column; gap: 20px; }
.content-header { margin-bottom: 8px; }
.content-header h3 { font-size: 16px; font-weight: 600; color: var(--text-primary); margin: 0 0 4px 0; }
.content-header p { font-size: 13px; color: var(--text-muted); margin: 0; }
.mcp-list { display: flex; flex-direction: column; gap: 12px; }
.mcp-card { background: var(--main-bg); border: 1px solid var(--border-color); border-radius: 12px; padding: 16px; }
.mcp-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.mcp-info { display: flex; align-items: center; gap: 12px; }
.mcp-info h4 { font-size: 14px; font-weight: 600; color: var(--text-primary); margin: 0; }
.mcp-type { font-size: 11px; padding: 2px 8px; background: var(--hover-bg); border-radius: 4px; color: var(--text-muted); }
.mcp-status { font-size: 12px; padding: 4px 10px; border-radius: 6px; background: var(--hover-bg); color: var(--text-muted); }
.mcp-status.connected { background: #10b981; color: white; }
.mcp-actions { display: flex; gap: 8px; }
.btn-secondary { padding: 6px 12px; border-radius: 6px; border: 1px solid var(--border-color); background: var(--hover-bg); color: var(--text-primary); font-size: 12px; cursor: pointer; }
.btn-danger { padding: 6px 12px; border-radius: 6px; border: 1px solid #ef4444; background: transparent; color: #ef4444; font-size: 12px; cursor: pointer; }
.add-mcp { display: flex; align-items: center; justify-content: center; gap: 8px; padding: 16px; background: var(--main-bg); border: 1px dashed var(--border-color); border-radius: 12px; color: var(--text-muted); cursor: pointer; }
.add-mcp:hover { border-color: var(--primary-color); color: var(--primary-color); }
.add-mcp svg { width: 20px; height: 20px; }
</style>