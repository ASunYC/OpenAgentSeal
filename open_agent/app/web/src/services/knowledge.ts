export interface KnowledgeWiki {
  id: string
  name: string
  displayName: string
  description: string
  category: 'industry' | 'domain' | 'project' | 'private'
  wikiType: 'general' | 'manual'
  visibility: 'private' | 'public'
  status: string
  tags: string[]
  pagesCount: number
  entitiesCount: number
  conceptsCount: number
  createdAt: string
  updatedAt: string
}

export interface KnowledgePage {
  id: string
  wikiId: string
  title: string
  path: string
  pageType: 'general' | 'source' | 'entity'
  content: string
  tags: string[]
  source: string
  sourceRefs: string[]
  version: number
  wordCount: number
  updatedAt: string
  lastModified: string
}

export interface KnowledgeGraphNode {
  id: string
  label: string
  type: 'wiki' | 'page' | 'source' | 'entity' | 'tag'
}

export interface KnowledgeGraphEdge {
  id: string
  source: string
  target: string
  label: string
}

export interface KnowledgeGraph {
  nodes: KnowledgeGraphNode[]
  edges: KnowledgeGraphEdge[]
}

export interface KnowledgeSourceFile {
  path: string
  title: string
  complete: boolean
  chunkCount: number
  sizeBytes: number
  errorMessage?: string
}

export interface KnowledgeImportJob {
  id: string
  fileName: string
  status: 'queued' | 'running' | 'processing' | 'completed' | 'failed'
  progress: number
  error?: string
}

const WIKIS_KEY = 'open-agent:wikis'
const PAGES_KEY = 'open-agent:pages'

function uid(prefix: string) {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw ? JSON.parse(raw) as T : fallback
  } catch {
    return fallback
  }
}

function writeJson<T>(key: string, value: T) {
  localStorage.setItem(key, JSON.stringify(value))
}

function slugify(text: string): string {
  return text.toLowerCase().replace(/\s+/g, '-').replace(/[^\w-]/g, '')
}

// Local-first wiki CRUD
export function loadLocalWikis(): KnowledgeWiki[] {
  return readJson(WIKIS_KEY, [])
}

export function loadLocalPages(): KnowledgePage[] {
  return readJson(PAGES_KEY, [])
}

export function createWikiLocal(input: { displayName: string; description?: string; category?: string }): KnowledgeWiki {
  const wikis = loadLocalWikis()
  const now = new Date().toISOString()
  const wiki: KnowledgeWiki = {
    id: uid('wiki'),
    name: slugify(input.displayName),
    displayName: input.displayName,
    description: input.description || '',
    category: (input.category as KnowledgeWiki['category']) || 'project',
    wikiType: 'general',
    visibility: 'private',
    status: 'published',
    tags: [],
    pagesCount: 0,
    entitiesCount: 0,
    conceptsCount: 0,
    createdAt: now,
    updatedAt: now,
  }
  writeJson(WIKIS_KEY, [wiki, ...wikis])
  return wiki
}

export function deleteWikiLocal(id: string) {
  writeJson(WIKIS_KEY, loadLocalWikis().filter((wiki) => wiki.id !== id))
  writeJson(PAGES_KEY, loadLocalPages().filter((page) => page.wikiId !== id))
}

export function savePageLocal(input: { wikiId: string; title: string; content: string; id?: string; pageType?: string; tags?: string[] }): KnowledgePage {
  const pages = loadLocalPages()
  const now = new Date().toISOString()
  const page: KnowledgePage = {
    id: input.id || uid('page'),
    wikiId: input.wikiId,
    title: input.title,
    path: `wiki/${input.pageType || 'general'}/${slugify(input.title)}.md`,
    pageType: (input.pageType as KnowledgePage['pageType']) || 'general',
    content: input.content,
    tags: input.tags || extractTags(input.content),
    source: 'manual',
    sourceRefs: [],
    version: 1,
    wordCount: input.content.replace(/\s+/g, '').length,
    updatedAt: now,
    lastModified: now,
  }
  const next = pages.some((item) => item.id === page.id) ? pages.map((item) => item.id === page.id ? page : item) : [page, ...pages]
  writeJson(PAGES_KEY, next)
  // Update wiki page count
  const wikis = loadLocalWikis()
  writeJson(WIKIS_KEY, wikis.map((wiki) => {
    if (wiki.id === input.wikiId) {
      return { ...wiki, pagesCount: next.filter((p) => p.wikiId === input.wikiId).length, updatedAt: now }
    }
    return wiki
  }))
  return page
}

