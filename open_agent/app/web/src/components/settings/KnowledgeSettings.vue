<template>
  <div class="tab-content">
    <div class="content-header">
      <h3>{{ t('知识库', 'Knowledge Base') }}</h3>
      <p>{{ t('基于 Markdown 的本地知识管理，支持双向链接、文件导入和知识图谱', 'Local Markdown-based knowledge management with backlinks, file import and graph') }}</p>
    </div>

    <div v-if="!viewerWikiId">
      <div class="knowledge-toolbar">
        <input v-model="searchQuery" :placeholder="t('搜索知识库...', 'Search wikis...')" class="search-input" />
        <button class="add-agent" @click="openCreateWiki">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          <span>{{ t('新建知识库', 'New Wiki') }}</span>
        </button>
      </div>

      <div v-if="filteredWikis.length === 0" class="empty-state">
        <span>{{ t('暂无知识库', 'No wikis yet') }}</span>
      </div>

      <div v-else class="agents-list">
        <div class="agent-card" v-for="wiki in filteredWikis" :key="wiki.id" @click="openWiki(wiki.id)">
          <div class="agent-avatar seal-avatar" :style="{ background: getWikiColor(wiki.id) }" :aria-label="wiki.displayName">
            <span class="seal-avatar-body">
              <span class="seal-avatar-face">
                <span class="seal-avatar-eye left"></span>
                <span class="seal-avatar-eye right"></span>
                <span class="seal-avatar-nose"></span>
              </span>
              <span class="seal-avatar-flipper left"></span>
              <span class="seal-avatar-flipper right"></span>
            </span>
          </div>
          <div class="agent-info">
            <h4>{{ wiki.displayName }}</h4>
            <p class="agent-model" v-if="wiki.description">{{ wiki.description.slice(0, 80) }}</p>
            <p class="agent-steps">{{ wiki.pagesCount || 0 }} {{ t('页', 'pages') }} · {{ formatDate(wiki.updatedAt) }}</p>
          </div>
          <div class="agent-actions">
            <button class="btn-icon btn-delete" @click.stop="removeWiki(wiki)" :title="t('删除', 'Delete')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3,6 5,6 21,6"/><path d="M19,6v14a2,2,0,0,1-2,2H7a2,2,0,0,1-2-2V6m3,0V4a2,2,0,0,1,2-2h4a2,2,0,0,1,2,2v2"/></svg>
            </button>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="wiki-detail">
      <div class="detail-header">
        <button class="btn-back" @click="closeWiki">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 12H5"/><path d="M12 19l-7-7 7-7"/></svg>
          <span>{{ t('返回列表', 'Back to list') }}</span>
        </button>
        <div class="detail-actions">
          <label class="add-agent small">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            <span>{{ t('导入文件', 'Import') }}</span>
            <input type="file" :accept="acceptExtensions" multiple hidden @change="handleImport" />
          </label>
          <button class="add-agent small" @click="newPage">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            <span>{{ t('新建页面', 'New Page') }}</span>
          </button>
        </div>
      </div>

      <h4 class="wiki-title">{{ activeWikiName }}</h4>

      <div v-if="!editingPageId">
        <div v-if="viewerPages.length === 0" class="empty-state">
          <span>{{ t('暂无页面，请新建或导入文件', 'No pages yet. Create one or import files.') }}</span>
        </div>

        <div v-else class="agents-list">
          <div class="agent-card" v-for="page in viewerPages" :key="page.id" @click="editPage(page)">
            <div class="agent-avatar page-avatar">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            </div>
            <div class="agent-info">
              <h4>{{ page.title }}</h4>
              <p class="agent-model">
                <span v-if="page.tags.length" class="page-tags">{{ page.tags.slice(0, 4).join(', ') }}</span>
                <span v-else class="page-tags empty">{{ t('无标签', 'No tags') }}</span>
              </p>
              <p class="agent-steps">{{ page.wordCount || 0 }} {{ t('字', 'chars') }} · {{ formatDate(page.updatedAt) }}</p>
            </div>
            <div class="agent-actions">
              <button class="btn-icon" @click.stop="editPage(page)" :title="t('编辑', 'Edit')">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
              </button>
              <button class="btn-icon btn-delete" @click.stop="removePage(page)" :title="t('删除', 'Delete')">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3,6 5,6 21,6"/><path d="M19,6v14a2,2,0,0,1-2,2H7a2,2,0,0,1-2-2V6m3,0V4a2,2,0,0,1,2-2h4a2,2,0,0,1,2,2v2"/></svg>
              </button>
            </div>
          </div>
        </div>
      </div>

      <div v-else class="page-editor">
        <div class="form-group">
          <label>{{ t('标题', 'Title') }}</label>
          <input v-model="pageDraft.title" :placeholder="t('页面标题', 'Page title')" />
        </div>
        <div class="form-group">
          <label>{{ t('标签', 'Tags') }}</label>
          <input v-model="pageDraft.tags" :placeholder="t('标签1, 标签2', 'tag1, tag2')" />
        </div>
        <div class="form-group">
          <label>{{ t('内容', 'Content') }} <small>(Markdown)</small></label>
          <textarea v-model="pageDraft.content" :placeholder="t('Markdown 内容...', 'Markdown content...')" rows="14" class="editor-area" />
        </div>
        <div class="editor-actions">
          <button class="btn-cancel" @click="closeEditor">{{ t('取消', 'Cancel') }}</button>
          <button class="btn-save" @click="savePage" :disabled="!pageDraft.title.trim()">{{ t('保存', 'Save') }}</button>
        </div>
      </div>

      <details class="graph-section" v-if="!editingPageId && graph.nodes.length">
        <summary class="graph-summary">{{ t('知识图谱', 'Knowledge Graph') }} ({{ graph.nodes.length }} {{ t('节点', 'nodes') }}, {{ graph.edges.length }} {{ t('边', 'edges') }})</summary>
        <div class="graph-preview">
          <span class="graph-node" v-for="node in graph.nodes.slice(0, 24)" :key="node.id" :class="node.type">{{ node.label.slice(0, 18) }}</span>
        </div>
      </details>
    </div>

    <div class="modal-overlay" v-if="showCreateModal" @click="showCreateModal = false">
      <div class="modal" @click.stop>
        <div class="modal-header">
          <h3>{{ t('新建知识库', 'New Wiki') }}</h3>
          <button class="btn-close" @click="showCreateModal = false">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>{{ t('名称', 'Name') }}</label>
            <input v-model="createDraft.displayName" :placeholder="t('知识库名称', 'Wiki name')" @keydown.enter="createWiki" />
          </div>
          <div class="form-group">
            <label>{{ t('描述', 'Description') }}</label>
            <textarea v-model="createDraft.description" :placeholder="t('可选描述', 'Optional description')" rows="3" />
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn-cancel" @click="showCreateModal = false">{{ t('取消', 'Cancel') }}</button>
          <button class="btn-save" @click="createWiki" :disabled="!createDraft.displayName.trim()">{{ t('创建', 'Create') }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import {
  loadLocalWikis, loadLocalPages, createWikiLocal, deleteWikiLocal,
  savePageLocal, deletePageLocal, buildKnowledgeGraph, importFileContent,
} from '@/services/knowledge'
import type { KnowledgeWiki, KnowledgePage, KnowledgeGraph } from '@/services/knowledge'

const settingsStore = useSettingsStore()

function t(zh: string, en: string): string { return settingsStore.t(zh, en) }

const wikis = ref<KnowledgeWiki[]>(loadLocalWikis())
const pages = ref<KnowledgePage[]>(loadLocalPages())
const viewerWikiId = ref('')
const editingPageId = ref('')
const searchQuery = ref('')
const showCreateModal = ref(false)
const createDraft = reactive({ displayName: '', description: '' })
const pageDraft = reactive({ id: '', title: '', tags: '', content: '' })
const acceptExtensions = '.md,.markdown,.txt,.json,.csv,.html,.htm,.xml'

const activeWikiName = computed(() => {
  const w = wikis.value.find((i) => i.id === viewerWikiId.value)
  return w?.displayName || ''
})

const viewerPages = computed(() => pages.value.filter((p) => p.wikiId === viewerWikiId.value))

const filteredWikis = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  return wikis.value.filter((w) => !q || w.displayName.toLowerCase().includes(q) || (w.description || '').toLowerCase().includes(q))
})

