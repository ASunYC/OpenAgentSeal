<template>
  <div class="tab-content knowledge-tab">
    <div class="content-header">
      <h3>{{ t('知识库', 'Knowledge Base') }}</h3>
      <p>{{ t('基于 Markdown 的本地知识管理，支持双向链接、文件导入和知识图谱', 'Local Markdown-based knowledge management with backlinks, file import and graph') }}</p>
    </div>

    <!-- Stats bar -->
    <div class="knowledge-stats" v-if="wikis.length">
      <span class="stat-badge">{{ wikis.length }} {{ t('个知识库', ' wikis') }}</span>
      <span class="stat-badge">{{ totalPages }} {{ t('页', ' pages') }}</span>
    </div>

    <!-- Top actions -->
    <div class="knowledge-actions">
      <input v-model="searchQuery" :placeholder="t('搜索 wiki 或页面', 'Search wikis or pages')" class="search-input" />
      <button class="btn-primary" @click="openCreateWiki">{{ t('新建知识库', 'New Wiki') }}</button>
    </div>

    <!-- Create wiki modal -->
    <div class="modal-overlay" v-if="showCreateModal" @click="showCreateModal = false">
      <div class="modal" @click.stop>
        <div class="modal-header">
          <h3>{{ t('新建知识库', 'New Wiki') }}</h3>
          <button class="btn-close" @click="showCreateModal = false">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>{{ t('名称', 'Name') }}</label>
            <input v-model="createDraft.displayName" :placeholder="t('知识库名称', 'Wiki name')" @keydown.enter="createWiki" />
          </div>
          <div class="form-group">
            <label>{{ t('描述', 'Description') }}</label>
            <textarea v-model="createDraft.description" :placeholder="t('可选描述', 'Optional description')" rows="2" />
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn-cancel" @click="showCreateModal = false">{{ t('取消', 'Cancel') }}</button>
          <button class="btn-save" @click="createWiki" :disabled="!createDraft.displayName.trim()">{{ t('创建', 'Create') }}</button>
        </div>
      </div>
    </div>

    <!-- Wiki list -->
    <div class="wiki-list" v-if="!viewerWikiId">
      <div v-if="filteredWikis.length === 0" class="empty-state">
        <p>{{ t('暂无知识库，点击上方按钮创建', 'No wikis yet. Create one above.') }}</p>
      </div>
      <div class="wiki-card" v-for="wiki in filteredWikis" :key="wiki.id" @click="openWiki(wiki.id)">
        <div class="wiki-card-header">
          <h4>{{ wiki.displayName }}</h4>
          <span class="wiki-category">{{ wiki.category }}</span>
        </div>
        <p class="wiki-desc" v-if="wiki.description">{{ wiki.description.slice(0, 80) }}</p>
        <div class="wiki-meta">
          <span>{{ wiki.pagesCount || 0 }} {{ t('页', ' pages') }}</span>
          <span>{{ new Date(wiki.updatedAt).toLocaleDateString() }}</span>
        </div>
        <button class="wiki-delete" @click.stop="removeWiki(wiki)" :title="t('删除', 'Delete')">
          <svg viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2"><polyline points="3,6 5,6 21,6"/><path d="M19,6v14a2,2,0,0,1-2,2H7a2,2,0,0,1-2-2V6m3,0V4a2,2,0,0,1,2-2h4a2,2,0,0,1,2,2v2"/></svg>
        </button>
      </div>
    </div>

    <!-- Wiki detail / Page editor -->
    <div class="wiki-detail" v-else>
      <div class="detail-header">
        <button class="btn-back" @click="closeWiki">{{ t('← 返回', '← Back') }}</button>
        <div>
          <button class="btn-primary small" @click="newPage">{{ t('新建页面', 'New Page') }}</button>
          <label class="btn-primary small import-btn" style="margin-left:8px">
            {{ t('导入文件', 'Import') }}
            <input type="file" :accept="acceptExtensions" multiple hidden @change="handleImport" />
          </label>
        </div>
      </div>

      <!-- Page list -->
      <div class="page-list" v-if="!editingPageId">
        <div v-if="viewerPages.length === 0" class="empty-state">
          <p>{{ t('暂无页面', 'No pages yet') }}</p>
        </div>
        <div class="page-card" v-for="page in viewerPages" :key="page.id" @click="editPage(page)">
          <h5>{{ page.title }}</h5>
          <div class="page-meta">
            <span class="page-tags" v-if="page.tags.length">{{ page.tags.slice(0, 3).join(', ') }}</span>
            <span>{{ new Date(page.updatedAt).toLocaleDateString() }}</span>
            <span>{{ page.wordCount || 0 }} {{ t('字', ' chars') }}</span>
          </div>
          <button class="page-delete" @click.stop="removePage(page)" :title="t('删除', 'Delete')">
            <svg viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2" width="14" height="14"><polyline points="3,6 5,6 21,6"/><path d="M19,6v14a2,2,0,0,1-2,2H7a2,2,0,0,1-2-2V6m3,0V4a2,2,0,0,1,2-2h4a2,2,0,0,1,2,2v2"/></svg>
          </button>
        </div>
      </div>

      <!-- Page editor -->
      <div class="page-editor" v-else>
        <div class="form-group">
          <label>{{ t('标题', 'Title') }}</label>
          <input v-model="pageDraft.title" :placeholder="t('页面标题', 'Page title')" />
        </div>
        <div class="form-group">
          <label>{{ t('标签', 'Tags') }} <small>({{ t('逗号分隔', 'comma separated') }})</small></label>
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
    </div>

    <!-- Knowledge graph (simple preview) -->
    <div class="graph-section" v-if="viewerWikiId && !editingPageId">
      <details>
        <summary class="graph-summary">{{ t('知识图谱预览', 'Knowledge Graph Preview') }} ({{ graph.nodes.length }} {{ t('节点', 'nodes') }}, {{ graph.edges.length }} {{ t('边', 'edges') }})</summary>
        <div class="graph-preview">
          <div v-for="node in graph.nodes.slice(0, 20)" :key="node.id" class="graph-node" :class="node.type">
            <span class="node-label">{{ node.label.slice(0, 20) }}</span>
            <span class="node-type">{{ node.type }}</span>
          </div>
        </div>
      </details>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
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

