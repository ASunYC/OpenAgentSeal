/**
 * useWorkspaceManager — Reactive state management for the workspace resource manager.
 *
 * Provides workspace CRUD, file browsing, and file operations.
 */

import { ref, computed } from 'vue'
import type { Workspace, FileEntry } from '@/types'
import { workspaceApi } from '@/api'

// Singleton state shared across all component instances
const workspaces = ref<Workspace[]>([])
const currentWorkspaceId = ref<string>('')
const currentPath = ref<string>('')
const files = ref<FileEntry[]>([])
const loading = ref(false)
const error = ref<string>('')
const viewMode = ref<'list' | 'grid'>('list')
const searchQuery = ref('')
const selectedPaths = ref<Set<string>>(new Set())

let initialized = false

export function useWorkspaceManager() {
  const currentWorkspace = computed(() =>
    workspaces.value.find(ws => ws.id === currentWorkspaceId.value) || null
  )

  const breadcrumbs = computed(() => {
    const parts = currentPath.value ? currentPath.value.split('/').filter(Boolean) : []
    const crumbs = [{ name: currentWorkspace.value?.name || 'Root', path: '' }]
    let acc = ''
    for (const part of parts) {
      acc = acc ? `${acc}/${part}` : part
      crumbs.push({ name: part, path: acc })
    }
    return crumbs
  })

  const sortedFiles = computed(() => {
    const items = [...files.value]
    // Search filter
    if (searchQuery.value) {
      const q = searchQuery.value.toLowerCase()
      return items.filter(f => f.name.toLowerCase().includes(q))
    }
    // Default: dirs first, then alphabetical
    return items.sort((a, b) => {
      if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1
      return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })
    })
  })

  async function init() {
    if (initialized) return
    initialized = true
    await loadWorkspaces()
    if (workspaces.value.length > 0 && !currentWorkspaceId.value) {
      const current = workspaces.value.find(ws => ws.is_current) || workspaces.value[0]
      await selectWorkspace(current.id)
    }
  }

  async function loadWorkspaces() {
    try {
      const data = await workspaceApi.listWorkspaces()
      workspaces.value = data.workspaces
    } catch (e: any) {
      error.value = `加载工作区失败: ${e.message}`
    }
  }

  async function selectWorkspace(wsId: string) {
    currentWorkspaceId.value = wsId
    currentPath.value = ''
    selectedPaths.value.clear()
    searchQuery.value = ''
    await loadFiles()
  }

  async function loadFiles() {
    if (!currentWorkspaceId.value) return
    loading.value = true
    error.value = ''
    try {
      const data = await workspaceApi.listFiles(currentWorkspaceId.value, currentPath.value)
      files.value = data.files
    } catch (e: any) {
      error.value = `加载文件失败: ${e.message}`
      files.value = []
    } finally {
      loading.value = false
    }
  }

  async function navigateTo(path: string) {
    currentPath.value = path
    selectedPaths.value.clear()
    searchQuery.value = ''
    await loadFiles()
  }

  async function createWorkspace(name: string, path: string) {
    try {
      const result = await workspaceApi.createWorkspace(name, path)
      workspaces.value.push(result.workspace)
      await selectWorkspace(result.workspace.id)
    } catch (e: any) {
      error.value = `创建工作区失败: ${e.message}`
    }
  }

  async function deleteWorkspace(wsId: string) {
    try {
      await workspaceApi.deleteWorkspace(wsId)
      workspaces.value = workspaces.value.filter(ws => ws.id !== wsId)
      if (currentWorkspaceId.value === wsId) {
        if (workspaces.value.length > 0) {
          await selectWorkspace(workspaces.value[0].id)
        } else {
          currentWorkspaceId.value = ''
          files.value = []
        }
      }
    } catch (e: any) {
      error.value = `删除工作区失败: ${e.message}`
    }
  }

  async function setCurrentWorkspace(wsId: string) {
    try {
      await workspaceApi.setCurrentWorkspace(wsId)
      // Update local state
      workspaces.value.forEach(ws => {
        ws.is_current = (ws.id === wsId)
      })
      await selectWorkspace(wsId)
    } catch (e: any) {
      error.value = `设置当前工作区失败: ${e.message}`
    }
  }

  async function createFolder(name: string) {
    if (!currentWorkspaceId.value || !name) return
    const folderPath = currentPath.value ? `${currentPath.value}/${name}` : name
    try {
      await workspaceApi.mkdir(currentWorkspaceId.value, folderPath)
      await loadFiles()
    } catch (e: any) {
      error.value = `创建文件夹失败: ${e.message}`
    }
  }

  async function deleteItem(path: string) {
    if (!currentWorkspaceId.value) return
    try {
      await workspaceApi.deleteFile(currentWorkspaceId.value, path)
      selectedPaths.value.delete(path)
      await loadFiles()
    } catch (e: any) {
      error.value = `删除失败: ${e.message}`
    }
  }

  async function renameItem(oldPath: string, newName: string) {
    if (!currentWorkspaceId.value) return
    try {
      await workspaceApi.rename(currentWorkspaceId.value, oldPath, newName)
      await loadFiles()
    } catch (e: any) {
      error.value = `重命名失败: ${e.message}`
    }
  }

  async function uploadFile(file: File) {
    if (!currentWorkspaceId.value) return
    try {
      await workspaceApi.upload(currentWorkspaceId.value, file, currentPath.value)
      await loadFiles()
    } catch (e: any) {
      error.value = `上传失败: ${e.message}`
    }
  }

  function toggleSelect(path: string) {
    if (selectedPaths.value.has(path)) {
      selectedPaths.value.delete(path)
    } else {
      selectedPaths.value.add(path)
    }
    // Trigger reactivity
    selectedPaths.value = new Set(selectedPaths.value)
  }

  async function searchAllWorkspaces(query: string) {
    if (!query.trim()) {
      return []
    }
    try {
      const data = await workspaceApi.searchAll(query)
      return data.results
    } catch (e: any) {
      error.value = `搜索失败：${e.message}`
      return []
    }
  }

  return {
    // State
    workspaces,
    currentWorkspaceId,
    currentWorkspace,
    currentPath,
    files,
    sortedFiles,
    loading,
    error,
    viewMode,
    searchQuery,
    selectedPaths,
    breadcrumbs,

    // Workspace operations
    init,
    loadWorkspaces,
    selectWorkspace,
    createWorkspace,
    deleteWorkspace,
    setCurrentWorkspace,

    // Navigation
    navigateTo,
    loadFiles,

    // File operations
    createFolder,
    deleteItem,
    renameItem,
    uploadFile,

    // Selection
    toggleSelect,

    // Search
    searchAllWorkspaces,
  }
}
