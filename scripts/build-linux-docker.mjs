#!/usr/bin/env node

import fs from 'node:fs'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const scriptPath = fileURLToPath(import.meta.url)
const scriptDir = path.dirname(scriptPath)
const root = path.resolve(scriptDir, '..')
const output = path.join(root, 'dist', 'OpenAgentSeal-linux-x64')

const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds))

export async function runWithRetry(
  run,
  { attempts = 3, delay = wait, onRetry = () => {} } = {},
) {
  let result
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    result = run()
    if (result.error) throw result.error
    if (result.status === 0) return result
    if (attempt < attempts) {
      const delayMs = attempt * 2000
      onRetry(attempt, attempts, delayMs)
      await delay(delayMs)
    }
  }
  return result
}

function runDockerBuild() {
  return spawnSync(
    'docker',
    [
      'buildx',
      'build',
      '--platform',
      'linux/amd64',
      '--file',
      path.join(root, 'scripts', 'docker', 'linux-x64.Dockerfile'),
      '--target',
      'export',
      '--output',
      `type=local,dest=${output.split(path.sep).join('/')}`,
      root,
    ],
    { cwd: root, stdio: 'inherit' },
  )
}

async function main() {
  fs.rmSync(output, { recursive: true, force: true })
  fs.mkdirSync(output, { recursive: true })

  const result = await runWithRetry(runDockerBuild, {
    onRetry: (attempt, attempts, delayMs) => {
      process.stderr.write(
        `Docker build attempt ${attempt}/${attempts} failed; retrying in ${delayMs / 1000}s...\n`,
      )
    },
  })

  if (result.status !== 0) process.exit(result.status ?? 1)
  process.stdout.write(`Linux release artifacts: ${output}\n`)
}

if (process.argv[1] && path.resolve(process.argv[1]) === scriptPath) {
  await main()
}
