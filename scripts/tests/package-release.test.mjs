import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'

import {
  buildPyInstallerPlan,
  createMobileBuildArgs,
  createPyInstallerArgs,
  createTauriBundleArgs,
  createTauriCompileArgs,
  desktopBundlePlan,
  mobileReleaseLayout,
  normalizePlatform,
  prepareSpawnCommand,
  releaseLayout,
  runWithRetry,
  shouldPackageDataPath,
  syncDirectory,
  tauriBundleDirectories,
  webUiSourceDigest,
} from '../package-release.mjs'

const root = path.resolve(import.meta.dirname, '..', '..')

test('normalizes the supported host platforms', () => {
  assert.equal(normalizePlatform('win32'), 'windows')
  assert.equal(normalizePlatform('linux'), 'linux')
  assert.throws(() => normalizePlatform('darwin'), /Unsupported build platform/)
})

test('creates separate desktop and CLI release locations', () => {
  const layout = releaseLayout(root, 'linux', 'x64')

  assert.equal(layout.releaseDir, path.join(root, 'dist', 'OpenAgentSeal-linux-x64'))
  assert.equal(layout.desktopDir, path.join(layout.releaseDir, 'desktop'))
  assert.equal(layout.cliDir, path.join(layout.releaseDir, 'cli'))
})

test('creates a stable Android APK release location', () => {
  const layout = mobileReleaseLayout(root)

  assert.equal(layout.releaseDir, path.join(root, 'dist', 'mobile', 'android'))
  assert.equal(
    layout.sourceApk,
    path.join(root, 'open_agent', 'app', 'web', 'android', 'app', 'build', 'outputs', 'apk', 'debug', 'app-debug.apk'),
  )
  assert.equal(layout.outputApk, path.join(layout.releaseDir, 'OpenAgentSeal-Mobile-debug.apk'))
})

test('packages Android from the already-built Web UI', () => {
  assert.deepEqual(createMobileBuildArgs(root), [
    '--prefix',
    path.join(root, 'open_agent', 'app', 'web'),
    'run',
    'mobile:package',
  ])
  assert.deepEqual(createMobileBuildArgs(root, { clean: true }), [
    '--prefix',
    path.join(root, 'open_agent', 'app', 'web'),
    'run',
    'mobile:package:clean',
  ])
})

test('filters Python bytecode caches from packaged data', () => {
  assert.equal(
    shouldPackageDataPath(path.join(root, 'skills', '__pycache__', 'tool.cpython-311.pyc')),
    false,
  )
  assert.equal(shouldPackageDataPath(path.join(root, 'skills', 'tool.pyc')), false)
  assert.equal(shouldPackageDataPath(path.join(root, 'skills', 'tool.py')), true)
})

test('Web UI source digest ignores dependency caches and changes with source content', () => {
  const temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'openagentseal-web-digest-'))
  const webRoot = path.join(temporaryRoot, 'open_agent', 'app', 'web')
  try {
    fs.mkdirSync(path.join(webRoot, 'src'), { recursive: true })
    fs.mkdirSync(path.join(webRoot, 'node_modules', 'example'), { recursive: true })
    fs.writeFileSync(path.join(webRoot, 'src', 'main.ts'), 'export const value = 1\n')
    fs.writeFileSync(path.join(webRoot, 'node_modules', 'example', 'index.js'), 'first\n')
    const initialDigest = webUiSourceDigest(temporaryRoot)

    fs.writeFileSync(path.join(webRoot, 'node_modules', 'example', 'index.js'), 'second\n')
    assert.equal(webUiSourceDigest(temporaryRoot), initialDigest)

    fs.writeFileSync(path.join(webRoot, 'src', 'main.ts'), 'export const value = 2\n')
    assert.notEqual(webUiSourceDigest(temporaryRoot), initialDigest)
  } finally {
    fs.rmSync(temporaryRoot, { recursive: true, force: true })
  }
})

