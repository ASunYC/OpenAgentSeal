import assert from 'node:assert/strict'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import ts from 'typescript'

const sourcePath = new URL('../src/models/runtimeTask.ts', import.meta.url)
const source = await readFile(sourcePath, 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ES2022,
    target: ts.ScriptTarget.ES2022,
    importsNotUsedAsValues: ts.ImportsNotUsedAsValues.Remove,
    verbatimModuleSyntax: false,
  },
  fileName: 'runtimeTask.ts',
})

const tempDir = await mkdtemp(join(tmpdir(), 'open-agent-runtime-task-'))
const modulePath = join(tempDir, 'runtimeTask.mjs')
await writeFile(modulePath, compiled.outputText, 'utf8')

try {
  const task = await import(`file:///${modulePath.replace(/\\/g, '/')}`)
  const turn = {
    turn_id: 'turn-1',
    user_input: 'inspect the project',
    status: 'completed',
    metadata: {
      workspace_references: [
        { kind: 'file', name: 'a.ts', path: 'C:\\repo\\src\\a.ts', root: 'C:\\repo\\src' },
      ],
      attachments: [
        { kind: 'attachment', name: 'notes.md', path: 'notes.md', size: 120 },
      ],
      memory_references: [
        { id: 42, category: 'decision', importance: 'high', content: 'Use the stable provider route.' },
      ],
    },
  }
  const events = [
    event(1, 'run_start', { status: 'running' }),
    event(2, 'step_start', { step: 1, max_steps: 3 }),
    event(3, 'tool_call', { tool_call_id: 'call-1', tool_name: 'read_file', arguments: { path: 'a.ts' } }),
    event(4, 'tool_result', { tool_call_id: 'call-1', tool_name: 'read_file', success: true, result: 'ok', elapsed: 0.25 }),
    event(5, 'step_end', { step: 1, elapsed: 0.5 }),
    event(6, 'complete', { status: 'idle', content: 'done' }),
  ]

  const projection = task.buildRuntimeTaskProjection(turn, events)
  assert.deepEqual(projection.references.map(item => item.path), ['C:\\repo\\src\\a.ts', 'notes.md'])
  assert.equal(projection.memories[0].id, '42')
  assert.equal(projection.memories[0].content, 'Use the stable provider route.')
  assert.equal(projection.tools.length, 1)
  assert.equal(projection.tools[0].callId, 'call-1')
  assert.equal(projection.tools[0].name, 'read_file')
  assert.equal(projection.tools[0].status, 'done')
  assert.equal(projection.tools[0].elapsedSeconds, 0.25)
  assert.equal(projection.plan[0].kind, 'request')
  assert.equal(projection.plan.at(-1).kind, 'result')
  assert.equal(projection.plan.at(-1).status, 'done')

  const running = task.buildRuntimeTaskProjection(
    { ...turn, status: 'running' },
    events.slice(0, 3),
  )
  assert.equal(running.tools[0].status, 'active')
  assert.equal(running.plan.at(-1).status, 'active')

  const failed = task.buildRuntimeTaskProjection(
    { ...turn, status: 'failed', error: 'boom' },
    [...events.slice(0, 3), event(4, 'tool_result', { tool_call_id: 'call-1', tool_name: 'read_file', success: false, error: 'denied' }), event(5, 'error', { error: 'boom' })],
  )
  assert.equal(failed.tools[0].status, 'error')
  assert.equal(failed.plan.at(-1).status, 'error')
} finally {
  await rm(tempDir, { recursive: true, force: true })
}

function event(seq, event_type, payload) {
  return {
    event_id: `event-${seq}`,
    seq,
    event_type,
    payload,
    created_at: `2026-07-16T10:00:0${seq}.000Z`,
  }
}
