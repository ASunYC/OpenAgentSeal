import { API_BASE } from '@/api'

export interface AutonomicsEnvelope<T> {
  readonly success: true
  readonly data: T
  readonly meta?: Readonly<{ next_cursor?: string | null }>
}

export interface AutonomicsRequestOptions extends Omit<RequestInit, 'body' | 'headers' | 'signal'> {
  readonly body?: unknown
  readonly signal?: AbortSignal
  readonly csrfToken?: string
  readonly reauthentication?: string
  readonly ifMatch?: string | number
  readonly headers?: Readonly<Record<string, string>>
}

export class AutonomicsApiError extends Error {
  readonly status: number
  readonly code: string
  readonly requestId: string
  readonly details: unknown

  constructor(status: number, code: string, message: string, requestId = '', details: unknown = null) {
    super(message)
    this.name = 'AutonomicsApiError'
    this.status = status
    this.code = code
    this.requestId = requestId
    this.details = details
  }
}

interface OperationalSession {
  auth_mode: 'cookie' | 'bearer'
  csrf_token: string | null
  access_token?: string
  roles: string[]
  expires_in_seconds: number
  next_bootstrap_capability?: string
}

let bootstrapCapability = ''
let memoryAccessToken = ''
let memoryCsrfToken = ''
let sessionReady = false
let sessionPromise: Promise<void> | null = null
let resumeAttempted = false

function crossOriginApi(): boolean {
  if (typeof window === 'undefined') return false
  return new URL(API_BASE, window.location.href).origin !== window.location.origin
}

function isTauriRuntime(): boolean {
  if (typeof window === 'undefined') return false
  return '__TAURI_INTERNALS__' in window
}

async function loadHostBootstrapCapability(): Promise<string> {
  if (!isTauriRuntime()) return ''
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    const value = await invoke<unknown>('load_operational_bootstrap_capability')
    return typeof value === 'string' && value.length >= 32 && value.length <= 4096 ? value : ''
  } catch {
    throw new AutonomicsApiError(503, 'operational_host_unavailable', 'The desktop host could not provide operational access')
  }
}

async function storeHostBootstrapCapability(value: string): Promise<void> {
  if (!isTauriRuntime()) return
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    await invoke('store_operational_bootstrap_capability', { capability: value })
  } catch {
    throw new AutonomicsApiError(503, 'operational_host_unavailable', 'The desktop host could not retain renewed operational access')
  }
}

function requestCredentials(): RequestCredentials {
  return crossOriginApi() ? 'omit' : 'same-origin'
}

function sessionHeaders(): Record<string, string> {
  return memoryAccessToken ? { Authorization: `Bearer ${memoryAccessToken}` } : {}
}

function isMutation(method: string): boolean {
  return !['GET', 'HEAD', 'OPTIONS'].includes(method)
}

function errorPayload(value: unknown): { code: string; message: string; details: unknown } {
  if (!value || typeof value !== 'object') return { code: 'request_failed', message: 'The request could not be completed', details: null }
  const root = value as Record<string, unknown>
  const nested = root.error && typeof root.error === 'object'
    ? root.error as Record<string, unknown>
    : root.detail && typeof root.detail === 'object'
      ? root.detail as Record<string, unknown>
      : root
  return {
    code: typeof nested.code === 'string' ? nested.code : 'request_failed',
    message: typeof nested.message === 'string' ? nested.message : 'The request could not be completed',
    details: nested.details ?? null,
  }
}

function clearOperationalSession(): void {
  memoryAccessToken = ''
  memoryCsrfToken = ''
  sessionReady = false
  resumeAttempted = false
}

export function provideOperationalBootstrapCapability(value: string): void {
  bootstrapCapability = value.trim()
  clearOperationalSession()
}

async function acceptSession(session: OperationalSession): Promise<void> {
  const accessToken = session.auth_mode === 'bearer' ? session.access_token ?? '' : ''
  const csrfToken = session.csrf_token ?? ''
  const successor = session.next_bootstrap_capability
  if (typeof successor === 'string' && successor.length >= 32 && successor.length <= 4096) {
    bootstrapCapability = successor
    await storeHostBootstrapCapability(successor)
  }
  memoryAccessToken = accessToken
  memoryCsrfToken = csrfToken
  sessionReady = session.auth_mode === 'cookie' || accessToken.length > 0
}

