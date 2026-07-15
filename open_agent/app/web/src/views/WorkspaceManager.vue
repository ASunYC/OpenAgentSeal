<template>
  <div class="workspace-manager">
    <!-- Header: Workspace switcher + new workspace button -->
    <div class="wm-header">
      <div class="wm-header-left">
        <select
          class="wm-workspace-select"
          :value="currentWorkspaceId"
          @change="onWorkspaceChange"
          :title="currentWorkspace ? currentWorkspace.path : '无工作区'"
        >
          <option v-for="ws in workspaces" :key="ws.id" :value="ws.id">
            {{ ws.name }}{{ ws.is_current ? ' (当前)' : '' }}
          </option>
          <option v-if="!workspaces.length" value="" disabled>
            无工作区
          </option>
        </select>
        <button
          v-if="currentWorkspace && !currentWorkspace.is_current"
          class="wm-header-btn"
          @click="onSetCurrent"
          title="设为当前工作区"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
        </button>
        <button
          v-if="currentWorkspace"
          class="wm-header-btn danger"
          @click="onDeleteWorkspace"
          title="删除工作区"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="3 6 5 6 21 6"/>
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
          </svg>
        </button>
      </div>
      <div class="wm-header-center">
        <div class="wm-search-box">
          <svg class="wm-search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8"/>
            <line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <input
            type="text"
            class="wm-search-input"
            :value="searchQuery"
            @input="updateSearchQuery"
            placeholder="搜索文件名..."
          />
          <button v-if="searchQuery" class="wm-search-clear" @click="clearSearchQuery">
            ×
          </button>
        </div>
      </div>
      <div class="wm-header-right">
        <span class="wm-item-count">{{ visibleWorkspaceFileCount }} 项</span>
        <span v-if="selectedPaths.size > 0" class="wm-selected-count">
          · 选中 {{ selectedPaths.size }} 项
        </span>
      </div>
    </div>

    <!-- Toolbar -->
    <div class="wm-toolbar">
      <div class="wm-toolbar-left">
        <button class="wm-toolbar-btn" @click="$emit('choose-files')" title="选择文件">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
          </svg>
          <span>文件</span>
        </button>
        <button class="wm-toolbar-btn" @click="$emit('choose-directory')" title="选择目录">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
          </svg>
          <span>目录</span>
        </button>
        <button class="wm-toolbar-btn" @click="$emit('add-web-url')" title="添加 Web 地址">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <line x1="2" y1="12" x2="22" y2="12"/>
            <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
          </svg>
          <span>Web</span>
        </button>
        <button class="wm-toolbar-btn" @click="$emit('add-server-path')" title="添加服务器路径">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="2" y="2" width="20" height="8" rx="2" ry="2"/>
            <rect x="2" y="14" width="20" height="8" rx="2" ry="2"/>
            <line x1="6" y1="6" x2="6.01" y2="6"/>
            <line x1="6" y1="18" x2="6.01" y2="18"/>
          </svg>
          <span>路径</span>
        </button>
      </div>
      <div class="wm-toolbar-right">
        <button
          class="wm-toolbar-btn view-toggle"
          :class="{ active: viewMode === 'list' }"
          @click="setViewMode('list')"
          title="列表视图"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="8" y1="6" x2="21" y2="6"/>
            <line x1="8" y1="12" x2="21" y2="12"/>
            <line x1="8" y1="18" x2="21" y2="18"/>
            <line x1="3" y1="6" x2="3.01" y2="6"/>
            <line x1="3" y1="12" x2="3.01" y2="12"/>
            <line x1="3" y1="18" x2="3.01" y2="18"/>
          </svg>
        </button>
        <button
          class="wm-toolbar-btn view-toggle"
          :class="{ active: viewMode === 'grid' }"
          @click="setViewMode('grid')"
          title="网格视图"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="3" width="7" height="7"/>
            <rect x="14" y="3" width="7" height="7"/>
            <rect x="14" y="14" width="7" height="7"/>
            <rect x="3" y="14" width="7" height="7"/>
          </svg>
        </button>
        <button class="wm-toolbar-btn" @click="$emit('refresh')" title="刷新">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="23 4 23 10 17 10"/>
            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
          </svg>
        </button>
      </div>
    </div>

    <!-- Workspace list with expandable files -->
    <div class="wm-workspace-list">
      <div
        v-for="ws in workspaces"
        :key="ws.id"
        class="wm-workspace-group"
        :class="{ 'is-current': ws.is_current }"
      >
        <!-- Workspace header -->
        <div class="wm-workspace-header" @click="toggleWorkspaceExpand(ws.id)">
          <button class="wm-expand-btn" :class="{ expanded: expandedWorkspaces.has(ws.id) }">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="9 18 15 12 9 6"/>
            </svg>
          </button>
          <span class="wm-workspace-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
            </svg>
          </span>
          <span class="wm-workspace-name">
            {{ ws.name }}
            <span v-if="ws.is_current" class="wm-current-badge">当前</span>
          </span>
          <span class="wm-workspace-path" :title="ws.path">{{ ws.path }}</span>
          <div class="wm-workspace-actions" @click.stop>
            <button
              v-if="!ws.is_current"
              class="wm-action-btn"
              @click="onSetWorkspaceCurrent(ws.id)"
              title="设为当前"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="20 6 9 17 4 12"/>
              </svg>
            </button>
            <button
              class="wm-action-btn danger"
              @click="onDeleteWorkspaceById(ws.id)"
              title="删除"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="3 6 5 6 21 6"/>
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
              </svg>
            </button>
          </div>
        </div>

        <!-- File list (expandable) -->
        <div v-if="expandedWorkspaces.has(ws.id)" class="wm-file-list" :class="{ grid: viewMode === 'grid' }">
          <div
            v-for="item in visibleWorkspaceFiles(ws.id)"
            :key="item.key"
            class="wm-file-item"
            :class="{
              selected: selectionState(ws.id, item.file) !== 'unchecked',
              partial: selectionState(ws.id, item.file) === 'mixed',
              directory: item.file.is_dir,
              expanded: item.expanded
            }"
            :style="{ '--file-level': item.level }"
            @click="onFileRowClick(ws.id, item.file)"
            @contextmenu.prevent="openContextMenu($event, ws.id, item.file)"
          >
            <input
              type="checkbox"
              :checked="selectionState(ws.id, item.file) === 'checked'"
              :indeterminate.prop="selectionState(ws.id, item.file) === 'mixed'"
              :aria-checked="selectionState(ws.id, item.file) === 'mixed' ? 'mixed' : selectionState(ws.id, item.file) === 'checked'"
              @click.stop
              @change="onFileCheckboxChange($event, ws.id, item.file)"
            />
            <button
              v-if="item.file.is_dir"
              class="wm-file-expand"
              :class="{ expanded: item.expanded }"
              type="button"
              @click.stop="toggleDirectory(ws.id, item.file)"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="9 18 15 12 9 6"/>
              </svg>
            </button>
            <span v-else class="wm-file-expand-placeholder"></span>
            <span class="wm-file-icon">
              <svg v-if="item.file.is_dir" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
              </svg>
              <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
              </svg>
            </span>
            <span class="wm-file-name" :title="item.file.path">{{ item.file.name }}</span>
            <span class="wm-file-size">{{ formatFileSize(item.file.size) }}</span>
          </div>
          <div v-if="!visibleWorkspaceFiles(ws.id).length" class="wm-empty-state">
            空目录
          </div>
        </div>
      </div>

      <div v-if="!workspaces.length" class="wm-empty-workspaces">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
        </svg>
        <p>点击"目录"按钮添加工作区</p>
      </div>
    </div>

    <!-- Status bar -->
    <div class="wm-status" v-if="error">
      <span class="wm-error">{{ error }}</span>
    </div>

    <!-- New workspace dialog -->
    <div v-if="showNewWorkspaceDialog" class="wm-dialog-overlay" @click.self="showNewWorkspaceDialog = false">
      <div class="wm-dialog">
        <h3>新建工作区</h3>
        <label>
          名称
          <input v-model="newWsName" placeholder="工作区名称" />
        </label>
        <label>
          路径
          <input v-model="newWsPath" placeholder="目录路径（留空则用名称创建）" />
        </label>
        <div class="wm-dialog-actions">
          <button class="wm-dialog-cancel" @click="showNewWorkspaceDialog = false">取消</button>
          <button class="wm-dialog-ok" @click="onCreateWorkspace">创建</button>
        </div>
      </div>
    </div>

    <!-- Context menu -->
    <div
      v-if="contextMenu.visible"
      class="wm-context-menu"
      :style="{ top: contextMenu.y + 'px', left: contextMenu.x + 'px' }"
    >
      <button v-if="contextMenu.file?.is_dir" @click="onContextAction('open')">打开</button>
      <button @click="onContextAction('rename')">重命名</button>
      <button @click="onContextAction('delete')" class="danger">删除</button>
    </div>

    <!-- Hidden file input for upload -->
    <input
      ref="fileInputRef"
      type="file"
      multiple
      style="display: none"
      @change="onFileSelected"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import type { FileEntry } from '@/types'
