<template>
  <div 
    class="settings-panel settings-shell"
    :style="{ width: panelWidth + 'px' }"
  >
    <!-- 左侧拖拽手柄 -->
    <div
      class="resizer"
      :class="{ dragging: isDragging }"
      @mousedown="startDrag"
      title="拖拽调整宽度"
    >
      <div class="resizer-indicator"></div>
    </div>
    <!-- 面板头部 -->
    <header class="panel-header settings-header">
      <h2>{{ t('设置', 'Settings') }}</h2>
      <button class="btn-close settings-button" @click="$emit('close')">
        <svg class="close-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
          <line x1="18" y1="6" x2="6" y2="18"/>
          <line x1="6" y1="6" x2="18" y2="18"/>
        </svg>
      </button>
    </header>
    
    <!-- 菜单列表 -->
    <div class="panel-body">
      <nav class="settings-menu">
        <div 
          class="menu-item" 
          :class="{ active: currentTab === 'dashboard' }"
          @click="switchTab('dashboard')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="3" width="7" height="7"/>
            <rect x="14" y="3" width="7" height="7"/>
            <rect x="14" y="14" width="7" height="7"/>
            <rect x="3" y="14" width="7" height="7"/>
          </svg>
          <span>{{ t('数据面板', 'Dashboard') }}</span>
        </div>
        
        <div 
          class="menu-item" 
          :class="{ active: currentTab === 'workspace' }"
          @click="switchTab('workspace')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
          </svg>
          <span>{{ t('工作目录', 'Workspace') }}</span>
        </div>
        
        <div 
          class="menu-item" 
          :class="{ active: currentTab === 'user' }"
          @click="switchTab('user')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
            <circle cx="12" cy="7" r="4"/>
          </svg>
          <span>{{ t('用户', 'User') }}</span>
        </div>
        
        <div 
          class="menu-item" 
          :class="{ active: currentTab === 'models' }"
          @click="switchTab('models')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09A1.65 1.65 0 0 0 19.4 15z"/>
          </svg>
          <span>{{ t('模型', 'Models') }}</span>
        </div>
        
        <div 
          class="menu-item" 
          :class="{ active: currentTab === 'smart-routing' }"
          @click="switchTab('smart-routing')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M4 7h7a4 4 0 0 1 4 4v6"/>
            <path d="M4 17h7a4 4 0 0 0 4-4V7"/>
            <path d="M18 4l3 3-3 3"/>
            <path d="M18 14l3 3-3 3"/>
          </svg>
          <span>{{ t('智能路由', 'Smart Routing') }}</span>
        </div>
        
        <div 
          class="menu-item" 
          :class="{ active: currentTab === 'agents' }"
          @click="switchTab('agents')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
            <circle cx="9" cy="7" r="4"/>
            <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
            <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
          </svg>
          <span>{{ t('智能体', 'Agents') }}</span>
        </div>
        
        <div 
          class="menu-item" 
          :class="{ active: currentTab === 'skills' }"
          @click="switchTab('skills')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
          </svg>
          <span>{{ t('技能', 'Skills') }}</span>
        </div>
        
        <div
          class="menu-item"
          :class="{ active: currentTab === 'plugins' }"
          @click="switchTab('plugins')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M14 3v4a2 2 0 0 0 2 2h4" />
            <path d="M5 8V5a2 2 0 0 1 2-2h7l5 5v3" />
            <path d="M5 16v3a2 2 0 0 0 2 2h3" />
            <path d="M15 14h6v6h-6z" />
            <path d="M3 11h6v6H3z" />
          </svg>
          <span>{{ t('插件', 'Plugins') }}</span>
        </div>

        <div 
          class="menu-item" 
          :class="{ active: currentTab === 'mcp' }"
          @click="switchTab('mcp')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="4" y="4" width="16" height="16" rx="2" ry="2"/>
            <rect x="9" y="9" width="6" height="6"/>
            <line x1="9" y1="1" x2="9" y2="4"/>
            <line x1="15" y1="1" x2="15" y2="4"/>
            <line x1="9" y1="20" x2="9" y2="23"/>
            <line x1="15" y1="20" x2="15" y2="23"/>
            <line x1="20" y1="9" x2="23" y2="9"/>
            <line x1="20" y1="14" x2="23" y2="14"/>
            <line x1="1" y1="9" x2="4" y2="9"/>
            <line x1="1" y1="14" x2="4" y2="14"/>
          </svg>
          <span>{{ t('MCP', 'MCP') }}</span>
        </div>
        
        <div 
          class="menu-item" 
          :class="{ active: currentTab === 'logs' }"
          @click="switchTab('logs')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
            <line x1="16" y1="13" x2="8" y2="13"/>
            <line x1="16" y1="17" x2="8" y2="17"/>
            <polyline points="10 9 9 9 8 9"/>
          </svg>
          <span>{{ t('日志', 'Logs') }}</span>
        </div>
        
        <div
          class="menu-item"
          :class="{ active: currentTab === 'knowledge' }"
          @click="switchTab('knowledge')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>
            <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
          </svg>
          <span>{{ t('知识库', 'Knowledge') }}</span>
        </div>

        <div
          class="menu-item"
          :class="{ active: currentTab === 'tasks' }"
          @click="switchTab('tasks')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <polyline points="12 6 12 12 16 16"/>
          </svg>
          <span>{{ t('定时任务', 'Tasks') }}</span>
        </div>
        
        <div 
          class="menu-item" 
          :class="{ active: currentTab === 'system' }"
          @click="switchTab('system')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l-.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09A1.65 1.65 0 0 0 19.4 15z"/>
          </svg>
          <span>{{ t('系统', 'System') }}</span>
        </div>
      </nav>
      
      <!-- 内容区域 -->
      <div class="settings-content settings-surface">
        <!-- 数据面板 -->
        <DashboardSettings v-if="currentTab === 'dashboard'" />
        
        <!-- 工作目录 -->
        <WorkspaceSettings v-else-if="currentTab === 'workspace'" />
        
        <!-- 用户设置 -->
        <UserSettings v-else-if="currentTab === 'user'" />
        
        <!-- 模型设置 -->
        <ModelsSettings v-else-if="currentTab === 'models'" />

        <!-- 智能路由 -->
        <SmartRoutingSettings v-else-if="currentTab === 'smart-routing'" />
        
        <!-- 智能体设置 -->
        <AgentsSettings v-else-if="currentTab === 'agents'" />
        
        <!-- 技能 -->
        <SkillsSettings v-else-if="currentTab === 'skills'" />

        <PluginsSettings v-else-if="currentTab === 'plugins'" />
        
        <!-- MCP -->
        <MCPSettings v-else-if="currentTab === 'mcp'" />
        
        <!-- 日志 -->
        <LogsSettings v-else-if="currentTab === 'logs'" />
        
        <!-- 知识库 -->
        <KnowledgeSettings v-else-if="currentTab === 'knowledge'" />

        <!-- 定时任务 -->
        <TasksSettings v-else-if="currentTab === 'tasks'" />
        
        <!-- 系统设置 -->
        <SystemSettings v-else-if="currentTab === 'system'" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import DashboardSettings from '@/components/settings/DashboardSettings.vue'