async function resumeCookieSession(signal?: AbortSignal): Promise<boolean> {
  if (crossOriginApi() || resumeAttempted) return false
  resumeAttempted = true
  const response = await fetch(`${API_BASE}/operations/session/resume`, {
    method: 'GET', credentials: 'same-origin', cache: 'no-store', signal,
    headers: { Accept: 'application/json' },
  })
  if (!response.ok) return false
  await acceptSession(await parseEnvelope<OperationalSession>(response))
  return sessionReady
}

async function parseEnvelope<T>(response: Response): Promise<T> {
  const payload: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const normalized = errorPayload(payload)
    throw new AutonomicsApiError(response.status, normalized.code, normalized.message, response.headers.get('x-request-id') ?? '', normalized.details)
  }
  if (!payload || typeof payload !== 'object' || !('success' in payload)) {
    throw new AutonomicsApiError(response.status, 'invalid_response', 'The server returned an invalid response')
  }
  return (payload as AutonomicsEnvelope<T>).data
}

async function establishOperationalSession(signal?: AbortSignal): Promise<void> {
  if (await resumeCookieSession(signal)) return
  if (!bootstrapCapability) bootstrapCapability = await loadHostBootstrapCapability()
  const capability = bootstrapCapability
  if (capability.length < 32) {
    throw new AutonomicsApiError(401, 'operational_bootstrap_required', 'Enter the one-time operational bootstrap capability provided by the host administrator')
  }
  bootstrapCapability = ''
  const mode = crossOriginApi() ? 'bearer' : 'cookie'
  const response = await fetch(`${API_BASE}/operations/session/bootstrap`, {
    method: 'POST', credentials: requestCredentials(), cache: 'no-store', signal,
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode, capability }),
  })
  const session = await parseEnvelope<OperationalSession>(response)
  await acceptSession(session)
  if (!sessionReady) throw new AutonomicsApiError(500, 'invalid_session', 'The server did not establish an operational session')
}

export async function bootstrapOperationalSession(signal?: AbortSignal): Promise<void> {
  if (sessionReady) return
  if (!sessionPromise) sessionPromise = establishOperationalSession(signal)
  const pending = sessionPromise
  try { await pending } finally { if (sessionPromise === pending) sessionPromise = null }
}

async function reauthenticateOperationalSession(signal?: AbortSignal): Promise<void> {
  await bootstrapOperationalSession(signal)
  if (!bootstrapCapability) bootstrapCapability = await loadHostBootstrapCapability()
  const capability = bootstrapCapability
  if (capability.length < 32 || capability.length > 4096) {
    throw new AutonomicsApiError(401, 'operational_bootstrap_required', 'Operational reauthentication requires a current host capability')
  }
  bootstrapCapability = ''
  const response = await fetch(`${API_BASE}/operations/session/reauthenticate`, {
    method: 'POST', credentials: requestCredentials(), cache: 'no-store', signal,
    headers: {
      Accept: 'application/json', 'Content-Type': 'application/json',
      ...sessionHeaders(), ...(memoryCsrfToken ? { 'X-CSRF-Token': memoryCsrfToken } : {}),
    },
    body: JSON.stringify({ user_presence_confirmed: true, capability }),
  })
  const session = await parseEnvelope<OperationalSession>(response)
  await acceptSession(session)
}