const graph = computed<KnowledgeGraph>(() => buildKnowledgeGraph(wikis.value, pages.value, viewerWikiId.value || undefined))

function formatDate(date: string): string {
  try { return new Date(date).toLocaleDateString() } catch { return date }
}

function getWikiColor(id: string): string {
  const colors = ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4']
  return colors[id.length % colors.length]
}

function openCreateWiki() {
  createDraft.displayName = ''
  createDraft.description = ''
  showCreateModal.value = true
}

function createWiki() {
  if (!createDraft.displayName.trim()) return
  const wiki = createWikiLocal({ displayName: createDraft.displayName.trim(), description: createDraft.description.trim() })
  showCreateModal.value = false
  wikis.value = loadLocalWikis()
  openWiki(wiki.id)
}

function openWiki(id: string) {
  viewerWikiId.value = id
  editingPageId.value = ''
  pages.value = loadLocalPages()
}

function closeWiki() { viewerWikiId.value = ''; editingPageId.value = '' }

function removeWiki(wiki: KnowledgeWiki) {
  if (!confirm(t(`确定删除「${wiki.displayName}」？`, `Delete "${wiki.displayName}"?`))) return
  deleteWikiLocal(wiki.id)
  if (viewerWikiId.value === wiki.id) viewerWikiId.value = ''
  wikis.value = loadLocalWikis()
  pages.value = loadLocalPages()
}