import { workspaceApi } from '@/api'
import { useWorkspaceManager } from '@/composables/useWorkspaceManager'
import {
  deselectWorkspaceFilePath,
  selectWorkspaceFilePath,
  workspaceCacheKey,
  workspaceFileSelectionState,
  type WorkspaceSelectionState,
} from '@/models/workspaceSelection'

defineEmits<{
  (event: 'choose-files'): void
  (event: 'choose-directory'): void
  (event: 'add-web-url'): void
  (event: 'add-server-path'): void
  (event: 'refresh'): void
}>()

const {
  workspaces,
  currentWorkspaceId,
  currentWorkspace,
  error,
  viewMode,
  searchQuery,
  selectedPaths,
  init,
  selectWorkspace,
  createWorkspace,
  deleteWorkspace,
  setCurrentWorkspace,
  deleteItem,
  renameItem,
  uploadFile,
} = useWorkspaceManager()

// Expanded workspaces state
const expandedWorkspaces = ref<Set<string>>(new Set())
const expandedDirectories = ref<Set<string>>(new Set())

// Workspace files cache
const workspaceFiles = ref<Record<string, FileEntry[]>>({})

// Dialog state
const showNewWorkspaceDialog = ref(false)
const newWsName = ref('')
const newWsPath = ref('')

