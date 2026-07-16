import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'

import { runWithRetry } from '../build-linux-docker.mjs'

const root = path.resolve(import.meta.dirname, '..', '..')
const escapeRegExp = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

test('Linux builder is pinned to the Ubuntu 22.04 amd64 image with Tauri dependencies', () => {
  const dockerfile = fs.readFileSync(
    path.join(root, 'scripts', 'docker', 'linux-x64.Dockerfile'),
    'utf8',
  )

  assert.match(
    dockerfile,
    /FROM mcr\.microsoft\.com\/mirror\/docker\/library\/ubuntu@sha256:[0-9a-f]{64}/,
  )
  assert.match(dockerfile, /libwebkit2gtk-4\.1-dev/)
  assert.match(dockerfile, /libayatana-appindicator3-dev/)
  assert.match(dockerfile, /APPIMAGE_EXTRACT_AND_RUN=1/)
  assert.match(dockerfile, /mirrors\.aliyun\.com\/ubuntu/)
  assert.match(dockerfile, /Acquire::Retries=5/)
  assert.match(dockerfile, /Acquire::http::Pipeline-Depth=0/)
  assert.match(dockerfile, /--fix-missing/)
  assert.match(dockerfile, /type=cache,target=\/var\/cache\/apt/)
  assert.match(dockerfile, /type=cache,target=\/root\/\.cache\/pip/)
  assert.match(dockerfile, /type=cache,target=\/root\/\.npm/)
  assert.match(dockerfile, /type=cache,target=\/root\/\.cargo\/registry/)
  assert.match(dockerfile, /type=cache[^\n]*target=\/workspace\/\.venv/)
  assert.match(dockerfile, /type=cache[^\n]*target=\/workspace\/build\/pyinstaller/)
  assert.match(dockerfile, /\/api\/health/)
  assert.match(dockerfile, /__pycache__/)
  assert.doesNotMatch(dockerfile, /docker\/dockerfile:/)
  assert.match(dockerfile, /OpenAgentSeal-linux-x64/)

  const dependencyCopy = dockerfile.indexOf('COPY desktop/package.json')
  const sourceCopy = dockerfile.indexOf('COPY . .')
  assert.notEqual(dependencyCopy, -1)
  assert.ok(dependencyCopy < sourceCopy)
})

test('Docker build context excludes local build environments', () => {
  const dockerignore = fs.readFileSync(path.join(root, '.dockerignore'), 'utf8')

  for (const item of [
    '.git',
    '.venv',
    'node_modules',
    'dist',
    'desktop/src-tauri/target',
    '**/__pycache__',
    '**/*.pyc',
  ]) {
    assert.match(dockerignore, new RegExp(`^${escapeRegExp(item)}/?$`, 'm'))
  }
})

test('Docker build retries transient registry failures', async () => {
  const statuses = [1, 1, 0]
  const delays = []
  const result = await runWithRetry(
    () => ({ status: statuses.shift() }),
    { attempts: 3, delay: async (milliseconds) => delays.push(milliseconds) },
  )

  assert.equal(result.status, 0)
  assert.deepEqual(delays, [2000, 4000])
})
