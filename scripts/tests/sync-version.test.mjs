import assert from 'node:assert/strict'
import test from 'node:test'

import { isValidVersion, replaceFirstJsonVersion } from '../sync-version.mjs'

test('accepts semantic release versions and rejects malformed values', () => {
  assert.equal(isValidVersion('1.2.3'), true)
  assert.equal(isValidVersion('1.2.3-beta.1'), true)
  assert.equal(isValidVersion('1.2'), false)
})

test('updates only the first JSON version field', () => {
  const source = '{\n  "version": "0.1.0",\n  "nested": {"version": "keep"}\n}\n'
  assert.equal(
    replaceFirstJsonVersion(source, '2.0.0'),
    '{\n  "version": "2.0.0",\n  "nested": {"version": "keep"}\n}\n',
  )
})