test('incremental data sync does not rewrite files with identical content', () => {
  const temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'openagentseal-sync-'))
  const source = path.join(temporaryRoot, 'source')
  const destination = path.join(temporaryRoot, 'destination')
  try {
    fs.mkdirSync(source)
    fs.mkdirSync(destination)
    fs.writeFileSync(path.join(source, 'asset.txt'), 'same content\n')
    fs.writeFileSync(path.join(destination, 'asset.txt'), 'same content\n')
    const originalTime = new Date('2020-01-01T00:00:00Z')
    fs.utimesSync(path.join(destination, 'asset.txt'), originalTime, originalTime)

    syncDirectory(source, destination)
    assert.equal(fs.statSync(path.join(destination, 'asset.txt')).mtimeMs, originalTime.getTime())

    fs.writeFileSync(path.join(source, 'asset.txt'), 'changed content\n')
    syncDirectory(source, destination)
    assert.equal(fs.readFileSync(path.join(destination, 'asset.txt'), 'utf8'), 'changed content\n')
  } finally {
    fs.rmSync(temporaryRoot, { recursive: true, force: true })
  }
})

test('builds a Linux CLI onedir plan without desktop static assets', () => {
  const plan = buildPyInstallerPlan({
    kind: 'cli',
    platform: 'linux',
    targetTriple: 'x86_64-unknown-linux-gnu',
    root,
    python: 'python3',
  })

  assert.equal(plan.name, 'openagentseal-cli')
  assert.equal(plan.oneFile, false)
  assert.equal(plan.entry.endsWith(path.join('scripts', 'packaging', 'open_agent_cli.py')), true)
  assert.equal(plan.data.some((item) => item.destination === 'open_agent/app/static'), false)
  assert.equal(plan.data.some((item) => item.destination === 'open_agent/skills'), true)
  assert.equal(plan.hiddenImports.includes('win32timezone'), false)
})

test('builds a target-qualified Linux backend sidecar', () => {
  const plan = buildPyInstallerPlan({
    kind: 'backend',
    platform: 'linux',
    targetTriple: 'x86_64-unknown-linux-gnu',
    root,
    python: 'python3',
  })

  assert.equal(plan.name, 'open-agent-backend-x86_64-unknown-linux-gnu')
  assert.equal(plan.oneFile, true)
  assert.equal(plan.hiddenImports.includes('win32timezone'), false)
})

test('builds a Windows backend onefile plan with Web UI and winpty', () => {
  const plan = buildPyInstallerPlan({
    kind: 'backend',
    platform: 'windows',
    targetTriple: 'x86_64-pc-windows-msvc',
    root,
    python: 'python.exe',
    winptyDir: path.join(root, '.venv', 'Lib', 'site-packages', 'winpty'),
  })

  assert.equal(plan.name, 'open-agent-backend-x86_64-pc-windows-msvc')
  assert.equal(plan.oneFile, true)
  assert.equal(plan.data.some((item) => item.destination === 'open_agent/app/static'), true)
  assert.deepEqual(
    plan.binaries.map((item) => path.basename(item.source)).sort(),
    ['OpenConsole.exe', 'winpty-agent.exe'],
  )
  assert.equal(plan.hiddenImports.includes('win32timezone'), true)
  const args = createPyInstallerArgs(plan, {
    root,
    distPath: path.join(root, 'build', 'backend-dist'),
    workPath: path.join(root, 'build', 'backend-work'),
    specPath: path.join(root, 'build', 'backend-spec'),
  })
  const importIndex = args.indexOf('win32timezone')
  assert.equal(importIndex > 0, true)
  assert.equal(args[importIndex - 1], '--hidden-import')
})