// Context menu state
const contextMenu = ref<{
  visible: boolean
  x: number
  y: number
  wsId: string
  file: FileEntry | null
}>({ visible: false, x: 0, y: 0, wsId: '', file: null })

const fileInputRef = ref<HTMLInputElement | null>(null)

const visibleWorkspaceFileCount = computed(() =>
  workspaces.value.reduce((total, ws) => total + visibleWorkspaceFiles(ws.id).length, 0)
)

onMounted(() => {
  init()
  // Close context menu on click elsewhere
  document.addEventListener('click', () => {
    contextMenu.value.visible = false
  })
})

function toggleWorkspaceExpand(wsId: string) {
  if (expandedWorkspaces.value.has(wsId)) {
    expandedWorkspaces.value.delete(wsId)
  } else {
    expandedWorkspaces.value.add(wsId)
    // Always reload files when expanding
    loadWorkspaceFiles(wsId)
  }
}

function cacheKey(wsId: string, path = ''): string {
  return workspaceCacheKey(wsId, path)
}

async function loadWorkspaceFiles(wsId: string, path = '') {
  const key = cacheKey(wsId, path)
  try {
    const result = await workspaceApi.listFiles(wsId, path || undefined)
    // Force reactivity by creating a new object
    workspaceFiles.value = {
      ...workspaceFiles.value,
      [key]: result.files || []
    }
  } catch (e: any) {
    console.error(`Failed to load files for workspace ${wsId}:${path}:`, e)
    workspaceFiles.value = {
      ...workspaceFiles.value,
      [key]: []
    }
  }
}

function onSetWorkspaceCurrent(wsId: string) {
  setCurrentWorkspace(wsId)
}

async function onDeleteWorkspaceById(wsId: string) {
  await deleteWorkspace(wsId)
  // Clean up cached files - force reactivity
  const newFiles = { ...workspaceFiles.value }
  for (const key of Object.keys(newFiles)) {
    if (key === wsId || key.startsWith(`${wsId}:`)) {
      delete newFiles[key]
    }
  }
  workspaceFiles.value = newFiles
  expandedWorkspaces.value.delete(wsId)
  expandedDirectories.value = new Set(
    Array.from(expandedDirectories.value).filter(key => !key.startsWith(`${wsId}:`))
  )
}

