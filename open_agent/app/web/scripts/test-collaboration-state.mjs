import assert from 'node:assert/strict'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import ts from 'typescript'

const sourcePath = new URL('../src/models/collaborationState.ts', import.meta.url)
const source = await readFile(sourcePath, 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ES2022,
    target: ts.ScriptTarget.ES2022,
    importsNotUsedAsValues: ts.ImportsNotUsedAsValues.Remove,
    verbatimModuleSyntax: false,
  },
  fileName: 'collaborationState.ts',
})

const tempDir = await mkdtemp(join(tmpdir(), 'open-agent-collaboration-state-'))
const modulePath = join(tempDir, 'collaborationState.mjs')
await writeFile(modulePath, compiled.outputText, 'utf8')

try {
  const state = await import(`file:///${modulePath.replace(/\\/g, '/')}`)
  const tasks = [
    { task_id: '1', profile_id: 'writer', status: 'completed', updated_at: '2026-07-16T09:00:00Z' },
    { task_id: '2', profile_id: 'writer', status: 'running', updated_at: '2026-07-16T10:00:00Z' },
    { task_id: '3', profile_id: 'reviewer', status: 'failed', updated_at: '2026-07-16T10:01:00Z' },
  ]
  assert.equal(state.deriveAgentStatus('writer', tasks, ''), 'running')
  assert.equal(state.deriveAgentStatus('reviewer', tasks, ''), 'failed')
  assert.equal(state.deriveAgentStatus('main', tasks, 'main'), 'running')
  assert.equal(state.deriveAgentStatus('idle-agent', tasks, ''), 'idle')

  const stale = state.findStaleReferences(
    [{ path: 'C:\\repo\\src\\a.ts', modifiedAt: 100 }, { path: 'C:\\repo\\README.md', modifiedAt: 300 }],
    [{ path: 'src/a.ts', modified_at: 200 }, { path: 'README.md', modified_at: 250 }],
    'C:\\repo',
  )
  assert.deepEqual(stale.map(item => item.path), ['C:\\repo\\src\\a.ts'])
} finally {
  await rm(tempDir, { recursive: true, force: true })
}
