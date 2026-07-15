import type { FileEntry, WorkspaceSourceNode } from '@/types'

export type WorkspaceSelectionState = 'checked' | 'mixed' | 'unchecked'
export type WorkspaceFileCache = Record<string, FileEntry[]>

export function workspaceCacheKey(workspaceId: string, path = ''): string {
  return path ? `${workspaceId}:${path}` : workspaceId
}

export function normalizeComparablePath(path: string): string {
  return path.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
}

export function isSameOrDescendantPath(candidate: string, root: string): boolean {
  const normalizedCandidate = normalizeComparablePath(candidate)
  const normalizedRoot = normalizeComparablePath(root)
  return normalizedCandidate === normalizedRoot || normalizedCandidate.startsWith(`${normalizedRoot}/`)
}

export function absoluteWorkspacePath(rootPath: string, relativePath: string): string {
  const root = rootPath.replace(/[\\/]+$/, '')
  const rel = relativePath.replace(/^[\\/]+/, '').replace(/\//g, '\\')
  if (!root) return relativePath
  return rel ? `${root}\\${rel}` : root
}

export function relativeWorkspacePath(rootPath: string, selectionPath: string): string {
  const root = rootPath.replace(/\\/g, '/').replace(/\/+$/, '')
  const selection = selectionPath.replace(/\\/g, '/').replace(/\/+$/, '')
  const normalizedRoot = root.toLowerCase()
  const normalizedSelection = selection.toLowerCase()
  if (!normalizedRoot || normalizedSelection === normalizedRoot) return ''
  if (!normalizedSelection.startsWith(`${normalizedRoot}/`)) return ''
  return selection.slice(root.length + 1)
}

export function selectedAncestorPath(selectedPaths: Iterable<string>, path: string): string {
  const normalized = normalizeComparablePath(path)
  let best = ''
  for (const selected of selectedPaths) {
    const normalizedSelected = normalizeComparablePath(selected)
    if (
      normalized !== normalizedSelected &&
      normalized.startsWith(`${normalizedSelected}/`) &&
      normalizedSelected.length > best.length
    ) {
      best = selected
    }
  }
  return best
}

export function loadedWorkspaceChildren(
  cache: WorkspaceFileCache,
  workspaceId: string,
  relativePath: string,
): FileEntry[] {
  return cache[workspaceCacheKey(workspaceId, relativePath)] || []
}

export function loadedDescendantSelectionPaths(
  cache: WorkspaceFileCache,
  workspaceId: string,
  workspaceRoot: string,
  relativePath: string,
): string[] {
  const result: string[] = []
  const append = (path: string) => {
    for (const child of loadedWorkspaceChildren(cache, workspaceId, path)) {
      const childSelectionPath = absoluteWorkspacePath(workspaceRoot, child.path)
      result.push(childSelectionPath)
      if (child.is_dir) append(child.path)
    }
  }
  append(relativePath)
  return result
}

export function removeSelectionSubtree(selected: Set<string>, path: string): void {
  for (const candidate of Array.from(selected)) {
    if (isSameOrDescendantPath(candidate, path)) {
      selected.delete(candidate)
    }
  }
}

function addLoadedSelectionExcept(
  selected: Set<string>,
  cache: WorkspaceFileCache,
  workspaceId: string,
  workspaceRoot: string,
  file: FileEntry,
  excludedPath: string,
): void {
  const fileSelectionPath = absoluteWorkspacePath(workspaceRoot, file.path)
  if (isSameOrDescendantPath(fileSelectionPath, excludedPath)) return

  if (file.is_dir && isSameOrDescendantPath(excludedPath, fileSelectionPath)) {
    for (const child of loadedWorkspaceChildren(cache, workspaceId, file.path)) {
      addLoadedSelectionExcept(selected, cache, workspaceId, workspaceRoot, child, excludedPath)
    }
    return
  }

  selected.add(fileSelectionPath)
}

export function selectWorkspaceFilePath(
  selectedPaths: Iterable<string>,
  cache: WorkspaceFileCache,
  workspaceId: string,
  workspaceRoot: string,
  file: FileEntry,
): Set<string> {
  const path = absoluteWorkspacePath(workspaceRoot, file.path)
  const selected = new Set(selectedPaths)
  selected.add(path)
  if (file.is_dir) {
    for (const descendant of loadedDescendantSelectionPaths(cache, workspaceId, workspaceRoot, file.path)) {
      selected.delete(descendant)
    }
  }
  return selected
}

export function deselectWorkspaceFilePath(
  selectedPaths: Iterable<string>,
  cache: WorkspaceFileCache,
  workspaceId: string,
  workspaceRoot: string,
  file: FileEntry,
): Set<string> {
  const path = absoluteWorkspacePath(workspaceRoot, file.path)
  const selected = new Set(selectedPaths)
  const ancestor = selectedAncestorPath(selected, path)

  if (ancestor) {
    selected.delete(ancestor)
    const relativeAncestor = relativeWorkspacePath(workspaceRoot, ancestor)
    for (const child of loadedWorkspaceChildren(cache, workspaceId, relativeAncestor)) {
      addLoadedSelectionExcept(selected, cache, workspaceId, workspaceRoot, child, path)
    }
  }

  removeSelectionSubtree(selected, path)
  return selected
}

export function workspaceFileSelectionState(
  selectedPaths: Iterable<string>,
  cache: WorkspaceFileCache,
  workspaceId: string,
  workspaceRoot: string,
  file: FileEntry,
): WorkspaceSelectionState {
  const selectedSet = selectedPaths instanceof Set ? selectedPaths : new Set(selectedPaths)
  const path = absoluteWorkspacePath(workspaceRoot, file.path)
  if (selectedSet.has(path) || selectedAncestorPath(selectedSet, path)) {
    return 'checked'
  }

  if (!file.is_dir) {
    return 'unchecked'
  }

  const children = loadedWorkspaceChildren(cache, workspaceId, file.path)
  if (!children.length) {
    return 'unchecked'
  }

  const childStates = children.map(child =>
    workspaceFileSelectionState(selectedSet, cache, workspaceId, workspaceRoot, child),
  )
  if (childStates.every(state => state === 'checked')) {
    return 'checked'
  }
  if (childStates.some(state => state !== 'unchecked')) {
    return 'mixed'
  }
  return 'unchecked'
}

function sourceChildren(source: WorkspaceSourceNode): WorkspaceSourceNode[] {
  return Array.isArray(source.children) ? source.children : []
}

export function collectWorkspaceSourcePaths(sources: WorkspaceSourceNode[]): Set<string> {
  const available = new Set<string>()
  const visit = (source: WorkspaceSourceNode) => {
    if (source.path) available.add(source.path)
    for (const child of sourceChildren(source)) visit(child)
  }
  sources.forEach(visit)
  return available
}

export function normalizeWorkspaceSourceSelection(
  sources: WorkspaceSourceNode[],
  paths: Iterable<string>,
): string[] {
  const selected = new Set(paths)
  const available = new Set<string>()

  const visit = (source: WorkspaceSourceNode): boolean => {
    if (source.path) available.add(source.path)
    const children = sourceChildren(source)
    if (!children.length) {
      return selected.has(source.path)
    }

    const childStates = children.map(visit)
    const allChildrenSelected = childStates.length > 0 && childStates.every(Boolean)
    if (allChildrenSelected) {
      selected.add(source.path)
      for (const child of children) removeSelectionSubtree(selected, child.path)
      return true
    }

    selected.delete(source.path)
    return false
  }

  sources.forEach(visit)
  return Array.from(selected).filter(path => available.has(path))
}

export function compactWorkspaceSourceSelection(
  sources: WorkspaceSourceNode[],
  selectedPaths: Iterable<string>,
): string[] {
  const selected = new Set(selectedPaths)
  const compacted: string[] = []

  const visit = (source: WorkspaceSourceNode, ancestorSelected = false) => {
    const isSelected = selected.has(source.path)
    if (isSelected && !ancestorSelected) {
      compacted.push(source.path)
    }
    for (const child of sourceChildren(source)) {
      visit(child, ancestorSelected || isSelected)
    }
  }

  sources.forEach(source => visit(source))
  return compacted
}
