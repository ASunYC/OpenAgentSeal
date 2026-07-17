#!/usr/bin/env node

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url))
const DEFAULT_ROOT = path.resolve(SCRIPT_DIR, '..')

export function isValidVersion(version) {
  return /^\d+\.\d+\.\d+(?:[-.][0-9A-Za-z.-]+)?$/.test(version)
}

export function replaceFirstJsonVersion(content, version) {
  return content.replace(/("version"\s*:\s*")[^"]+(")/m, `$1${version}$2`)
}

export function androidVersionCode(version) {
  if (!isValidVersion(version)) throw new Error(`Invalid Android version: ${version}`)
  const [major, minor, patch] = version.split(/[.-]/, 3).map(Number)
  if (minor > 999 || patch > 999) {
    throw new Error(`Android version components must be below 1000: ${version}`)
  }
  const code = major * 1_000_000 + minor * 1_000 + patch
  if (code <= 0 || code > 2_100_000_000) {
    throw new Error(`Android versionCode is out of range: ${code}`)
  }
  return code
}

function replaceFirst(content, pattern, replacement, description) {
  if (!pattern.test(content)) throw new Error(`Version field not found in ${description}`)
  pattern.lastIndex = 0
  return content.replace(pattern, replacement)
}

function replaceFirstN(content, pattern, replacement, count, description) {
  let replaced = 0
  const result = content.replace(pattern, (...args) => {
    if (replaced >= count) return args[0]
    replaced += 1
    return typeof replacement === 'function' ? replacement(...args) : replacement
  })
  if (replaced !== count) throw new Error(`Expected ${count} version fields in ${description}`)
  return result
}

function updateFile(root, relativePath, updater) {
  const file = path.join(root, relativePath)
  const content = fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '')
  const updated = updater(content)
  if (updated !== content) fs.writeFileSync(file, updated, 'utf8')
}

export function syncVersion(root = DEFAULT_ROOT, { skipAndroid = false } = {}) {
  const versionFile = path.join(root, 'version.json')
  const version = JSON.parse(fs.readFileSync(versionFile, 'utf8')).version
  if (!isValidVersion(version)) throw new Error(`Invalid version in version.json: ${version}`)

  const textUpdates = [
    ['pyproject.toml', /^(version\s*=\s*)"[^"]+"/m, `$1"${version}"`],
    ['open_agent/version.py', /^(DEFAULT_VERSION\s*=\s*)"[^"]+"/m, `$1"${version}"`],
    ['open_agent/cli.py', /version="open-agent [^"]+"/, `version="open-agent ${version}"`],
    ['open_agent/acp/__init__.py', /version="[^"]+"\)/, `version="${version}")`],
    ['desktop/src-tauri/Cargo.toml', /^(version\s*=\s*)"[^"]+"/m, `$1"${version}"`],
  ]
  if (!skipAndroid) {
    textUpdates.push(
      [
        'open_agent/app/web/android/app/build.gradle',
        /^(\s*versionCode\s+)\d+/m,
        `$1${androidVersionCode(version)}`,
      ],
      [
        'open_agent/app/web/android/app/build.gradle',
        /^(\s*versionName\s+)"[^"]+"/m,
        `$1"${version}"`,
      ],
    )
  }
  for (const [relativePath, pattern, replacement] of textUpdates) {
    updateFile(root, relativePath, (content) =>
      replaceFirst(content, pattern, replacement, relativePath),
    )
  }

  for (const relativePath of [
    'desktop/package.json',
    'open_agent/app/web/package.json',
    'desktop/src-tauri/tauri.conf.json',
  ]) {
    updateFile(root, relativePath, (content) => replaceFirstJsonVersion(content, version))
  }

  for (const relativePath of [
    'desktop/package-lock.json',
    'open_agent/app/web/package-lock.json',
  ]) {
    updateFile(root, relativePath, (content) =>
      replaceFirstN(
        content,
        /("version"\s*:\s*")[^"]+(")/g,
        (match, prefix, suffix) => `${prefix}${version}${suffix}`,
        2,
        relativePath,
      ),
    )
  }

  process.stdout.write(`Synced OpenAgentSeal version: ${version}\n`)
  return version
}

const invokedPath = process.argv[1] ? pathToFileURL(path.resolve(process.argv[1])).href : ''
if (invokedPath === import.meta.url) syncVersion()
