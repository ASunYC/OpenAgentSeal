import assert from 'node:assert/strict'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import ts from 'typescript'

const sourcePath = new URL('../src/models/workspaceSelection.ts', import.meta.url)
const source = await readFile(sourcePath, 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ES2022,
    target: ts.ScriptTarget.ES2022,
    importsNotUsedAsValues: ts.ImportsNotUsedAsValues.Remove,
    verbatimModuleSyntax: false,
  },
  fileName: 'workspaceSelection.ts',
})

const tempDir = await mkdtemp(join(tmpdir(), 'open-agent-workspace-selection-'))
const modulePath = join(tempDir, 'workspaceSelection.mjs')
await writeFile(modulePath, compiled.outputText, 'utf8')

try {
  const model = await import(`file:///${modulePath.replace(/\\/g, '/')}`)
  const wsId = 'ws1'
  const root = 'C:\\repo'
  const dir = file('src', true)
  const fileA = file('src/a.ts')
  const nested = file('src/nested', true)
  const fileB = file('src/nested/b.ts')
  const cache = {
    [model.workspaceCacheKey(wsId)]: [dir, file('README.md')],
    [model.workspaceCacheKey(wsId, 'src')]: [fileA, nested],
    [model.workspaceCacheKey(wsId, 'src/nested')]: [fileB],
  }

  let selected = model.selectWorkspaceFilePath([], cache, wsId, root, dir)
  assert.deepEqual([...selected], ['C:\\repo\\src'])
  assert.equal(model.workspaceFileSelectionState(selected, cache, wsId, root, fileA), 'checked')
  assert.equal(model.workspaceFileSelectionState(selected, cache, wsId, root, nested), 'checked')

  selected = model.deselectWorkspaceFilePath(selected, cache, wsId, root, fileA)
  assert.equal(model.workspaceFileSelectionState(selected, cache, wsId, root, dir), 'mixed')
  assert.equal(model.workspaceFileSelectionState(selected, cache, wsId, root, fileA), 'unchecked')
  assert.equal(model.workspaceFileSelectionState(selected, cache, wsId, root, nested), 'checked')
  assert.deepEqual([...selected], ['C:\\repo\\src\\nested'])

  selected = model.selectWorkspaceFilePath(selected, cache, wsId, root, fileA)
  assert.equal(model.workspaceFileSelectionState(selected, cache, wsId, root, dir), 'checked')

  const sources = [{
    name: 'repo',
    path: 'C:\\repo',
    type: 'directory',
    children: [
      { name: 'README.md', path: 'C:\\repo\\README.md', type: 'file' },
      { name: 'src', path: 'C:\\repo\\src', type: 'directory' },
    ],
  }]
  assert.deepEqual(
    model.normalizeWorkspaceSourceSelection(sources, ['C:\\repo\\README.md', 'C:\\repo\\src']),
    ['C:\\repo'],
  )
  assert.deepEqual(
    model.compactWorkspaceSourceSelection(sources, ['C:\\repo', 'C:\\repo\\src']),
    ['C:\\repo'],
  )

  const staleLocalSource = {
    id: 'legacy-local',
    name: 'old-repo',
    path: 'C:\\old-repo',
    type: 'directory',
    children: [],
  }
  const webSource = {
    id: 'web-1',
    name: 'docs.example.com',
    path: 'https://docs.example.com/',
    type: 'web',
    children: [],
  }
  const workspaces = [{
    id: 'managed-1',
    name: 'repo',
    path: 'C:\\repo',
    created: '2026-07-18T00:00:00Z',
  }]
  const discovered = [{
    id: 'discovered-1',
    name: 'repo',
    path: 'C:\\repo',
    type: 'directory',
    children: [{ name: 'README.md', path: 'C:\\repo\\README.md', type: 'file' }],
    children_count: 1,
  }]
  const payload = model.buildWorkspaceContextSources(
    [staleLocalSource, webSource],
    workspaces,
    discovered,
  )
  assert.deepEqual(payload.map(source => source.path), ['https://docs.example.com/', 'C:\\repo'])
  assert.equal(payload[1].children_count, 1)
  assert.equal(payload[1].children[0].name, 'README.md')
  assert.deepEqual(
    model.buildWorkspaceContextSelection(
      [staleLocalSource, webSource],
      ['C:\\old-repo', 'https://docs.example.com/'],
      ['C:\\repo\\src'],
    ),
    ['https://docs.example.com/', 'C:\\repo\\src'],
  )
} finally {
  await rm(tempDir, { recursive: true, force: true })
}

function file(path, isDir = false) {
  const parts = path.split('/')
  return {
    name: parts[parts.length - 1],
    path,
    is_dir: isDir,
    size: isDir ? null : 1,
    modified_at: 1,
    mime_type: isDir ? null : 'text/plain',
  }
}