export async function autonomicsRequest<T>(path: string, options: AutonomicsRequestOptions = {}): Promise<T> {
  const method = (options.method ?? 'GET').toUpperCase()
  if (options.reauthentication !== undefined) {
    if (options.reauthentication !== 'REAUTHENTICATE') {
      throw new AutonomicsApiError(400, 'reauthentication_confirmation_required', 'Type REAUTHENTICATE to refresh the operational session')
    }
    await reauthenticateOperationalSession(options.signal)
  } else {
    await bootstrapOperationalSession(options.signal)
  }
  const csrfToken = options.csrfToken ?? memoryCsrfToken
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...sessionHeaders(),
    ...options.headers,
  }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (isMutation(method) && csrfToken) headers['X-CSRF-Token'] = csrfToken
  if (options.ifMatch !== undefined) headers['If-Match'] = String(options.ifMatch)

  const response = await fetch(`${API_BASE}/operations${path}`, {
    method,
    credentials: requestCredentials(),
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
    cache: 'no-store',
  })
  if (response.status === 204) return undefined as T

  const contentType = response.headers.get('content-type') ?? ''
  const payload: unknown = contentType.includes('application/json')
    ? await response.json().catch(() => null)
    : null
  if (!response.ok) {
    if (response.status === 401) clearOperationalSession()
    const normalized = errorPayload(payload)
    throw new AutonomicsApiError(
      response.status,
      normalized.code,
      normalized.message,
      response.headers.get('x-request-id') ?? '',
      normalized.details,
    )
  }
  if (!payload || typeof payload !== 'object' || !('success' in payload)) {
    throw new AutonomicsApiError(response.status, 'invalid_response', 'The server returned an invalid response')
  }
  const envelope = payload as AutonomicsEnvelope<T>
  return envelope.data
}

export async function requestPage<T>(path: string, cursor = '', signal?: AbortSignal): Promise<{ items: T[]; nextCursor: string }> {
  await bootstrapOperationalSession(signal)
  const query = new URLSearchParams({ limit: '50' })
  if (cursor) query.set('cursor', cursor)
  const response = await fetch(`${API_BASE}/operations${path}?${query}`, {
    credentials: requestCredentials(), signal, cache: 'no-store', headers: { Accept: 'application/json', ...sessionHeaders() },
  })
  const payload: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    if (response.status === 401) clearOperationalSession()
    const normalized = errorPayload(payload)
    throw new AutonomicsApiError(response.status, normalized.code, normalized.message, response.headers.get('x-request-id') ?? '', normalized.details)
  }
  const envelope = payload as Partial<AutonomicsEnvelope<T[]>>
  return {
    items: Array.isArray(envelope.data) ? envelope.data : [],
    nextCursor: typeof envelope.meta?.next_cursor === 'string' ? envelope.meta.next_cursor : '',
  }
}

export interface SensitiveMutationOptions {
  readonly csrfToken?: string
  readonly reauthentication?: string
  readonly signal?: AbortSignal
}

const id = encodeURIComponent

export const channelsOperationsApi = {
  listAccounts: (cursor = '', signal?: AbortSignal) => requestPage<Record<string, unknown>>('/channel-accounts', cursor, signal),
  createAccount: (body: unknown, options: SensitiveMutationOptions = {}) => autonomicsRequest<Record<string, unknown>>('/channel-accounts', { method: 'POST', body, ...options }),
  updateAccount: (accountId: string, body: unknown, options: SensitiveMutationOptions = {}) => autonomicsRequest<Record<string, unknown>>(`/channel-accounts/${id(accountId)}`, { method: 'PATCH', body, ...options }),
  deleteAccount: (accountId: string, options: SensitiveMutationOptions = {}) => autonomicsRequest<Record<string, unknown>>(`/channel-accounts/${id(accountId)}`, { method: 'DELETE', ...options }),
  rotateCredential: (accountId: string, body: unknown, options: SensitiveMutationOptions = {}) => autonomicsRequest<Record<string, unknown>>(`/channel-accounts/${id(accountId)}/credential`, { method: 'PUT', body, ...options }),
  diagnostics: (accountId: string, signal?: AbortSignal) => autonomicsRequest<Record<string, unknown>>(`/channel-accounts/${id(accountId)}/diagnostics`, { signal }),
  listRoutes: (accountId: string, signal?: AbortSignal) => autonomicsRequest<Record<string, unknown>[]>(`/channel-accounts/${id(accountId)}/routes`, { signal }),
  putRoute: (accountId: string, body: unknown, options: SensitiveMutationOptions = {}) => autonomicsRequest<Record<string, unknown>>(`/channel-accounts/${id(accountId)}/routes`, { method: 'PUT', body, ...options }),
  deleteRoute: (routeId: string, options: SensitiveMutationOptions = {}) => autonomicsRequest<Record<string, unknown>>(`/routes/${id(routeId)}`, { method: 'DELETE', ...options }),
  listInbox: (cursor = '', signal?: AbortSignal) => requestPage<Record<string, unknown>>('/inbox', cursor, signal),
  listOutbox: (cursor = '', signal?: AbortSignal) => requestPage<Record<string, unknown>>('/outbox', cursor, signal),
  resendOutbox: (obligationId: string, body: unknown, options: SensitiveMutationOptions = {}) => autonomicsRequest<Record<string, unknown>>(`/outbox/${id(obligationId)}/resend`, { method: 'POST', body, ...options }),
  listAudit: (cursor = '', signal?: AbortSignal) => requestPage<Record<string, unknown>>('/audit', cursor, signal),
  revealAudit: (auditId: string, body: unknown, options: SensitiveMutationOptions = {}) => autonomicsRequest<Record<string, unknown>>(`/audit/${id(auditId)}/reveal`, { method: 'POST', body, ...options }),
  getRetention: (signal?: AbortSignal) => autonomicsRequest<Record<string, unknown>>('/retention/policy', { signal }),
  setRetention: (body: unknown, options: SensitiveMutationOptions = {}) => autonomicsRequest<Record<string, unknown>>('/retention/policy', { method: 'PUT', body, ...options }),
  runRetention: (options: SensitiveMutationOptions = {}) => autonomicsRequest<Record<string, unknown>>('/retention/run', { method: 'POST', ...options }),
  listRetentionDeadLetters: (signal?: AbortSignal) => autonomicsRequest<Record<string, unknown>[]>('/retention/dead-letters?limit=50', { signal }),
  requeueRetention: (deadLetterId: string, options: SensitiveMutationOptions = {}) => autonomicsRequest<Record<string, unknown>>(`/retention/dead-letters/${id(deadLetterId)}/requeue`, { method: 'POST', ...options }),
}

