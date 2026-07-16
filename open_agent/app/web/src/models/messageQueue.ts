import type { ChatAttachment } from '@/types'

export type QueueMessageKind = 'normal' | 'interrupt'
export type QueueMessageStatus = 'queued' | 'sending' | 'failed'

export interface MessageQueueScope {
  agentId: string
  sessionId: string
}

export interface QueuedComposerMessage {
  id: string
  content: string
  draftContent: string
  attachments: ChatAttachment[]
  editing: boolean
  createdAt: string
  kind: QueueMessageKind
  status: QueueMessageStatus
  error: string
  attemptCount: number
  agentId: string
  sessionId: string
}

interface QueueItemInput {
  content: string
  attachments?: ChatAttachment[]
  kind?: QueueMessageKind
  scope: MessageQueueScope
  now?: string
  id?: string
}

type StoredQueueItem = Partial<QueuedComposerMessage> | null

function cloneAttachments(attachments: ChatAttachment[] = []): ChatAttachment[] {
  return attachments.map(attachment => ({ ...attachment }))
}

function generateQueueId(): string {
  return `queue_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

export function createQueueItem(input: QueueItemInput): QueuedComposerMessage {
  const content = input.content.trim()
  return {
    id: input.id || generateQueueId(),
    content,
    draftContent: content,
    attachments: cloneAttachments(input.attachments),
    editing: false,
    createdAt: input.now || new Date().toISOString(),
    kind: input.kind === 'interrupt' ? 'interrupt' : 'normal',
    status: 'queued',
    error: '',
    attemptCount: 0,
    agentId: input.scope.agentId || 'main',
    sessionId: input.scope.sessionId || '',
  }
}

function normalizeStoredQueueItem(
  value: StoredQueueItem,
  scope: MessageQueueScope,
): QueuedComposerMessage | null {
  if (!value || typeof value !== 'object') return null
  const content = String(value.content || '').trim()
  const attachments = Array.isArray(value.attachments) ? cloneAttachments(value.attachments) : []
  if (!content && attachments.length === 0) return null

  const agentId = String(value.agentId || scope.agentId || 'main')
  const sessionId = String(value.sessionId || scope.sessionId || '')
  if (agentId !== (scope.agentId || 'main') || sessionId !== (scope.sessionId || '')) return null

  const storedStatus = value.status === 'failed' ? 'failed' : 'queued'
  return {
    id: String(value.id || generateQueueId()),
    content,
    draftContent: String(value.draftContent || content),
    attachments,
    editing: false,
    createdAt: String(value.createdAt || new Date().toISOString()),
    kind: value.kind === 'interrupt' ? 'interrupt' : 'normal',
    status: storedStatus,
    error: storedStatus === 'failed' ? String(value.error || '') : '',
    attemptCount: Math.max(0, Number(value.attemptCount) || 0),
    agentId,
    sessionId,
  }
}

export function parseStoredQueue(raw: string | null, scope: MessageQueueScope): QueuedComposerMessage[] {
  if (!raw) return []
  try {
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
      .map(item => normalizeStoredQueueItem(item as StoredQueueItem, scope))
      .filter((item): item is QueuedComposerMessage => Boolean(item))
  } catch {
    return []
  }
}

export function serializeQueue(items: QueuedComposerMessage[]): string {
  return JSON.stringify(items.map(item => ({
    ...item,
    attachments: cloneAttachments(item.attachments),
    editing: false,
    draftContent: item.content,
  })))
}

export function selectNextQueueItem(items: QueuedComposerMessage[]): QueuedComposerMessage | null {
  const ready = items.filter(item => item.status === 'queued' && !item.editing)
  return ready.find(item => item.kind === 'interrupt') || ready[0] || null
}

export function markQueueItemSending(item: QueuedComposerMessage): QueuedComposerMessage {
  return {
    ...item,
    editing: false,
    status: 'sending',
    error: '',
    attemptCount: item.attemptCount + 1,
  }
}

export function markQueueItemFailed(item: QueuedComposerMessage, error: string): QueuedComposerMessage {
  return {
    ...item,
    status: 'failed',
    error: error.trim() || 'Request failed',
  }
}

export function retryQueueItem(item: QueuedComposerMessage): QueuedComposerMessage {
  return {
    ...item,
    status: 'queued',
    error: '',
  }
}