function newPage() {
  editingPageId.value = 'new'
  pageDraft.id = ''; pageDraft.title = ''; pageDraft.tags = ''; pageDraft.content = ''
}

function editPage(page: KnowledgePage) {
  editingPageId.value = page.id
  pageDraft.id = page.id
  pageDraft.title = page.title
  pageDraft.tags = (page.tags || []).join(', ')
  pageDraft.content = page.content
}

function savePage() {
  if (!pageDraft.title.trim() || !viewerWikiId.value) return
  savePageLocal({ wikiId: viewerWikiId.value, title: pageDraft.title.trim(), content: pageDraft.content, id: pageDraft.id || undefined, tags: pageDraft.tags.split(',').map((t) => t.trim()).filter(Boolean) })
  editingPageId.value = ''
  pages.value = loadLocalPages()
  wikis.value = loadLocalWikis()
}

function closeEditor() { editingPageId.value = '' }

function removePage(page: KnowledgePage) {
  if (!confirm(t(`删除「${page.title}」？`, `Delete "${page.title}"?`))) return
  deletePageLocal(page.id)
  pages.value = loadLocalPages()
}

function handleImport(event: Event) {
  const input = event.target as HTMLInputElement
  const files = input.files
  if (!files || !viewerWikiId.value) return
  for (const file of Array.from(files)) {
    const reader = new FileReader()
    reader.onload = () => {
      importFileContent(viewerWikiId.value, file.name, String(reader.result || ''))
      pages.value = loadLocalPages()
      wikis.value = loadLocalWikis()
    }
    reader.readAsText(file)
  }
  input.value = ''
}
</script>

<style scoped>
.tab-content { display: flex; flex-direction: column; gap: 20px; }
.content-header { margin-bottom: 8px; }
.content-header h3 { font-size: 16px; font-weight: 600; color: var(--text-primary); margin: 0 0 4px 0; }
.content-header p { font-size: 13px; color: var(--text-muted); margin: 0; }

.knowledge-toolbar { display: flex; gap: 12px; align-items: center; margin-bottom: 4px; }
.search-input { flex: 1; height: 36px; padding: 0 13px; border: 1px solid var(--border-color); border-radius: 10px; background: var(--glass-bg-strong); color: var(--text-primary); font-size: 13px; box-shadow: inset 0 1px 0 rgba(255,255,255,0.35); }
.search-input:focus { outline: none; border-color: var(--primary-color); }

