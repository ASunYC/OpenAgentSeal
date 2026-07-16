import { ref } from 'vue'
import type { ChatAttachment } from '@/types'
import {
  createQueueItem,
  markQueueItemFailed,
  markQueueItemSending,
  parseStoredQueue,
  retryQueueItem,
  selectNextQueueItem,
  serializeQueue,
  type MessageQueueScope,
  type QueueMessageKind,
  type QueuedComposerMessage,
} from '@/models/messageQueue'

const STORAGE_PREFIX = 'open_agent_seal_message_queue_v2'
const LEGACY_STORAGE_PREFIX = 'open_agent_seal_message_queue_v1'

export type { QueuedComposerMessage } from '@/models/messageQueue'

function cloneAttachments(attachments: ChatAttachment[]): ChatAttachment[] {
  return attachments.map((attachment) => ({ ...attachment }))
}

function safeStorageKey(scope: MessageQueueScope): string {
  return `${STORAGE_PREFIX}:${encodeURIComponent(scope.agentId || 'main')}:${encodeURIComponent(scope.sessionId || '')}`
}

function normalizeScope(scope: MessageQueueScope): MessageQueueScope {
  return {
    agentId: scope.agentId || 'main',
    sessionId: scope.sessionId || '',
  }
}

export function useMessageQueue() {
  const queuedMessages = ref<QueuedComposerMessage[]>([])
  const queueScope = ref<MessageQueueScope>({ agentId: 'main', sessionId: '' })

  function isCurrentScope(scope: MessageQueueScope): boolean {
    const normalized = normalizeScope(scope)
    return normalized.agentId === queueScope.value.agentId
      && normalized.sessionId === queueScope.value.sessionId
  }

  function persistItems(scope: MessageQueueScope, items: QueuedComposerMessage[]) {
    if (typeof localStorage === 'undefined') return
    const key = safeStorageKey(normalizeScope(scope))
    if (items.length === 0) {
      localStorage.removeItem(key)
    } else {
      localStorage.setItem(key, serializeQueue(items))
    }
  }

  function persist() {
    persistItems(queueScope.value, queuedMessages.value)
  }

  function load(scope = queueScope.value) {
    queueScope.value = normalizeScope(scope)
    if (typeof localStorage === 'undefined') {
      queuedMessages.value = []
      return
    }

    const key = safeStorageKey(queueScope.value)
    const stored = localStorage.getItem(key)
    queuedMessages.value = parseStoredQueue(stored, queueScope.value)

    if (!stored && queueScope.value.sessionId) {
      const unscoped = { agentId: queueScope.value.agentId, sessionId: '' }
      const unscopedKey = safeStorageKey(unscoped)
      const restored = parseStoredQueue(localStorage.getItem(unscopedKey), unscoped)
      if (restored.length > 0) {
        queuedMessages.value = restored.map(item => ({ ...item, sessionId: queueScope.value.sessionId }))
        persist()
        localStorage.removeItem(unscopedKey)
      }
    } else if (!stored && !queueScope.value.sessionId) {
      const legacyKey = `${LEGACY_STORAGE_PREFIX}:${queueScope.value.agentId}`
      queuedMessages.value = parseStoredQueue(localStorage.getItem(legacyKey), queueScope.value)
      if (queuedMessages.value.length > 0) {
        persist()
        localStorage.removeItem(legacyKey)
      }
    }
  }

  function setQueueScope(agentId: string, sessionId = '') {
    const nextScope = { agentId: agentId || 'main', sessionId: sessionId || '' }
    if (
      nextScope.agentId === queueScope.value.agentId
      && nextScope.sessionId === queueScope.value.sessionId
    ) return
    persist()
    load(nextScope)
  }

  function queueMessage(
    content: string,
    attachments: ChatAttachment[] = [],
    kind: QueueMessageKind = 'normal',
  ): boolean {
    const nextContent = content.trim()
    const nextAttachments = cloneAttachments(attachments)
    if (!nextContent && nextAttachments.length === 0) return false

    queuedMessages.value.push(createQueueItem({
      content: nextContent,
      attachments: nextAttachments,
      kind,
      scope: queueScope.value,
    }))
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

  function removeQueuedMessage(id: string, scope = queueScope.value) {
    const normalized = normalizeScope(scope)
    if (isCurrentScope(normalized)) {
      queuedMessages.value = queuedMessages.value.filter((item) => item.id !== id)
      persist()
      return
    }
    if (typeof localStorage === 'undefined') return
    const items = parseStoredQueue(localStorage.getItem(safeStorageKey(normalized)), normalized)
    persistItems(normalized, items.filter(item => item.id !== id))
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
    return selectNextQueueItem(queuedMessages.value)
  }

  function markQueuedMessageSending(id: string): QueuedComposerMessage | null {
    const index = queuedMessages.value.findIndex(item => item.id === id)
    if (index < 0) return null
    const next = markQueueItemSending(queuedMessages.value[index])
    queuedMessages.value[index] = next
    persist()
    return { ...next, attachments: cloneAttachments(next.attachments) }
  }

  function markQueuedMessageFailed(id: string, error: string, scope = queueScope.value) {
    const normalized = normalizeScope(scope)
    if (isCurrentScope(normalized)) {
      const index = queuedMessages.value.findIndex(item => item.id === id)
      if (index < 0) return
      queuedMessages.value[index] = markQueueItemFailed(queuedMessages.value[index], error)
      persist()
      return
    }
    if (typeof localStorage === 'undefined') return
    const items = parseStoredQueue(localStorage.getItem(safeStorageKey(normalized)), normalized)
    const index = items.findIndex(item => item.id === id)
    if (index < 0) return
    items[index] = markQueueItemFailed(items[index], error)
    persistItems(normalized, items)
  }

  function retryQueuedMessage(id: string) {
    const index = queuedMessages.value.findIndex(item => item.id === id)
    if (index < 0) return
    queuedMessages.value[index] = retryQueueItem(queuedMessages.value[index])
    persist()
  }

  function clearQueue() {
    queuedMessages.value = []
    persist()
  }

  load(queueScope.value)

  return {
    queuedMessages,
    queueScope,
    setQueueScope,
    queueMessage,
    editQueuedMessage,
    cancelQueuedMessageEdit,
    saveQueuedMessageEdit,
    removeQueuedMessage,
    takeQueuedMessage,
    nextQueuedMessage,
    markQueuedMessageSending,
    markQueuedMessageFailed,
    retryQueuedMessage,
    clearQueue,
  }
}
