import { ref } from 'vue'
import type { ChatAttachment } from '@/types'

const STORAGE_PREFIX = 'open_agent_seal_message_queue_v1'

export interface QueuedComposerMessage {
  id: string
  content: string
  draftContent: string
  attachments: ChatAttachment[]
  editing: boolean
  createdAt: string
}

interface StoredQueuedComposerMessage {
  id?: string
  content?: string
  draftContent?: string
  attachments?: ChatAttachment[]
  createdAt?: string
}

function cloneAttachments(attachments: ChatAttachment[]): ChatAttachment[] {
  return attachments.map((attachment) => ({ ...attachment }))
}

function generateQueueId(): string {
  return `queue_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

function safeStorageKey(scopeId: string): string {
  return `${STORAGE_PREFIX}:${scopeId || 'main'}`
}

function normalizeStoredItem(item: StoredQueuedComposerMessage): QueuedComposerMessage | null {
  const content = String(item.content || '').trim()
  const attachments = Array.isArray(item.attachments) ? cloneAttachments(item.attachments) : []
  if (!content && attachments.length === 0) return null

  return {
    id: item.id || generateQueueId(),
    content,
    draftContent: String(item.draftContent || content),
    attachments,
    editing: false,
    createdAt: item.createdAt || new Date().toISOString(),
  }
}

export function useMessageQueue() {
  const queuedMessages = ref<QueuedComposerMessage[]>([])
  const queueScopeId = ref('main')

  function persist() {
    if (typeof localStorage === 'undefined') return
    const storageItems = queuedMessages.value.map((item) => ({
      id: item.id,
      content: item.content,
      draftContent: item.draftContent,
      attachments: cloneAttachments(item.attachments),
      createdAt: item.createdAt,
    }))
    const key = safeStorageKey(queueScopeId.value)
    if (storageItems.length === 0) {
      localStorage.removeItem(key)
      return
    }
    localStorage.setItem(key, JSON.stringify(storageItems))
  }

  function load(scopeId = queueScopeId.value) {
    queueScopeId.value = scopeId || 'main'
    if (typeof localStorage === 'undefined') {
      queuedMessages.value = []
      return
    }

    try {
      const raw = localStorage.getItem(safeStorageKey(queueScopeId.value))
      const parsed = raw ? JSON.parse(raw) : []
      queuedMessages.value = Array.isArray(parsed)
        ? parsed.map(normalizeStoredItem).filter((item): item is QueuedComposerMessage => Boolean(item))
        : []
    } catch (error) {
      console.error('Failed to load queued messages:', error)
      queuedMessages.value = []
    }
  }

  function setQueueScope(scopeId: string) {
    const nextScope = scopeId || 'main'
    if (nextScope === queueScopeId.value) return
    persist()
    load(nextScope)
  }

  function queueMessage(content: string, attachments: ChatAttachment[] = []): boolean {
    const nextContent = content.trim()
    const nextAttachments = cloneAttachments(attachments)
    if (!nextContent && nextAttachments.length === 0) return false

    queuedMessages.value.push({
      id: generateQueueId(),
      content: nextContent,
      draftContent: nextContent,
      attachments: nextAttachments,
      editing: false,
      createdAt: new Date().toISOString(),
    })
    persist()
    return true
  }

  function editQueuedMessage(item: QueuedComposerMessage) {
    item.draftContent = item.content
    item.editing = true
    persist()
  }

  function cancelQueuedMessageEdit(item: QueuedComposerMessage) {
    item.draftContent = item.content
    item.editing = false
    persist()
  }

  function saveQueuedMessageEdit(item: QueuedComposerMessage) {
    const nextContent = item.draftContent.trim()
    if (!nextContent && item.attachments.length === 0) {
      removeQueuedMessage(item.id)
      return
    }
    item.content = nextContent
    item.draftContent = nextContent
    item.editing = false
    persist()
  }

  function removeQueuedMessage(id: string) {
    queuedMessages.value = queuedMessages.value.filter((item) => item.id !== id)
    persist()
  }

  function takeQueuedMessage(id: string): QueuedComposerMessage | null {
    const item = queuedMessages.value.find((queued) => queued.id === id) || null
    if (!item) return null
    removeQueuedMessage(id)
    return {
      ...item,
      attachments: cloneAttachments(item.attachments),
      editing: false,
    }
  }

  function nextQueuedMessage(): QueuedComposerMessage | null {
    return queuedMessages.value.find((item) => !item.editing) || null
  }

  function clearQueue() {
    queuedMessages.value = []
    persist()
  }

  load(queueScopeId.value)

  return {
    queuedMessages,
    queueScopeId,
    setQueueScope,
    queueMessage,
    editQueuedMessage,
    cancelQueuedMessageEdit,
    saveQueuedMessageEdit,
    removeQueuedMessage,
    takeQueuedMessage,
    nextQueuedMessage,
    clearQueue,
  }
}
