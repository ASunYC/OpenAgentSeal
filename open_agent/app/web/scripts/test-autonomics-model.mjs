import assert from 'node:assert/strict'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import ts from 'typescript'

const sourcePath = new URL('../src/models/autonomics.ts', import.meta.url)
const source = await readFile(sourcePath, 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ES2022,
    target: ts.ScriptTarget.ES2022,
    importsNotUsedAsValues: ts.ImportsNotAsValues?.Remove,
    verbatimModuleSyntax: false,
  },
  fileName: 'autonomics.ts',
})

const tempDir = await mkdtemp(join(tmpdir(), 'open-agent-autonomics-'))
const modulePath = join(tempDir, 'autonomics.mjs')
await writeFile(modulePath, compiled.outputText, 'utf8')

try {
  const model = await import(`file:///${modulePath.replace(/\\/g, '/')}`)

  const active = model.projectStatus('running')
  assert.deepEqual(active, {
    value: 'running', label: 'Running', tone: 'active', terminal: false, known: true,
  })
  assert.deepEqual(model.projectStatus('future-state'), {
    value: 'unknown', label: 'Unknown state', tone: 'neutral', terminal: false, known: false,
  })

  const redacted = model.redactOperationalValue({
    safe_count: 4,
    credential: 'should-never-render',
    nested: { authorization: 'Bearer secret', token_hint: 'hidden', state: 'ready' },
    rows: [{ attachment_url: 'https://private.invalid', attempt: 2 }],
  })
  assert.equal(redacted.credential, '[REDACTED]')
  assert.equal(redacted.nested.authorization, '[REDACTED]')
  assert.equal(redacted.nested.token_hint, '[REDACTED]')
  assert.equal(redacted.rows[0].attachment_url, '[REDACTED]')
  assert.equal(redacted.nested.state, 'ready')
  assert.equal(JSON.stringify(redacted).includes('should-never-render'), false)

  const account = model.projectChannelAccount({
    account_id: 'slack-primary', adapter_kind: 'slack', enabled: true,
    credential_ref: 'opaque:credential-reference', credential: 'never',
    updated_at: '2026-08-12T02:00:00Z', version: 7,
    allowed_actions: ['disable', 'rotate_credential', 'delete'],
  })
  assert.equal(account.credential.configured, true)
  assert.equal(account.credential.writeOnly, true)
  assert.equal('value' in account.credential, false)
  assert.equal(JSON.stringify(account).includes('opaque:credential-reference'), false)
  assert.equal(JSON.stringify(account).includes('never'), false)
  assert.ok(Object.isFrozen(account))

  const unknownDelivery = model.projectDelivery({
    obligation_id: 'outbox-7', state: 'delivery_unknown', attempt: 3,
    allowed_actions: ['reconcile', 'manual_resend'],
  }, 'operator')
  assert.equal(unknownDelivery.risk, 'critical')
  assert.equal(unknownDelivery.warningCode, 'duplicate_delivery_possible')
  assert.equal(unknownDelivery.requiresTypedConfirmation, true)
  assert.deepEqual(unknownDelivery.actions, ['reconcile', 'manual_resend'])
  assert.deepEqual(model.projectDelivery({ state: 'future' }, 'operator').actions, [])
  assert.deepEqual(model.projectDelivery({ state: 'delivery_unknown' }, 'viewer').actions, [])

  const run = model.projectSchedulerRun({
    run_id: 'run-12', job_id: 'job-3', state: 'retry_wait', attempt: 2,
    next_attempt_at: '2026-08-12T03:00:00Z', allowed_actions: ['retry'],
  }, 'operator')
  assert.equal(run.attemptNumber, 3)
  assert.equal(run.retryScheduled, true)
  assert.deepEqual(run.actions, ['retry'])

  const budgets = model.projectGoalBudgets({
    consumed_iterations: 4, max_iterations: 10,
    consumed_tokens: 1750, max_tokens: 5000,
    consumed_estimated_cost: 6.25, max_estimated_cost: 20,
    consumed_active_seconds: 420, max_wall_clock_seconds: 1200,
  })
  assert.deepEqual(budgets.map(item => item.kind), ['iterations', 'tokens', 'cost', 'active_time'])
  assert.deepEqual(budgets.map(item => item.percent), [40, 35, 31.25, 35])
  assert.equal(budgets.every(item => item.exhausted === false), true)
  assert.equal(model.projectGoalBudgets({ consumed_tokens: 12, max_tokens: 0 })[1].percent, 0)

  assert.deepEqual(model.legalActions({
    resource: 'goal', state: 'paused', role: 'operator',
    serverAllowed: ['resume', 'cancel', 'delete'],
    capabilities: { resume: true, cancel: false },
  }), ['resume'])
  assert.deepEqual(model.legalActions({
    resource: 'goal', state: 'paused', role: 'viewer',
    serverAllowed: ['resume'], capabilities: { resume: true },
  }), [])
  assert.deepEqual(model.legalActions({
    resource: 'unknown', state: 'unknown', role: 'admin',
    serverAllowed: ['delete'], capabilities: { delete: true },
  }), [])

  const draft = Object.freeze({ enabled: false, note: 'preserve this draft' })
  const request = model.versionedMutation(draft, 9)
  assert.deepEqual(request, { enabled: false, note: 'preserve this draft', expected_version: 9 })
  assert.notEqual(request, draft)
  assert.deepEqual(draft, { enabled: false, note: 'preserve this draft' })

  assert.equal(model.isCurrentSelection('goal-a', 'goal-a', 4, 4), true)
  assert.equal(model.isCurrentSelection('goal-a', 'goal-b', 4, 4), false)
  assert.equal(model.isCurrentSelection('goal-a', 'goal-a', 3, 4), false)
} finally {
  await rm(tempDir, { recursive: true, force: true })
}
