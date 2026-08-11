export type OperationalRole = 'viewer' | 'operator' | 'admin'
export type StatusTone = 'neutral' | 'active' | 'success' | 'warning' | 'danger'
export type OperationalResource = 'channel' | 'delivery' | 'scheduler_job' | 'scheduler_run' | 'goal' | 'retention'

export interface StatusProjection {
  readonly value: string
  readonly label: string
  readonly tone: StatusTone
  readonly terminal: boolean
  readonly known: boolean
}

export interface BudgetProjection {
  readonly kind: 'iterations' | 'tokens' | 'cost' | 'active_time'
  readonly consumed: number
  readonly maximum: number
  readonly percent: number
  readonly exhausted: boolean
}

export interface ChannelAccountProjection {
  readonly id: string
  readonly adapter: string
  readonly enabled: boolean
  readonly profileId: string
  readonly version: number
  readonly updatedAt: string
  readonly allowedActions: readonly string[]
  readonly credential: Readonly<{ configured: boolean; writeOnly: true }>
}

export interface DeliveryProjection {
  readonly id: string
  readonly status: StatusProjection
  readonly attemptNumber: number
  readonly risk: 'normal' | 'high' | 'critical'
  readonly warningCode: string
  readonly requiresTypedConfirmation: boolean
  readonly actions: readonly string[]
}

export interface SchedulerRunProjection {
  readonly id: string
  readonly jobId: string
  readonly status: StatusProjection
  readonly attemptNumber: number
  readonly retryScheduled: boolean
  readonly nextAttemptAt: string
  readonly actions: readonly string[]
}

const STATUS: Readonly<Record<string, Omit<StatusProjection, 'value' | 'known'>>> = Object.freeze({
  active: { label: 'Active', tone: 'active', terminal: false },
  running: { label: 'Running', tone: 'active', terminal: false },
  pending: { label: 'Pending', tone: 'neutral', terminal: false },
  claimed: { label: 'Claimed', tone: 'active', terminal: false },
  paused: { label: 'Paused', tone: 'warning', terminal: false },
  retry_wait: { label: 'Retry scheduled', tone: 'warning', terminal: false },
  blocked: { label: 'Needs approval', tone: 'warning', terminal: false },
  completed: { label: 'Completed', tone: 'success', terminal: true },
  succeeded: { label: 'Succeeded', tone: 'success', terminal: true },
  acknowledged: { label: 'Acknowledged', tone: 'success', terminal: true },
  cancelled: { label: 'Cancelled', tone: 'neutral', terminal: true },
  failed: { label: 'Failed', tone: 'danger', terminal: true },
  dead_letter: { label: 'Dead letter', tone: 'danger', terminal: true },
  delivery_unknown: { label: 'Delivery unknown', tone: 'danger', terminal: true },
})

const SENSITIVE_PARTS = Object.freeze([
  'password', 'secret', 'token', 'credential', 'authorization', 'cookie', 'signature',
  'api_key', 'apikey', 'attachment_url', 'webhook_url', 'platform_response',
])

const STATE_ACTIONS: Readonly<Record<OperationalResource, Readonly<Record<string, readonly string[]>>>> = Object.freeze({
  channel: Object.freeze({ active: ['disable', 'rotate_credential', 'delete'], paused: ['enable', 'rotate_credential', 'delete'] }),
  delivery: Object.freeze({ dead_letter: ['manual_resend'], delivery_unknown: ['reconcile', 'manual_resend'] }),
  scheduler_job: Object.freeze({ active: ['pause', 'trigger'], paused: ['resume', 'trigger', 'delete'] }),
  scheduler_run: Object.freeze({ failed: ['retry'], dead_letter: ['retry'], retry_wait: ['retry'] }),
  goal: Object.freeze({ active: ['pause', 'cancel', 'guidance'], paused: ['resume', 'cancel', 'guidance'], blocked: ['approve', 'cancel', 'guidance'] }),
  retention: Object.freeze({ active: ['run', 'update'], dead_letter: ['requeue'] }),
})

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function text(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

function finite(value: unknown, fallback = 0): number {
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

function sensitive(key: string): boolean {
  const normalized = key.toLowerCase().replace(/-/g, '_')
  return SENSITIVE_PARTS.some(part => normalized.includes(part))
}

function freeze<T extends object>(value: T): Readonly<T> {
  for (const nested of Object.values(value)) {
    if (nested && typeof nested === 'object' && !Object.isFrozen(nested)) freeze(nested)
  }
  return Object.freeze(value)
}

export function projectStatus(value: unknown): StatusProjection {
  const normalized = text(value).toLowerCase()
  const status = STATUS[normalized]
  if (!status) {
    return freeze({ value: 'unknown', label: 'Unknown state', tone: 'neutral' as const, terminal: false, known: false })
  }
  return freeze({ value: normalized, ...status, known: true })
}

export function redactOperationalValue(value: unknown, key = ''): any {
  if (sensitive(key)) return '[REDACTED]'
  if (Array.isArray(value)) return value.map(item => redactOperationalValue(item, key))
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([itemKey, item]) => [itemKey, redactOperationalValue(item, itemKey)]))
  }
  return value
}