function formatFileSize(bytes: number | null): string {
  if (bytes === null || bytes === undefined) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function workspaceRoot(wsId: string): string {
  return workspaces.value.find(ws => ws.id === wsId)?.path || ''
}

function selectFilePath(wsId: string, file: FileEntry) {
  selectedPaths.value = selectWorkspaceFilePath(
    selectedPaths.value,
    workspaceFiles.value,
    wsId,
    workspaceRoot(wsId),
    file,
  )
}

function deselectFilePath(wsId: string, file: FileEntry) {
  selectedPaths.value = deselectWorkspaceFilePath(
    selectedPaths.value,
    workspaceFiles.value,
    wsId,
    workspaceRoot(wsId),
    file,
  )
}

function selectionState(wsId: string, file: FileEntry): WorkspaceSelectionState {
  return workspaceFileSelectionState(
    selectedPaths.value,
    workspaceFiles.value,
    wsId,
    workspaceRoot(wsId),
    file,
  )
}

function onFileCheckboxChange(event: Event, wsId: string, file: FileEntry) {
  const checked = (event.target as HTMLInputElement).checked
  if (checked) {
    selectFilePath(wsId, file)
  } else {
    deselectFilePath(wsId, file)
  }
}

interface VisibleFileItem {
  key: string
  file: FileEntry
  level: number
  expanded: boolean
}

function visibleWorkspaceFiles(wsId: string): VisibleFileItem[] {
  const q = searchQuery.value.trim().toLowerCase()
  const result: VisibleFileItem[] = []

  const append = (path = '', level = 0) => {
    const parentKey = cacheKey(wsId, path)
    const children = [...(workspaceFiles.value[parentKey] || [])]
      .filter(file => !q || file.name.toLowerCase().includes(q) || file.path.toLowerCase().includes(q))
      .sort((a, b) => {
      if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1
      return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })
    })

    for (const file of children) {
      const dirKey = cacheKey(wsId, file.path)
      const expanded = expandedDirectories.value.has(dirKey)
      result.push({ key: `${wsId}:${file.path}`, file, level, expanded })
      if (file.is_dir && expanded) {
        append(file.path, level + 1)
      }
    }
  }

  append()
  return result
}

async function toggleDirectory(wsId: string, file: FileEntry) {
  if (!file.is_dir) return
  const key = cacheKey(wsId, file.path)
  const expanded = new Set(expandedDirectories.value)
  if (expanded.has(key)) {
    expanded.delete(key)
    expandedDirectories.value = expanded
    return
  }

  expanded.add(key)
  expandedDirectories.value = expanded
  if (!workspaceFiles.value[key]) {
    await loadWorkspaceFiles(wsId, file.path)
  }
}

function onFileRowClick(wsId: string, file: FileEntry) {
  if (file.is_dir) {
    void toggleDirectory(wsId, file)
  }
}

function openContextMenu(mouseEvent: MouseEvent, wsId: string, file: FileEntry) {
  contextMenu.value = {
    visible: true,
    x: mouseEvent.clientX,
    y: mouseEvent.clientY,
    wsId,
    file,
  }
}

function onWorkspaceChange(e: Event) {
  const wsId = (e.target as HTMLSelectElement).value
  selectWorkspace(wsId)
}

function updateSearchQuery(e: Event) {
  searchQuery.value = (e.target as HTMLInputElement).value
}

function clearSearchQuery() {
  searchQuery.value = ''
}

function setViewMode(mode: 'list' | 'grid') {
  viewMode.value = mode
}

async function onCreateWorkspace() {
  if (!newWsName.value.trim()) return
  await createWorkspace(newWsName.value.trim(), newWsPath.value.trim())
  showNewWorkspaceDialog.value = false
  newWsName.value = ''
  newWsPath.value = ''
}

async function onDeleteWorkspace() {
  if (!currentWorkspace.value) return
  if (confirm(`确定删除工作区 "${currentWorkspace.value.name}"？（不会删除磁盘上的文件）`)) {
    await deleteWorkspace(currentWorkspace.value.id)
  }
}

async function onSetCurrent() {
  if (!currentWorkspace.value) return
  await setCurrentWorkspace(currentWorkspace.value.id)
}

async function onFileSelected(e: Event) {
  const input = e.target as HTMLInputElement
  if (!input.files?.length) return
  for (const file of input.files) {
    await uploadFile(file)
  }
  input.value = ''
}

async function onContextAction(action: string) {
  const file = contextMenu.value.file
  const wsId = contextMenu.value.wsId
  contextMenu.value.visible = false
  if (!file || !wsId) return

  switch (action) {
    case 'open':
      await toggleDirectory(wsId, file)
      break
    case 'rename': {
      const newName = prompt('重命名为:', file.name)
      if (newName?.trim() && newName !== file.name) {
        await renameItem(file.path, newName.trim())
      }
      break
    }
    case 'delete':
      if (confirm(`确定删除 "${file.name}"？`)) {
        await deleteItem(file.path)
      }
      break
  }
}
</script>