const viewerPages = computed(() => pages.value.filter((p) => p.wikiId === viewerWikiId.value))
const totalPages = computed(() => wikis.value.reduce((s, w) => s + (w.pagesCount || 0), 0))

const filteredWikis = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  return wikis.value.filter((w) => !q || w.displayName.toLowerCase().includes(q) || w.description.toLowerCase().includes(q))
})

const graph = computed<KnowledgeGraph>(() => buildKnowledgeGraph(wikis.value, pages.value, viewerWikiId.value || undefined))

watch(wikis, (val) => localStorage.setItem('open-agent:wikis', JSON.stringify(val)), { deep: true })
watch(pages, (val) => localStorage.setItem('open-agent:pages', JSON.stringify(val)), { deep: true })

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

function closeWiki() {
  viewerWikiId.value = ''
  editingPageId.value = ''
}

function removeWiki(wiki: KnowledgeWiki) {
  if (!confirm(t(`确定删除「${wiki.displayName}」？`, `Delete "${wiki.displayName}"?`))) return
  deleteWikiLocal(wiki.id)
  if (viewerWikiId.value === wiki.id) viewerWikiId.value = ''
  wikis.value = loadLocalWikis()
  pages.value = loadLocalPages()
}

function newPage() {
  editingPageId.value = 'new'
  pageDraft.id = ''
  pageDraft.title = ''
  pageDraft.tags = ''
  pageDraft.content = ''
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
  savePageLocal({
    wikiId: viewerWikiId.value,
    title: pageDraft.title.trim(),
    content: pageDraft.content,
    id: pageDraft.id || undefined,
    tags: pageDraft.tags.split(',').map((t) => t.trim()).filter(Boolean),
  })
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
.knowledge-tab { gap: 16px; }

.knowledge-stats { display: flex; gap: 8px; flex-wrap: wrap; }
.stat-badge { padding: 4px 10px; border-radius: 999px; background: var(--primary-color); color: white; font-size: 12px; font-weight: 600; }

.knowledge-actions { display: flex; gap: 8px; align-items: center; }
.search-input { flex: 1; height: 36px; padding: 0 12px; border: 1px solid var(--border-color); border-radius: 10px; background: var(--glass-bg-strong); color: var(--text-primary); font-size: 13px; }
.search-input:focus { outline: none; border-color: var(--primary-color); }

.btn-primary { height: 36px; padding: 0 14px; border-radius: 10px; border: none; background: var(--primary-color); color: white; font-weight: 600; font-size: 13px; cursor: pointer; }
.btn-primary:hover { opacity: 0.9; }
.btn-primary.small { height: 30px; padding: 0 10px; font-size: 12px; border-radius: 8px; }
.btn-primary:disabled { opacity: 0.5; cursor: default; }

.wiki-list { display: flex; flex-direction: column; gap: 10px; }
.wiki-card { padding: 14px; border: 1px solid var(--border-color); border-radius: 12px; cursor: pointer; transition: border-color 0.2s; position: relative; }
.wiki-card:hover { border-color: var(--primary-color); }
.wiki-card-header { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.wiki-card-header h4 { font-size: 14px; font-weight: 600; margin: 0; color: var(--text-primary); }
.wiki-category { font-size: 11px; padding: 2px 6px; border-radius: 6px; background: var(--hover-bg); color: var(--text-muted); }
.wiki-desc { font-size: 12px; color: var(--text-muted); margin: 4px 0; }
.wiki-meta { display: flex; gap: 12px; font-size: 11px; color: var(--text-muted); }
.wiki-delete { position: absolute; right: 10px; top: 10px; width: 28px; height: 28px; border: none; background: transparent; cursor: pointer; border-radius: 6px; display: flex; align-items: center; justify-content: center; }
.wiki-delete:hover { background: rgba(239,68,68,0.1); }
.wiki-delete svg { width: 14px; height: 14px; }

.detail-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.btn-back { border: none; background: transparent; color: var(--primary-color); cursor: pointer; font-size: 13px; font-weight: 600; padding: 4px 0; }

.page-list { display: flex; flex-direction: column; gap: 8px; }
.page-card { padding: 10px 12px; border: 1px solid var(--border-color); border-radius: 10px; cursor: pointer; position: relative; }
.page-card:hover { border-color: var(--primary-color); }
.page-card h5 { font-size: 13px; font-weight: 600; margin: 0 0 4px 0; color: var(--text-primary); }
.page-meta { display: flex; gap: 10px; font-size: 11px; color: var(--text-muted); }
.page-tags { color: var(--primary-color); }
.page-delete { position: absolute; right: 8px; top: 8px; width: 24px; height: 24px; border: none; background: transparent; cursor: pointer; border-radius: 6px; display: flex; align-items: center; justify-content: center; }
.page-delete:hover { background: rgba(239,68,68,0.1); }

.editor-area { font-family: monospace; font-size: 13px; line-height: 1.5; }
.editor-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }

.import-btn { display: inline-flex; align-items: center; cursor: pointer; }

.graph-section { margin-top: 8px; }
.graph-summary { font-size: 13px; font-weight: 600; color: var(--text-secondary); cursor: pointer; padding: 6px 0; }
.graph-preview { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.graph-node { padding: 4px 8px; border-radius: 8px; font-size: 11px; display: flex; flex-direction: column; align-items: center; }
.graph-node.wiki { background: rgba(59,130,246,0.12); color: #2563eb; }
.graph-node.page { background: rgba(16,185,129,0.12); color: #059669; }
.graph-node.source { background: rgba(245,158,11,0.12); color: #d97706; }
.graph-node.entity { background: rgba(139,92,246,0.12); color: #7c3aed; }
.graph-node.tag { background: rgba(239,68,68,0.1); color: #dc2626; }
.node-type { font-size: 9px; opacity: 0.7; }
</style>