export const autonomicsOperationsApi = {
  health: (signal?: AbortSignal) => autonomicsRequest<Record<string, unknown>>('/supervisor/health', { signal }),
  listJobs: (cursor = '', signal?: AbortSignal) => requestPage<Record<string, unknown>>('/scheduler/jobs', cursor, signal),
  createJob: (body: unknown, options: SensitiveMutationOptions = {}) => autonomicsRequest<Record<string, unknown>>('/scheduler/jobs', { method: 'POST', body, ...options }),
  updateJob: (jobId: string, body: unknown, options: SensitiveMutationOptions = {}) => autonomicsRequest<Record<string, unknown>>(`/scheduler/jobs/${id(jobId)}`, { method: 'PATCH', body, ...options }),
  triggerJob: (jobId: string, options: SensitiveMutationOptions = {}) => autonomicsRequest<Record<string, unknown>>(`/scheduler/jobs/${id(jobId)}/trigger`, { method: 'POST', ...options }),
  listRuns: (cursor = '', signal?: AbortSignal) => requestPage<Record<string, unknown>>('/scheduler/runs', cursor, signal),
  listGoals: (cursor = '', signal?: AbortSignal) => requestPage<Record<string, unknown>>('/goals', cursor, signal),
  createGoal: (body: unknown, options: SensitiveMutationOptions = {}) => autonomicsRequest<Record<string, unknown>>('/goals', { method: 'POST', body, ...options }),
  iterations: (goalId: string, signal?: AbortSignal) => autonomicsRequest<Record<string, unknown>[]>(`/goals/${id(goalId)}/iterations?limit=50`, { signal }),
  guidance: (goalId: string, signal?: AbortSignal) => autonomicsRequest<Record<string, unknown>[]>(`/goals/${id(goalId)}/guidance?limit=50`, { signal }),
  appendGuidance: (goalId: string, body: unknown, options: SensitiveMutationOptions = {}) => autonomicsRequest<Record<string, unknown>>(`/goals/${id(goalId)}/guidance`, { method: 'POST', body, ...options }),
  controlGoal: (goalId: string, body: unknown, options: SensitiveMutationOptions = {}) => autonomicsRequest<Record<string, unknown>>(`/goals/${id(goalId)}/control`, { method: 'POST', body, ...options }),
  approveGoal: (goalId: string, body: unknown, options: SensitiveMutationOptions = {}) => autonomicsRequest<Record<string, unknown>>(`/goals/${id(goalId)}/approvals`, { method: 'POST', body, ...options }),
}
