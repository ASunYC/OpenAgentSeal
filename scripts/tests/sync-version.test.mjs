import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'

import {
  androidVersionCode,
  isValidVersion,
  replaceFirstJsonVersion,
  syncVersion,
} from '../sync-version.mjs'

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

test('maps semantic versions to monotonically increasing Android version codes', () => {
  assert.equal(androidVersionCode('0.1.0'), 1000)
  assert.equal(androidVersionCode('1.2.3'), 1002003)
  assert.equal(androidVersionCode('1.2.3-beta.1'), 1002003)
})

test('syncs non-Android release versions when the Android project is excluded', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'openagentseal-version-sync-'))
  const files = {
    'version.json': '{"version":"1.2.3"}',
    'pyproject.toml': 'version = "0.0.1"\n',
    'open_agent/version.py': 'DEFAULT_VERSION = "0.0.1"\n',
    'open_agent/cli.py': 'version="open-agent 0.0.1"\n',
    'open_agent/acp/__init__.py': 'AgentInfo(version="0.0.1")\n',
    'desktop/src-tauri/Cargo.toml': 'version = "0.0.1"\n',
    'desktop/package.json': '{"version":"0.0.1"}\n',
    'open_agent/app/web/package.json': '{"version":"0.0.1"}\n',
    'desktop/src-tauri/tauri.conf.json': '{"version":"0.0.1"}\n',
    'desktop/package-lock.json': '{"version":"0.0.1","packages":{"":{"version":"0.0.1"}}}\n',
    'open_agent/app/web/package-lock.json': '{"version":"0.0.1","packages":{"":{"version":"0.0.1"}}}\n',
  }
  try {
    for (const [relativePath, content] of Object.entries(files)) {
      const file = path.join(root, relativePath)
      fs.mkdirSync(path.dirname(file), { recursive: true })
      fs.writeFileSync(file, content)
    }

    assert.doesNotThrow(() => syncVersion(root, { skipAndroid: true }))
    assert.match(fs.readFileSync(path.join(root, 'pyproject.toml'), 'utf8'), /1\.2\.3/)
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})