<style scoped>
.workspace-manager {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--glass-bg);
  position: relative;
}

/* ── Header ── */

.wm-header {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-color);
  gap: 8px;
}

.wm-header-left,
.wm-header-right {
  display: flex;
  align-items: center;
  gap: 6px;
}

.wm-header-center {
  flex: 1;
  display: flex;
  justify-content: center;
  min-width: 0;
}

.wm-item-count {
  font-size: 11px;
  color: var(--text-muted);
}

.wm-selected-count {
  color: var(--primary-color);
}

.wm-workspace-select {
  padding: 4px 8px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--glass-bg-strong);
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  max-width: 180px;
}

.wm-header-btn {
  width: 26px;
  height: 26px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border-color);
  border-radius: 7px;
  background: var(--glass-bg);
  color: var(--text-secondary);
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}

.wm-header-btn:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.wm-header-btn.danger:hover {
  color: var(--danger-color, #e53e3e);
  border-color: color-mix(in srgb, var(--danger-color, #e53e3e) 40%, var(--border-color));
}

.wm-header-btn svg {
  width: 14px;
  height: 14px;
}

/* ── Toolbar ── */

.wm-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: var(--glass-bg);
  border-bottom: 1px solid var(--border-color);
  min-height: 38px;
}

.wm-toolbar-left,
.wm-toolbar-right {
  display: flex;
  align-items: center;
  gap: 4px;
}

.wm-toolbar-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
  white-space: nowrap;
}

.wm-toolbar-btn:hover {
  border-color: var(--border-color);
  background: var(--hover-bg);
  color: var(--text-primary);
}

.wm-toolbar-btn.view-toggle.active {
  border-color: color-mix(in srgb, var(--primary-color) 40%, var(--border-color));
  background: color-mix(in srgb, var(--primary-color) 10%, var(--glass-bg));
  color: var(--primary-color);
}

.wm-toolbar-btn svg {
  width: 15px;
  height: 15px;
}

.wm-search-box {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--glass-bg-strong);
  max-width: 240px;
  width: 100%;
}

.wm-search-icon {
  width: 14px;
  height: 14px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.wm-search-input {
  flex: 1;
  border: none;
  background: transparent;
  color: var(--text-primary);
  font-size: 12px;
  outline: none;
  min-width: 0;
}

.wm-search-input::placeholder {
  color: var(--text-muted);
}

.wm-search-clear {
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 16px;
  padding: 0 2px;
  line-height: 1;
}

.wm-search-clear:hover {
  color: var(--text-primary);
}

/* ── Status bar ── */

.wm-status {
  padding: 4px 12px;
  border-top: 1px solid var(--border-color);
  min-height: 24px;
}

.wm-error {
  font-size: 11px;
  color: var(--danger-color, #e53e3e);
}

/* ── Dialog ── */

.wm-dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.wm-dialog {
  background: var(--glass-bg-strong);
  border: 1px solid var(--border-color);
  border-radius: 14px;
  padding: 20px;
  min-width: 320px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
}

.wm-dialog h3 {
  margin: 0 0 16px;
  font-size: 15px;
  font-weight: 700;
}

.wm-dialog label {
  display: block;
  margin-bottom: 12px;
  font-size: 12px;
  color: var(--text-secondary);
}

.wm-dialog input {
  display: block;
  width: 100%;
  margin-top: 4px;
  padding: 6px 10px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--glass-bg);
  color: var(--text-primary);
  font-size: 13px;
}

.wm-dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}

.wm-dialog-cancel,
.wm-dialog-ok {
  padding: 6px 16px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid var(--border-color);
}

.wm-dialog-cancel {
  background: transparent;
  color: var(--text-secondary);
}

.wm-dialog-ok {
  background: var(--primary-color);
  color: white;
  border-color: var(--primary-color);
}

/* ── Context menu ── */

.wm-context-menu {
  position: fixed;
  z-index: 1001;
  background: var(--glass-bg-strong);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 4px;
  min-width: 120px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
}

.wm-context-menu button {
  display: block;
  width: 100%;
  padding: 6px 12px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-primary);
  font-size: 12px;
  text-align: left;
  cursor: pointer;
}

