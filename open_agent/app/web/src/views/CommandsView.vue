<template>
  <div class="commands-view">
    <header class="view-header">
      <h1>{{ t('指令', 'Commands') }}</h1>
      <p class="subtitle">{{ t('查看所有智能体的命令行参数', 'View command line arguments for all agents') }}</p>
    </header>
    
    <div class="commands-container">
      <div class="search-bar">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="8"/>
          <line x1="21" y1="21" x2="16.65" y2="16.65"/>
        </svg>
        <input 
          type="text" 
          v-model="searchQuery"
          :placeholder="t('搜索指令...', 'Search commands...')"
        />
      </div>
      
      <div class="commands-list">
        <div 
          v-for="agent in filteredAgents" 
          :key="agent.id"
          class="agent-commands"
        >
          <div class="agent-header">
            <div class="agent-avatar" :style="{ background: getAvatarColor(agent.name) }">
              {{ agent.name.charAt(0).toUpperCase() }}
            </div>
            <div class="agent-info">
              <h3>{{ agent.name }}</h3>
              <p>{{ agent.description || t('暂无描述', 'No description') }}</p>
            </div>
          </div>
          
          <div class="commands-table">
            <div class="table-header">
              <div class="col-command">{{ t('命令', 'Command') }}</div>
              <div class="col-params">{{ t('参数', 'Parameters') }}</div>
              <div class="col-desc">{{ t('说明', 'Description') }}</div>
            </div>
            <div class="table-body">
              <div 
                v-for="(cmd, index) in getAgentCommands(agent)" 
                :key="index"
                class="table-row"
              >
                <div class="col-command">
                  <code>{{ cmd.name }}</code>
                </div>
                <div class="col-params">
                  <span v-if="cmd.params && cmd.params.length" class="param-badge" v-for="p in cmd.params" :key="p">
                    {{ p }}
                  </span>
                  <span v-else class="no-params">-</span>
                </div>
                <div class="col-desc">{{ cmd.description }}</div>
              </div>
              
              <div v-if="getAgentCommands(agent).length === 0" class="no-commands">
                {{ t('暂无指令', 'No commands available') }}
              </div>
            </div>
          </div>
        </div>
      </div>
      
      <div v-if="filteredAgents.length === 0" class="empty-state">
        <div class="empty-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <rect x="2" y="3" width="20" height="14" rx="2" ry="2"/>
            <line x1="8" y1="21" x2="16" y2="21"/>
            <line x1="12" y1="17" x2="12" y2="21"/>
          </svg>
        </div>
        <p>{{ t('没有找到匹配的指令', 'No matching commands found') }}</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import { useAgentStore } from '@/stores/agent'
import { api } from '@/api'
import type { AgentConfig } from '@/types'

interface Command {
  name: string
  params?: string[]
  description: string
}

const settingsStore = useSettingsStore()
const agentStore = useAgentStore()

const agents = ref<AgentConfig[]>([])
const searchQuery = ref('')
const commandsMap = ref<Record<string, Command[]>>({})

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

const filteredAgents = computed(() => {
  if (!searchQuery.value) return agents.value
  
  const query = searchQuery.value.toLowerCase()
  return agents.value.filter(agent => {
    const commands = commandsMap.value[agent.id] || []
    return agent.name.toLowerCase().includes(query) ||
           commands.some(cmd => 
             cmd.name.toLowerCase().includes(query) ||
             cmd.description.toLowerCase().includes(query)
           )
  })
})

function getAvatarColor(name: string): string {
  const colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4']
  const index = name.charCodeAt(0) % colors.length
  return colors[index]
}

function getAgentCommands(agent: AgentConfig): Command[] {
  return commandsMap.value[agent.id] || []
}

async function loadCommands() {
  try {
    const commandInfos = await api.getCommands()
    for (const info of commandInfos) {
      commandsMap.value[info.agent_id] = info.commands || []
    }
  } catch (error) {
    console.error('Failed to load commands:', error)
  }
}

onMounted(async () => {
  await agentStore.loadAgents()
  agents.value = [...agentStore.agents]
  await loadCommands()
})
</script>

<style scoped>
.commands-view {
  padding: 32px;
  height: 100%;
  overflow-y: auto;
}

.view-header {
  margin-bottom: 24px;
}

.view-header h1 {
  font-size: 28px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.subtitle {
  color: var(--text-secondary);
  font-size: 16px;
}

.commands-container {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.search-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  max-width: 400px;
}

.search-bar svg {
  width: 20px;
  height: 20px;
  stroke: var(--text-muted);
  flex-shrink: 0;
}

.search-bar input {
  flex: 1;
  border: none;
  background: transparent;
  color: var(--text-primary);
  font-size: 14px;
}

.search-bar input:focus {
  outline: none;
}

.commands-list {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.agent-commands {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  overflow: hidden;
}

.agent-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px;
  border-bottom: 1px solid var(--border-color);
  background: var(--hover-bg);
}

.agent-avatar {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-weight: 700;
  font-size: 20px;
  flex-shrink: 0;
}

.agent-info h3 {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 4px 0;
}

.agent-info p {
  font-size: 14px;
  color: var(--text-secondary);
  margin: 0;
}

.commands-table {
  width: 100%;
}

.table-header {
  display: grid;
  grid-template-columns: 200px 200px 1fr;
  padding: 12px 20px;
  background: var(--input-bg);
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.table-body {
  max-height: 400px;
  overflow-y: auto;
}

.table-row {
  display: grid;
  grid-template-columns: 200px 200px 1fr;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
  transition: background 0.2s;
}

.table-row:last-child {
  border-bottom: none;
}

.table-row:hover {
  background: var(--hover-bg);
}

.col-command code {
  padding: 4px 8px;
  background: var(--input-bg);
  border-radius: 6px;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 13px;
  color: var(--primary-color);
}

.col-params {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.param-badge {
  padding: 2px 8px;
  background: var(--hover-bg);
  border-radius: 4px;
  font-size: 12px;
  font-family: monospace;
  color: var(--text-secondary);
}

.no-params {
  color: var(--text-muted);
}

.col-desc {
  font-size: 14px;
  color: var(--text-primary);
  line-height: 1.5;
}

.no-commands {
  padding: 24px;
  text-align: center;
  color: var(--text-muted);
  font-size: 14px;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px;
  color: var(--text-muted);
}

.empty-icon {
  margin-bottom: 16px;
}

.empty-icon svg {
  width: 64px;
  height: 64px;
  stroke: var(--text-muted);
}

.empty-state p {
  font-size: 16px;
}
</style>