.add-agent { display: flex; align-items: center; justify-content: center; gap: 6px; padding: 8px 16px; background: transparent; border: 1px dashed var(--border-color); border-radius: 12px; color: var(--text-secondary); cursor: pointer; font-size: 13px; transition: all 0.2s; white-space: nowrap; }
.add-agent:hover { border-color: var(--primary-color); color: var(--primary-color); }
.add-agent.small { padding: 6px 12px; border-radius: 10px; font-size: 12px; }
.add-agent svg { width: 18px; height: 18px; }
.add-agent.small svg { width: 16px; height: 16px; }
.add-agent span { font-size: 13px; }

.agents-list { display: flex; flex-direction: column; gap: 12px; }
.agent-card { display: flex; align-items: center; gap: 12px; padding: 16px; background: var(--main-bg); border: 1px solid var(--border-color); border-radius: 12px; cursor: pointer; transition: border-color 0.2s; }
.agent-card:hover { border-color: var(--primary-color); }
.agent-avatar { width: 48px; height: 48px; border-radius: 14px; color: white; display: flex; align-items: center; justify-content: center; font-size: 20px; font-weight: 600; flex-shrink: 0; }
.agent-info { flex: 1; min-width: 0; }
.agent-info h4 { font-size: 14px; font-weight: 600; color: var(--text-primary); margin: 0 0 4px 0; }
.agent-info .agent-model { font-size: 12px; color: var(--text-muted); margin: 0 0 2px 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 360px; }
.agent-info .agent-steps { font-size: 12px; color: var(--text-muted); margin: 0; }
.agent-actions { display: flex; gap: 4px; }
.btn-icon { width: 32px; height: 32px; border-radius: 8px; border: none; background: transparent; color: var(--text-secondary); cursor: pointer; display: flex; align-items: center; justify-content: center; }
.btn-icon:hover { background: var(--hover-bg); }
.btn-icon svg { width: 16px; height: 16px; }
.btn-icon.btn-delete:hover { background: rgba(239,68,68,0.1); color: #ef4444; }

.page-avatar { background: var(--hover-bg); color: var(--text-secondary); }
.page-avatar svg { width: 22px; height: 22px; }
.page-tags { color: var(--primary-color); }
.page-tags.empty { color: var(--text-muted); }

.empty-state { display: flex; align-items: center; justify-content: center; padding: 40px; border: 1px solid var(--border-color); border-radius: 12px; background: var(--main-bg); color: var(--text-muted); font-size: 14px; }

.detail-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.detail-actions { display: flex; gap: 8px; align-items: center; }
.btn-back { display: flex; align-items: center; gap: 4px; border: none; background: transparent; color: var(--text-secondary); cursor: pointer; font-size: 13px; padding: 4px 0; transition: color 0.15s; }
.btn-back:hover { color: var(--primary-color); }
.btn-back svg { width: 18px; height: 18px; }
.wiki-title { font-size: 15px; font-weight: 600; color: var(--text-primary); margin: 0 0 12px 0; }

.page-editor { display: flex; flex-direction: column; gap: 14px; background: var(--main-bg); border: 1px solid var(--border-color); border-radius: 12px; padding: 16px; }
.form-group { display: flex; flex-direction: column; gap: 4px; }
.form-group label { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.form-group label small { font-weight: 400; color: var(--text-muted); }
.form-group input, .form-group textarea, .form-group select { width: 100%; padding: 8px 12px; border: 1px solid var(--border-color); border-radius: 8px; background: var(--glass-bg-strong); color: var(--text-primary); font-size: 13px; box-sizing: border-box; }
.form-group input:focus, .form-group textarea:focus, .form-group select:focus { outline: none; border-color: var(--primary-color); }
.editor-area { font-family: 'Cascadia Code', 'Fira Code', monospace; font-size: 12px; line-height: 1.6; min-height: 300px; resize: vertical; }
.editor-actions { display: flex; justify-content: flex-end; gap: 12px; }

.btn-cancel { padding: 10px 20px; background: transparent; border: 1px solid var(--border-color); border-radius: 8px; color: var(--text-secondary); cursor: pointer; font-size: 14px; transition: all 0.2s; }
.btn-cancel:hover { background: var(--hover-bg); color: var(--text-primary); }
.btn-save { padding: 10px 20px; background: var(--primary-color); border: none; border-radius: 8px; color: white; font-size: 14px; font-weight: 600; cursor: pointer; transition: opacity 0.2s; }
.btn-save:hover:not(:disabled) { opacity: 0.9; }
.btn-save:disabled { opacity: 0.6; cursor: not-allowed; }

.graph-section { margin-top: 12px; }
.graph-summary { font-size: 13px; font-weight: 600; color: var(--text-secondary); cursor: pointer; padding: 6px 0; user-select: none; }
.graph-preview { display: flex; flex-wrap: wrap; gap: 6px; padding: 12px; margin-top: 8px; border: 1px solid var(--border-color); border-radius: 12px; background: var(--main-bg); }
.graph-node { padding: 4px 10px; border-radius: 8px; font-size: 12px; font-weight: 500; }
.graph-node.wiki { background: rgba(59,130,246,0.12); color: #2563eb; }
.graph-node.page { background: rgba(16,185,129,0.12); color: #059669; }
.graph-node.source { background: rgba(245,158,11,0.12); color: #d97706; }
.graph-node.entity { background: rgba(139,92,246,0.12); color: #7c3aed; }
.graph-node.tag { background: rgba(239,68,68,0.1); color: #dc2626; }

/* Modal styles matching AgentsSettings */
.modal-overlay { position: fixed; inset: 0; z-index: 1000; display: flex; align-items: center; justify-content: center; background: rgba(0,0,0,0.45); backdrop-filter: blur(4px); }
.modal { background: var(--main-bg); border-radius: 14px; min-width: 420px; max-width: 520px; box-shadow: 0 20px 60px rgba(0,0,0,0.18); overflow: hidden; }
.modal-header { display: flex; align-items: center; justify-content: space-between; padding: 18px 22px; border-bottom: 1px solid var(--border-color); }
.modal-header h3 { font-size: 16px; font-weight: 700; color: var(--text-primary); margin: 0; }
.modal-body { display: flex; flex-direction: column; gap: 16px; padding: 20px 22px; }
.modal-body .form-group textarea { resize: vertical; min-height: 60px; }
.modal-footer { display: flex; justify-content: flex-end; gap: 12px; padding: 16px 22px; border-top: 1px solid var(--border-color); }
.btn-close { width: 32px; height: 32px; border-radius: 10px; border: 1px solid var(--border-color); background: var(--glass-bg-strong); color: var(--text-primary); cursor: pointer; display: flex; align-items: center; justify-content: center; box-shadow: inset 0 1px 0 var(--glass-border), 0 8px 18px rgba(17,24,39,0.08); transition: all 0.2s; }
.btn-close:hover { background: rgba(239,68,68,0.12); border-color: rgba(239,68,68,0.42); color: #ef4444; transform: translateY(-1px); }
.btn-close svg { width: 18px; height: 18px; }

/* Seal avatar (mirrored from App.vue) */
.seal-avatar { position: relative; overflow: visible; background: linear-gradient(145deg, #dff3ff 0%, #9cc4df 100%) !important; box-shadow: inset 0 1px 0 rgba(255,255,255,0.58), 0 8px 18px rgba(72,104,132,0.16); }
.seal-avatar-body { position: relative; width: 72%; height: 58%; border-radius: 60% 58% 52% 54%; background: linear-gradient(145deg, #f7fbff 0%, #cbddeb 62%, #91a9bd 100%); box-shadow: inset 0 1px 3px rgba(255,255,255,0.85), 0 3px 8px rgba(72,104,132,0.18); }
.seal-avatar-face { position: absolute; top: 24%; right: 17%; width: 45%; height: 46%; }
.seal-avatar-eye { position: absolute; top: 6%; width: 18%; height: 18%; border-radius: 50%; background: #263746; }
.seal-avatar-eye.left { left: 8%; }
.seal-avatar-eye.right { right: 8%; }
.seal-avatar-nose { position: absolute; left: 42%; top: 50%; width: 20%; height: 16%; border-radius: 50%; background: #38495a; }
.seal-avatar-flipper { position: absolute; bottom: -14%; width: 32%; height: 30%; border-radius: 999px; background: #91a9bd; }
.seal-avatar-flipper.left { left: 8%; transform: rotate(-24deg); }
.seal-avatar-flipper.right { right: 8%; transform: rotate(24deg); }
</style>