export function projectChannelAccount(value: unknown): ChannelAccountProjection {
  const raw = record(value)
  const state = raw.enabled === false ? 'paused' : 'active'
  return freeze({
    id: text(raw.account_id),
    adapter: text(raw.adapter_kind, 'unknown'),
    enabled: raw.enabled === true,
    profileId: text(raw.default_profile_id),
    version: Math.max(0, finite(raw.version ?? raw.runtime_version)),
    updatedAt: text(raw.updated_at),
    allowedActions: legalActions({
      resource: 'channel', state, role: 'admin', serverAllowed: raw.allowed_actions,
      capabilities: raw.capabilities,
    }),
    credential: { configured: Boolean(raw.credential_ref), writeOnly: true as const },
  })
}

export function legalActions(input: {
  resource: string
  state: unknown
  role: OperationalRole
  serverAllowed?: unknown
  capabilities?: unknown
}): string[] {
  if (input.role === 'viewer' || !(input.resource in STATE_ACTIONS)) return []
  const resource = input.resource as OperationalResource
  const state = projectStatus(input.state)
  if (!state.known) return []
  const legal = STATE_ACTIONS[resource][state.value] ?? []
  const serverAllowed = strings(input.serverAllowed)
  const capabilityMap = record(input.capabilities)
  const candidates = serverAllowed.length > 0 ? legal.filter(action => serverAllowed.includes(action)) : legal
  return candidates.filter(action => capabilityMap[action] !== false)
}

export function projectDelivery(value: unknown, role: OperationalRole): DeliveryProjection {
  const raw = record(value)
  const status = projectStatus(raw.state)
  const isUnknown = status.value === 'delivery_unknown'
  const isDeadLetter = status.value === 'dead_letter'
  return freeze({
    id: text(raw.obligation_id),
    status,
    attemptNumber: Math.max(1, Math.floor(finite(raw.attempt)) + 1),
    risk: isUnknown ? 'critical' as const : isDeadLetter ? 'high' as const : 'normal' as const,
    warningCode: isUnknown ? 'duplicate_delivery_possible' : '',
    requiresTypedConfirmation: isUnknown,
    actions: legalActions({ resource: 'delivery', state: raw.state, role, serverAllowed: raw.allowed_actions, capabilities: raw.capabilities }),
  })
}

export function projectSchedulerRun(value: unknown, role: OperationalRole): SchedulerRunProjection {
  const raw = record(value)
  const status = projectStatus(raw.state)
  return freeze({
    id: text(raw.run_id),
    jobId: text(raw.job_id),
    status,
    attemptNumber: Math.max(1, Math.floor(finite(raw.attempt)) + 1),
    retryScheduled: status.value === 'retry_wait',
    nextAttemptAt: text(raw.next_attempt_at),
    actions: legalActions({ resource: 'scheduler_run', state: raw.state, role, serverAllowed: raw.allowed_actions, capabilities: raw.capabilities }),
  })
}

export function projectGoalBudgets(value: unknown): BudgetProjection[] {
  const raw = record(value)
  const definitions: Array<[BudgetProjection['kind'], string, string]> = [
    ['iterations', 'consumed_iterations', 'max_iterations'],
    ['tokens', 'consumed_tokens', 'max_tokens'],
    ['cost', 'consumed_estimated_cost', 'max_estimated_cost'],
    ['active_time', 'consumed_active_seconds', 'max_wall_clock_seconds'],
  ]
  return definitions.map(([kind, usedKey, maxKey]) => {
    const consumed = Math.max(0, finite(raw[usedKey]))
    const maximum = Math.max(0, finite(raw[maxKey]))
    const percent = maximum > 0 ? Math.min(100, Math.round((consumed / maximum) * 10000) / 100) : 0
    return freeze({ kind, consumed, maximum, percent, exhausted: maximum > 0 && consumed >= maximum })
  })
}

export function versionedMutation<T extends Record<string, unknown>>(draft: T, version: number): T & { expected_version: number } {
  return { ...draft, expected_version: Math.max(0, Math.floor(finite(version))) }
}

export function isCurrentSelection(
  requestedId: string, selectedId: string, requestedEpoch: number, currentEpoch: number,
): boolean {
  return Boolean(requestedId) && requestedId === selectedId && requestedEpoch === currentEpoch
}