import WorkspaceSettings from '@/components/settings/WorkspaceSettings.vue'
import UserSettings from '@/components/settings/UserSettings.vue'
import ModelsSettings from '@/components/settings/ModelsSettings.vue'
import SmartRoutingSettings from '@/components/settings/SmartRoutingSettings.vue'
import AgentsSettings from '@/components/settings/AgentsSettings.vue'
import SkillsSettings from '@/components/settings/SkillsSettings.vue'
import PluginsSettings from '@/components/settings/PluginsSettings.vue'
import MCPSettings from '@/components/settings/MCPSettings.vue'
import LogsSettings from '@/components/settings/LogsSettings.vue'
import TasksSettings from '@/components/settings/TasksSettings.vue'
import KnowledgeSettings from '@/components/settings/KnowledgeSettings.vue'
import SystemSettings from '@/components/settings/SystemSettings.vue'

const props = defineProps<{
  currentTab: string
  width?: number
}>()

const emit = defineEmits<{
  close: []
  switchTab: [tab: string]
  'update:width': [width: number]
}>()

const settingsStore = useSettingsStore()

// 拖拽相关
const isDragging = ref(false)
const startX = ref(0)
const startWidth = ref(0)
const minWidth = 500 // 最小宽度
const maxWidth = 1600 // 最大宽度

// 计算面板宽度
const panelWidth = computed({
  get: () => props.width || 900,
  set: (val) => emit('update:width', val)
})

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

function switchTab(tab: string) {
  emit('switchTab', tab)
}

