export type CollaborationStatus = 'running' | 'queued' | 'completed' | 'failed' | 'cancelled' | 'idle'

interface AgentTaskLike {
  profile_id: string
  status: string
  updated_at?: string
  created_at?: string
}

interface ReferenceLike {
  path: string
  modifiedAt?: number
}

interface ChangedFileLike {
  path: string
  modified_at?: number
}

function normalizeStatus(status: string): CollaborationStatus {
  if (status === 'running' || status === 'queued' || status === 'completed' || status === 'failed' || status === 'cancelled') {
    return status
  }
  return 'idle'
}

export function deriveAgentStatus(
  agentId: string,
  tasks: AgentTaskLike[],
  activeAgentId: string,
): CollaborationStatus {
  if (agentId === activeAgentId) return 'running'
  const matching = tasks.filter(task => task.profile_id === agentId)
  if (matching.some(task => task.status === 'running')) return 'running'
  if (matching.some(task => task.status === 'queued')) return 'queued'
  const latest = [...matching].sort((a, b) =>
    String(b.updated_at || b.created_at || '').localeCompare(String(a.updated_at || a.created_at || '')),
  )[0]
  return latest ? normalizeStatus(latest.status) : 'idle'
}

function normalizePath(value: string): string {
  return value.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
}

function absoluteChangedPath(repoRoot: string, path: string): string {
  if (/^[a-z]:[\\/]/i.test(path) || path.startsWith('/')) return path
  return `${repoRoot.replace(/[\\/]+$/, '')}/${path.replace(/^[\\/]+/, '')}`
}

export function findStaleReferences(
  references: ReferenceLike[],
  changedFiles: ChangedFileLike[],
  repoRoot: string,
): ReferenceLike[] {
  const changedByPath = new Map(
    changedFiles.map(file => [normalizePath(absoluteChangedPath(repoRoot, file.path)), Number(file.modified_at) || 0]),
  )
  return references.filter(reference => {
    const currentModifiedAt = changedByPath.get(normalizePath(reference.path)) || 0
    return currentModifiedAt > 0 && currentModifiedAt > (Number(reference.modifiedAt) || 0)
  })
}