export function deletePageLocal(id: string) {
  writeJson(PAGES_KEY, loadLocalPages().filter((page) => page.id !== id))
}

export function extractTags(content: string): string[] {
  const tags = new Set<string>()
  for (const match of content.matchAll(/#([\p{L}\p{N}_-]{2,32})/gu)) tags.add(match[1])
  for (const match of content.matchAll(/\[\[([^\]]{2,40})\]\]/g)) tags.add(match[1])
  return [...tags].slice(0, 20)
}

// Knowledge graph builder
export function buildKnowledgeGraph(wikis: KnowledgeWiki[], pages: KnowledgePage[], activeWikiId?: string): KnowledgeGraph {
  const filteredWikis = activeWikiId ? wikis.filter((wiki) => wiki.id === activeWikiId) : wikis
  const wikiIds = new Set(filteredWikis.map((wiki) => wiki.id))
  const filteredPages = pages.filter((page) => wikiIds.has(page.wikiId))
  const nodes: KnowledgeGraphNode[] = []
  const edges: KnowledgeGraphEdge[] = []
  const nodeIds = new Set<string>()

  function addNode(node: KnowledgeGraphNode) {
    if (nodeIds.has(node.id)) return
    nodeIds.add(node.id)
    nodes.push(node)
  }

  for (const wiki of filteredWikis) addNode({ id: wiki.id, label: wiki.displayName, type: 'wiki' })
  for (const page of filteredPages) {
    const type = page.pageType === 'source' || page.pageType === 'entity' ? page.pageType : 'page'
    addNode({ id: page.id, label: page.title, type })
    edges.push({ id: `${page.wikiId}-${page.id}`, source: page.wikiId, target: page.id, label: 'contains' })
    for (const tag of page.tags) {
      const tagId = `tag:${tag}`
      addNode({ id: tagId, label: tag, type: 'tag' })
      edges.push({ id: `${page.id}-${tagId}`, source: page.id, target: tagId, label: 'tagged' })
    }
    for (const match of page.content.matchAll(/\[\[([^\]]+)\]\]/g)) {
      const targetTitle = match[1].trim()
      const target = filteredPages.find((candidate) => candidate.title.toLowerCase() === targetTitle.toLowerCase())
      const targetId = target?.id || `entity:${targetTitle}`
      addNode({ id: targetId, label: targetTitle, type: target ? 'page' : 'entity' })
      edges.push({ id: `${page.id}-${targetId}`, source: page.id, target: targetId, label: 'links' })
    }
  }
  return { nodes, edges }
}

// Knowledge search across pages
export function searchKnowledge(pages: KnowledgePage[], wikiId: string | undefined, query: string): string {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  const scoped = wikiId ? pages.filter((page) => page.wikiId === wikiId) : pages
  const ranked = scoped
    .map((page) => ({
      page,
      score: words.reduce((sum, word) => sum + (page.title.toLowerCase().includes(word) || page.content.toLowerCase().includes(word) ? 1 : 0), 0),
    }))
    .filter((item) => item.score > 0 || words.length === 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, 6)
  return ranked.map(({ page }) => `### ${page.title}\n${page.content.slice(0, 1200)}`).join('\n\n')
}

// Import files as knowledge pages
export function importFileContent(wikiId: string, fileName: string, content: string): KnowledgePage {
  const title = fileName.replace(/\.[^.]+$/, '')
  const ext = fileName.split('.').pop()?.toLowerCase() || ''
  const pageType: KnowledgePage['pageType'] = ext === 'md' || ext === 'markdown' ? 'general' : 'source'
  return savePageLocal({
    wikiId,
    title,
    content: ext === 'md' || ext === 'markdown' ? content : `# ${title}\n\n${content}`,
    pageType,
  })
}