// 开始拖拽
const startDrag = (e: MouseEvent) => {
  isDragging.value = true
  startX.value = e.clientX
  startWidth.value = panelWidth.value
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
  // 添加事件监听
  document.addEventListener('mousemove', onDrag)
  document.addEventListener('mouseup', stopDrag)
}

// 拖拽中
const onDrag = (e: MouseEvent) => {
  if (!isDragging.value) return
  const deltaX = startX.value - e.clientX // 向左拖拽增加宽度
  let newWidth = startWidth.value + deltaX
  newWidth = Math.max(minWidth, Math.min(maxWidth, newWidth))
  panelWidth.value = newWidth
}

// 结束拖拽
const stopDrag = () => {
  isDragging.value = false
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  // 移除事件监听
  document.removeEventListener('mousemove', onDrag)
  document.removeEventListener('mouseup', stopDrag)
}
</script>

<style scoped>
.settings-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: transparent;
  position: relative;
  min-width: 500px;
  color: var(--text-primary);
}

.resizer {
  position: absolute;
  left: 0;
  top: 0;
  width: 8px;
  height: 100%;
  cursor: col-resize;
  z-index: 10;
  background: transparent;
  display: flex;
  align-items: center;
  justify-content: center;
}

.resizer-indicator {
  width: 4px;
  height: 60px;
  background: rgba(115, 115, 115, 0.32);
  border-radius: 999px;
  transition: all 0.2s;
}

.resizer:hover .resizer-indicator {
  background: var(--primary-color, #3b82f6);
  height: 100px;
}

.resizer.dragging .resizer-indicator {
  background: var(--primary-color, #3b82f6);
  width: 4px;
  height: 100%;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 22px;
  border-bottom: 1px solid var(--border-color);
  background: var(--glass-bg);
  backdrop-filter: blur(18px) saturate(160%);
  -webkit-backdrop-filter: blur(18px) saturate(160%);
}

.panel-header h2 {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
  letter-spacing: -0.02em;
}

.btn-close {
  width: 36px;
  height: 36px;
  border-radius: 12px;
  border: 1px solid var(--border-color);
  background: var(--glass-bg-strong);
  color: var(--text-primary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: inset 0 1px 0 var(--glass-border), 0 8px 18px rgba(17, 24, 39, 0.08);
  transition: transform 0.18s ease, background 0.2s ease, border-color 0.2s ease, color 0.2s ease;
}

.btn-close:hover {
  background: rgba(239, 68, 68, 0.12);
  border-color: rgba(239, 68, 68, 0.42);
  color: #ef4444;
  transform: translateY(-1px);
}

.btn-close .close-icon {
  width: 20px !important;
  height: 20px !important;
  flex-shrink: 0;
}

.panel-body {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.settings-menu {
  width: 178px;
  min-width: 178px;
  border-right: 1px solid var(--border-color);
  padding: 14px 10px;
  overflow-y: auto;
  background: rgba(255, 255, 255, 0.18);
}

:global(.dark) .settings-menu,
:global(.dark) .settings-content {
  background: rgba(0, 0, 0, 0.08);
}

.menu-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  margin: 2px 0;
  border-radius: 12px;
  cursor: pointer;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 560;
  transition: all 0.2s;
  position: relative;
  border: 1px solid transparent;
}

.menu-item:hover {
  background: var(--glass-bg);
  border-color: var(--border-color);
  color: var(--text-primary);
}

.menu-item.active {
  background: var(--glass-bg-strong);
  color: var(--primary-color);
  border-color: rgba(47, 110, 244, 0.18);
  box-shadow: 0 10px 24px rgba(47, 110, 244, 0.08), inset 0 1px 0 rgba(255, 255, 255, 0.62);
}

.menu-item svg {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}

.settings-content {
  flex: 1;
  overflow-y: auto;
  padding: 22px;
  background: rgba(255, 255, 255, 0.08);
}

.tab-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.content-header {
  margin-bottom: 8px;
}

.content-header h3 {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 4px 0;
  letter-spacing: -0.02em;
}

.content-header p {
  font-size: 13px;
  color: var(--text-muted);
  margin: 0;
}

.btn-primary {
  padding: 10px 20px;
  background: var(--primary-color);
  border: none;
  border-radius: 12px;
  color: white;
  font-size: 14px;
  cursor: pointer;
  transition: opacity 0.2s, transform 0.18s ease;
  align-self: flex-start;
  box-shadow: 0 14px 28px rgba(47, 110, 244, 0.18);
}

.btn-primary:hover {
  opacity: 0.9;
  transform: translateY(-1px);
}
</style>