test('renders platform-correct PyInstaller arguments', () => {
  const plan = buildPyInstallerPlan({
    kind: 'cli',
    platform: 'linux',
    targetTriple: 'x86_64-unknown-linux-gnu',
    root,
    python: 'python3',
  })
  const args = createPyInstallerArgs(plan, {
    root,
    distPath: path.join(root, 'build', 'cli-dist'),
    workPath: path.join(root, 'build', 'cli-work'),
    specPath: path.join(root, 'build', 'cli-spec'),
  })

  assert.equal(args.includes('--onefile'), false)
  assert.equal(args.includes('--clean'), false)
  assert.equal(
    args.includes(`${path.join(root, 'open_agent', 'skills')}:open_agent/skills`),
    true,
  )

  const cleanArgs = createPyInstallerArgs(plan, {
    root,
    distPath: path.join(root, 'build', 'cli-dist'),
    workPath: path.join(root, 'build', 'cli-work'),
    specPath: path.join(root, 'build', 'cli-spec'),
    clean: true,
  })
  assert.equal(cleanArgs.includes('--clean'), true)
})

test('compiles Tauri once and creates isolated native bundle commands', () => {
  assert.deepEqual(createTauriCompileArgs(root), [
    '--prefix',
    path.join(root, 'desktop'),
    'run',
    'tauri:compile',
    '--',
    '--no-bundle',
  ])
  assert.deepEqual(createTauriBundleArgs('windows', root, 'nsis'), [
    '--prefix',
    path.join(root, 'desktop'),
    'run',
    'tauri:bundle',
    '--',
    '--bundles',
    'nsis',
  ])
  assert.deepEqual(createTauriBundleArgs('linux', root, 'appimage'), [
    '--prefix',
    path.join(root, 'desktop'),
    'run',
    'tauri:bundle',
    '--',
    '--bundles',
    'appimage',
  ])
  assert.throws(
    () => createTauriBundleArgs('linux', root, 'msi'),
    /Unsupported linux Tauri bundle/,
  )
})

test('builds each desktop bundle independently with retries for downloaded tools', () => {
  assert.deepEqual(desktopBundlePlan('windows'), [
    { bundle: 'nsis', attempts: 3 },
    { bundle: 'msi', attempts: 3 },
  ])
  assert.deepEqual(desktopBundlePlan('linux'), [
    { bundle: 'deb', attempts: 1 },
    { bundle: 'appimage', attempts: 3 },
  ])
})

test('isolates the current platform Tauri bundle output directories', () => {
  const bundleRoot = path.join(root, 'desktop', 'src-tauri', 'target', 'release', 'bundle')

  assert.deepEqual(tauriBundleDirectories(root, 'windows'), [
    path.join(bundleRoot, 'nsis'),
    path.join(bundleRoot, 'msi'),
  ])
  assert.deepEqual(tauriBundleDirectories(root, 'linux'), [
    path.join(bundleRoot, 'deb'),
    path.join(bundleRoot, 'appimage'),
  ])
})

test('retries only the failing packaging operation', () => {
  let attempts = 0
  const retries = []

  const result = runWithRetry(
    () => {
      attempts += 1
      if (attempts < 3) throw new Error(`transient failure ${attempts}`)
      return 'done'
    },
    {
      attempts: 3,
      delay: () => {},
      onRetry: (attempt, total, error) => retries.push([attempt, total, error.message]),
    },
  )

  assert.equal(result, 'done')
  assert.deepEqual(retries, [
    [1, 3, 'transient failure 1'],
    [2, 3, 'transient failure 2'],
  ])
})

test('runs npm through cmd.exe on Windows', () => {
  assert.deepEqual(
    prepareSpawnCommand('npm', ['run', 'build'], 'win32', 'C:\\Windows\\System32\\cmd.exe'),
    {
      command: 'C:\\Windows\\System32\\cmd.exe',
      args: ['/d', '/s', '/c', 'npm.cmd', 'run', 'build'],
    },
  )
  assert.deepEqual(prepareSpawnCommand('npm', ['run', 'build'], 'linux'), {
    command: 'npm',
    args: ['run', 'build'],
  })
})
