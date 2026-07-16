import assert from 'node:assert/strict'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import ts from 'typescript'

const sourcePath = new URL('../src/models/messageQueue.ts', import.meta.url)
const source = await readFile(sourcePath, 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ES2022,
    target: ts.ScriptTarget.ES2022,
    importsNotUsedAsValues: ts.ImportsNotUsedAsValues.Remove,
    verbatimModuleSyntax: false,
  },
  fileName: 'messageQueue.ts',
})

const tempDir = await mkdtemp(join(tmpdir(), 'open-agent-message-queue-'))
const modulePath = join(tempDir, 'messageQueue.mjs')
await writeFile(modulePath, compiled.outputText, 'utf8')

try {
  const queue = await import(`file:///${modulePath.replace(/\\/g, '/')}`)
  const normal = queue.createQueueItem({
    content: 'normal',
    kind: 'normal',
    scope: { agentId: 'main', sessionId: 'session-1' },
    now: '2026-07-16T10:00:00.000Z',
    id: 'normal-1',
  })
  const interrupt = queue.createQueueItem({
    content: 'urgent',
    kind: 'interrupt',
    scope: { agentId: 'main', sessionId: 'session-1' },
    now: '2026-07-16T10:01:00.000Z',
    id: 'interrupt-1',
  })

  assert.equal(queue.selectNextQueueItem([normal, interrupt])?.id, 'interrupt-1')

  const sending = queue.markQueueItemSending(interrupt)
  assert.equal(sending.status, 'sending')
  assert.equal(sending.attemptCount, 1)
  assert.equal(queue.selectNextQueueItem([normal, sending])?.id, 'normal-1')

  const failed = queue.markQueueItemFailed(sending, 'network unavailable')
  assert.equal(failed.status, 'failed')
  assert.equal(failed.error, 'network unavailable')
  assert.equal(queue.selectNextQueueItem([failed]), null)

  const retried = queue.retryQueueItem(failed)
  assert.equal(retried.status, 'queued')
  assert.equal(retried.error, '')
  assert.equal(retried.attemptCount, 1)

  const restored = queue.parseStoredQueue(JSON.stringify([
    sending,
    failed,
    { id: 'empty', content: '', attachments: [] },
    null,
  ]), { agentId: 'main', sessionId: 'session-1' })
  assert.equal(restored.length, 2)
  assert.equal(restored[0].status, 'queued')
  assert.equal(restored[0].id, 'interrupt-1')
  assert.equal(restored[1].status, 'failed')
  assert.deepEqual(queue.parseStoredQueue('{bad json', { agentId: 'main', sessionId: 'session-1' }), [])

  const otherSession = queue.parseStoredQueue(JSON.stringify([normal]), {
    agentId: 'main',
    sessionId: 'session-2',
  })
  assert.equal(otherSession.length, 0)
} finally {
  await rm(tempDir, { recursive: true, force: true })
}