.wm-context-menu button:hover {
  background: var(--hover-bg);
}

.wm-context-menu button.danger {
  color: var(--danger-color, #e53e3e);
}

/* ── Workspace List ── */

.wm-workspace-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px 0;
}

.wm-workspace-group {
  border-bottom: 1px solid var(--border-color);
}

.wm-workspace-group.is-current {
  background: color-mix(in srgb, var(--primary-color) 5%, transparent);
}

.wm-workspace-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  transition: background 0.15s;
}

.wm-workspace-header:hover {
  background: var(--hover-bg);
}

.wm-expand-btn {
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: transform 0.2s;
}

.wm-expand-btn svg {
  width: 14px;
  height: 14px;
}

.wm-expand-btn.expanded {
  transform: rotate(90deg);
}

.wm-workspace-icon {
  width: 18px;
  height: 18px;
  color: var(--text-secondary);
  flex-shrink: 0;
}

.wm-workspace-icon svg {
  width: 100%;
  height: 100%;
}

.wm-workspace-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  flex-shrink: 0;
}

.wm-current-badge {
  display: inline-block;
  padding: 1px 6px;
  margin-left: 6px;
  font-size: 10px;
  font-weight: 500;
  color: var(--primary-color);
  background: color-mix(in srgb, var(--primary-color) 15%, transparent);
  border-radius: 4px;
}

.wm-workspace-path {
  flex: 1;
  font-size: 11px;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wm-workspace-actions {
  display: flex;
  gap: 4px;
  opacity: 0;
  transition: opacity 0.15s;
}

.wm-workspace-header:hover .wm-workspace-actions {
  opacity: 1;
}

.wm-action-btn {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s;
}

.wm-action-btn:hover {
  border-color: var(--border-color);
  background: var(--hover-bg);
  color: var(--text-primary);
}

.wm-action-btn.danger:hover {
  color: var(--danger-color, #e53e3e);
  border-color: color-mix(in srgb, var(--danger-color, #e53e3e) 40%, var(--border-color));
}

.wm-action-btn svg {
  width: 14px;
  height: 14px;
}

/* ── File List ── */

.wm-file-list {
  padding: 4px 0 8px 46px;
}

.wm-file-list.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
  gap: 6px;
  padding: 8px 12px 12px 46px;
}

.wm-file-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 12px;
  font-size: 12px;
  cursor: default;
  transition: background 0.1s;
}

.wm-file-list:not(.grid) .wm-file-item {
  padding-left: calc(12px + (var(--file-level) * 18px));
}

.wm-file-list.grid .wm-file-item {
  min-height: 82px;
  flex-direction: column;
  justify-content: center;
  text-align: center;
  border-radius: 7px;
}

.wm-file-item:hover {
  background: var(--hover-bg);
}

.wm-file-item.selected {
  background: color-mix(in srgb, var(--primary-color) 10%, transparent);
}

.wm-file-expand,
.wm-file-expand-placeholder {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}

.wm-file-expand {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: transform 0.15s, background 0.15s, color 0.15s;
}

.wm-file-expand:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.wm-file-expand.expanded {
  transform: rotate(90deg);
}

.wm-file-expand svg {
  width: 13px;
  height: 13px;
}

.wm-file-item input[type="checkbox"] {
  width: 14px;
  height: 14px;
  cursor: pointer;
}

.wm-file-icon {
  width: 16px;
  height: 16px;
  color: var(--text-secondary);
  flex-shrink: 0;
}

.wm-file-icon svg {
  width: 100%;
  height: 100%;
}

.wm-file-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-primary);
}

.wm-file-list.grid .wm-file-name {
  width: 100%;
  flex: 0;
}

.wm-file-list.grid .wm-file-size {
  display: none;
}

.wm-file-size {
  font-size: 11px;
  color: var(--text-muted);
  flex-shrink: 0;
  min-width: 50px;
  text-align: right;
}

/* ── Empty States ── */

.wm-empty-state {
  padding: 12px;
  text-align: center;
  font-size: 12px;
  color: var(--text-muted);
}

.wm-empty-workspaces {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 40px 20px;
  color: var(--text-muted);
}

.wm-empty-workspaces svg {
  width: 48px;
  height: 48px;
  opacity: 0.4;
}

.wm-empty-workspaces p {
  font-size: 13px;
  margin: 0;
}
</style>
