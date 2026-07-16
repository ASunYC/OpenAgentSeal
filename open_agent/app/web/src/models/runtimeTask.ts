export type RuntimeTaskStatus = 'done' | 'active' | 'pending' | 'error'

export interface RuntimeTaskPlanItem {
  id: string
  kind: 'request' | 'context' | 'step' | 'tool' | 'result'
  status: RuntimeTaskStatus
  title: string
  detail: string
}

export interface RuntimeTaskReference {
  id: string
  kind: string
  name: string
  path: string
  root?: string
  size?: number
  modifiedAt?: number
}

export interface RuntimeToolActivity {
  id: string
  callId: string
  name: string
  status: 'active' | 'done' | 'error'
  arguments: Record<string, unknown>
  result: unknown
  error: string
  elapsedSeconds?: number
  startedAt: string
  completedAt?: string
}

export interface RuntimeMemoryReference {
  id: string
  category: string
  importance: string
  content: string
}

interface RuntimeTurnLike {
  turn_id: string
  user_input: string
  status: string
  error?: string
  metadata?: Record<string, unknown>
}

interface RuntimeEventLike {
  event_id: string
  seq: number
  event_type: string
  payload: Record<string, unknown>
  created_at: string
}

export interface RuntimeTaskProjection {
  plan: RuntimeTaskPlanItem[]
  references: RuntimeTaskReference[]
  memories: RuntimeMemoryReference[]
  tools: RuntimeToolActivity[]
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function numberValue(value: unknown): number | undefined {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : undefined
}

function buildReferences(turn: RuntimeTurnLike | null): RuntimeTaskReference[] {
  const metadata = objectValue(turn?.metadata)
  const values = [metadata.workspace_references, metadata.attachments]
  const references: RuntimeTaskReference[] = []
  const seen = new Set<string>()

  for (const collection of values) {
    if (!Array.isArray(collection)) continue
    for (const raw of collection) {
      const item = objectValue(raw)
      const path = String(item.path || '')
      if (!path || seen.has(path)) continue
      seen.add(path)
      references.push({
        id: `${String(item.kind || 'file')}:${path}`,
        kind: String(item.kind || 'file'),
        name: String(item.name || path),
        path,
        root: item.root ? String(item.root) : undefined,
        size: numberValue(item.size),
        modifiedAt: numberValue(item.modified_at),
      })
    }
  }
  return references
}

function buildMemories(turn: RuntimeTurnLike | null): RuntimeMemoryReference[] {
  const values = objectValue(turn?.metadata).memory_references
  if (!Array.isArray(values)) return []
  return values.map(raw => {
    const item = objectValue(raw)
    return {
      id: String(item.id || ''),
      category: String(item.category || 'general'),
      importance: String(item.importance || 'normal'),
      content: String(item.content || ''),
    }
  }).filter(item => item.id && item.content)
}

function buildTools(events: RuntimeEventLike[]): RuntimeToolActivity[] {
  const tools: RuntimeToolActivity[] = []

  for (const event of events) {
    const payload = objectValue(event.payload)
    if (event.event_type === 'tool_call') {
      const callId = String(payload.tool_call_id || event.event_id)
      tools.push({
        id: `tool:${callId}`,
        callId,
        name: String(payload.tool_name || 'tool'),
        status: 'active',
        arguments: objectValue(payload.arguments),
        result: null,
        error: '',
        startedAt: event.created_at,
      })
      continue
    }

    if (event.event_type !== 'tool_result') continue
    const callId = String(payload.tool_call_id || '')
    const name = String(payload.tool_name || '')
    const target = (
      (callId && tools.find(item => item.callId === callId))
      || [...tools].reverse().find(item => item.status === 'active' && (!name || item.name === name))
    )
    if (!target) continue
    target.status = payload.success === false ? 'error' : 'done'
    target.result = payload.result ?? payload.content ?? null
    target.error = String(payload.error || '')
    target.elapsedSeconds = numberValue(payload.elapsed)
    target.completedAt = event.created_at
  }
  return tools
}

function terminalStatus(turn: RuntimeTurnLike | null, events: RuntimeEventLike[]): RuntimeTaskStatus {
  const lastTerminal = [...events].reverse().find(event => ['complete', 'error', 'cancelled'].includes(event.event_type))
  if (lastTerminal?.event_type === 'error' || turn?.status === 'failed') return 'error'
  if (lastTerminal || ['completed', 'cancelled'].includes(turn?.status || '')) return 'done'
  if (turn || events.length > 0) return 'active'
  return 'pending'
}

export function buildRuntimeTaskProjection(
  turn: RuntimeTurnLike | null,
  sourceEvents: RuntimeEventLike[],
): RuntimeTaskProjection {
  const events = [...sourceEvents].sort((a, b) => a.seq - b.seq)
  const references = buildReferences(turn)
  const memories = buildMemories(turn)
  const tools = buildTools(events)
  const plan: RuntimeTaskPlanItem[] = []

  if (turn || events.length > 0) {
    plan.push({
      id: `request:${turn?.turn_id || 'live'}`,
      kind: 'request',
      status: 'done',
      title: turn?.user_input || '',
      detail: '',
    })
  }

  if (references.length > 0 || memories.length > 0) {
    plan.push({
      id: `context:${turn?.turn_id || 'live'}`,
      kind: 'context',
      status: 'done',
      title: String(references.length + memories.length),
      detail: '',
    })
  }

  const stepStarts = events.filter(event => event.event_type === 'step_start')
  for (const start of stepStarts) {
    const payload = objectValue(start.payload)
    const step = numberValue(payload.step) || 0
    const end = events.find(event => (
      event.seq > start.seq
      && event.event_type === 'step_end'
      && (numberValue(objectValue(event.payload).step) || 0) === step
    ))
    plan.push({
      id: `step:${turn?.turn_id || 'live'}:${step}:${start.seq}`,
      kind: 'step',
      status: end ? 'done' : 'active',
      title: String(step),
      detail: end ? String(numberValue(objectValue(end.payload).elapsed) || '') : '',
    })
  }

  for (const tool of tools) {
    plan.push({
      id: tool.id,
      kind: 'tool',
      status: tool.status,
      title: tool.name,
      detail: tool.error,
    })
  }

  if (turn || events.length > 0) {
    const status = terminalStatus(turn, events)
    const errorEvent = [...events].reverse().find(event => event.event_type === 'error')
    plan.push({
      id: `result:${turn?.turn_id || 'live'}`,
      kind: 'result',
      status,
      title: '',
      detail: String(objectValue(errorEvent?.payload).error || turn?.error || ''),
    })
  }

  return { plan, references, memories, tools }
}
