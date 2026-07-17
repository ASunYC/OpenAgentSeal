#!/usr/bin/env node

import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { spawnSync } from 'node:child_process'
import { fileURLToPath, pathToFileURL } from 'node:url'

import { syncVersion } from './sync-version.mjs'

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url))
const DEFAULT_ROOT = path.resolve(SCRIPT_DIR, '..')

export function normalizePlatform(platform = process.platform) {
  if (platform === 'win32' || platform === 'windows') return 'windows'
  if (platform === 'linux') return 'linux'
  throw new Error(`Unsupported build platform: ${platform}`)
}

export function normalizeArchitecture(architecture = process.arch) {
  if (architecture === 'x64' || architecture === 'x86_64') return 'x64'
  throw new Error(`Unsupported build architecture: ${architecture}`)
}

export function shouldPackageDataPath(source) {
  const segments = path.normalize(source).split(path.sep)
  return (
    !segments.includes('__pycache__') &&
    !['.pyc', '.pyo'].includes(path.extname(source).toLowerCase())
  )
}

export function releaseLayout(root, platform, architecture) {
  const releaseDir = path.join(
    root,
    'dist',
    `OpenAgentSeal-${normalizePlatform(platform)}-${normalizeArchitecture(architecture)}`,
  )
  return {
    releaseDir,
    desktopDir: path.join(releaseDir, 'desktop'),
    cliDir: path.join(releaseDir, 'cli'),
  }
}

export function mobileReleaseLayout(root = DEFAULT_ROOT) {
  const releaseDir = path.join(root, 'dist', 'mobile', 'android')
  return {
    releaseDir,
    sourceApk: path.join(
      root,
      'open_agent',
      'app',
      'web',
      'android',
      'app',
      'build',
      'outputs',
      'apk',
      'debug',
      'app-debug.apk',
    ),
    outputApk: path.join(releaseDir, 'OpenAgentSeal-Mobile-debug.apk'),
  }
}

function dataItem(root, source, destination) {
  return { source: path.join(root, source), destination }
}

export function buildPyInstallerPlan({
  kind,
  platform,
  targetTriple,
  root = DEFAULT_ROOT,
  python,
  winptyDir,
}) {
  const normalizedPlatform = normalizePlatform(platform)
  if (kind !== 'backend' && kind !== 'cli') {
    throw new Error(`Unsupported PyInstaller target: ${kind}`)
  }

  const data = [
    dataItem(root, path.join('open_agent', 'config'), 'open_agent/config'),
    dataItem(root, path.join('open_agent', 'skills'), 'open_agent/skills'),
    dataItem(
      root,
      path.join('open_agent', 'plugins', 'bundled'),
      'open_agent/plugins/bundled',
    ),
  ]
  if (kind === 'backend') {
    data.unshift(
      dataItem(root, path.join('open_agent', 'app', 'static'), 'open_agent/app/static'),
    )
  }

  const binaries = []
  if (kind === 'backend' && normalizedPlatform === 'windows') {
    if (!winptyDir) {
      throw new Error('winptyDir is required for a Windows backend build')
    }
    binaries.push(
      { source: path.join(winptyDir, 'winpty-agent.exe'), destination: 'winpty' },
      { source: path.join(winptyDir, 'OpenConsole.exe'), destination: 'winpty' },
    )
  }

  const hiddenImports = [
    'open_agent.plugins.builtin.mineru_mcp',
    'open_agent.plugins.builtin.mineru_service',
    'markdown',
  ]
  if (kind === 'backend') {
    hiddenImports.push(
      'open_agent.cli',
      'uvicorn.logging',
      'uvicorn.loops',
      'uvicorn.loops.auto',
      'uvicorn.protocols',
      'uvicorn.protocols.http',
      'uvicorn.protocols.http.auto',
      'uvicorn.protocols.websockets',
      'uvicorn.protocols.websockets.auto',
      'uvicorn.lifespan',
      'uvicorn.lifespan.on',
    )
  }

  return {
    kind,
    platform: normalizedPlatform,
    python,
    name:
      kind === 'backend'
        ? `open-agent-backend-${targetTriple}`
        : 'openagentseal-cli',
    entry:
      kind === 'backend'
        ? path.join(root, 'desktop', 'backend', 'open_agent_backend.py')
        : path.join(root, 'scripts', 'packaging', 'open_agent_cli.py'),
    oneFile: kind === 'backend' || normalizedPlatform === 'windows',
    data,
    binaries,
    hiddenImports,
  }
}

export function createPyInstallerArgs(
  plan,
  { root = DEFAULT_ROOT, distPath, workPath, specPath, clean = false },
) {
  const separator = plan.platform === 'windows' ? ';' : ':'
  const args = [
    '-m',
    'PyInstaller',
    '--noconfirm',
    '--name',
    plan.name,
    '--paths',
    root,
    '--distpath',
    distPath,
    '--workpath',
    workPath,
    '--specpath',
    specPath,
  ]
  if (clean) args.push('--clean')
  if (plan.oneFile) args.push('--onefile')
  for (const item of plan.data) {
    args.push('--add-data', `${item.source}${separator}${item.destination}`)
  }
  for (const item of plan.binaries) {
    args.push('--add-binary', `${item.source}${separator}${item.destination}`)
  }
  for (const hiddenImport of plan.hiddenImports) {
    args.push('--hidden-import', hiddenImport)
  }
  args.push(plan.entry)
  return args
}

export function createTauriCompileArgs(root = DEFAULT_ROOT) {
  return [
    '--prefix',
    path.join(root, 'desktop'),
    'run',
    'tauri:compile',
    '--',
    '--no-bundle',
  ]
}

export function createMobileBuildArgs(root = DEFAULT_ROOT, { clean = false } = {}) {
  return [
    '--prefix',
    path.join(root, 'open_agent', 'app', 'web'),
    'run',
    clean ? 'mobile:package:clean' : 'mobile:package',
  ]
}

export function createTauriBundleArgs(platform, root = DEFAULT_ROOT, bundle) {
  const normalizedPlatform = normalizePlatform(platform)
  const supportedBundles =
    normalizedPlatform === 'windows' ? new Set(['nsis', 'msi']) : new Set(['deb', 'appimage'])
  if (!supportedBundles.has(bundle)) {
    throw new Error(`Unsupported ${normalizedPlatform} Tauri bundle: ${bundle}`)
  }
  return [
    '--prefix',
    path.join(root, 'desktop'),
    'run',
    'tauri:bundle',
    '--',
    '--bundles',
    bundle,
  ]
}

export function desktopBundlePlan(platform) {
  return normalizePlatform(platform) === 'windows'
    ? [
        { bundle: 'nsis', attempts: 3 },
        { bundle: 'msi', attempts: 3 },
      ]
    : [
        { bundle: 'deb', attempts: 1 },
        { bundle: 'appimage', attempts: 3 },
      ]
}

export function tauriBundleDirectories(root, platform) {
  const bundleRoot = path.join(root, 'desktop', 'src-tauri', 'target', 'release', 'bundle')
  return desktopBundlePlan(platform).map(({ bundle }) => path.join(bundleRoot, bundle))
}

export function prepareSpawnCommand(
  command,
  args,
  platform = process.platform,
  commandProcessor = process.env.ComSpec || 'cmd.exe',
) {
  if (platform === 'win32' && command === 'npm') {
    return {
      command: commandProcessor,
      args: ['/d', '/s', '/c', 'npm.cmd', ...args],
    }
  }
  return { command, args }
}

function sleep(milliseconds) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, milliseconds)
}

export function runWithRetry(
  operation,
  { attempts = 3, delay = sleep, onRetry = () => {} } = {},
) {
  if (!Number.isInteger(attempts) || attempts < 1) {
    throw new Error('Retry attempts must be a positive integer')
  }

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return operation()
    } catch (error) {
      if (attempt === attempts) throw error
      onRetry(attempt, attempts, error)
      delay(attempt * 5000)
    }
  }

  throw new Error('Retry operation did not run')
}

function run(command, args, { cwd = DEFAULT_ROOT, env = process.env, capture = false } = {}) {
  const invocation = prepareSpawnCommand(command, args)
  const result = spawnSync(invocation.command, invocation.args, {
    cwd,
    env,
    encoding: 'utf8',
    stdio: capture ? ['ignore', 'pipe', 'pipe'] : 'inherit',
  })
  if (result.error) throw result.error
  if (result.status !== 0) {
    const details = capture ? `\n${result.stderr || result.stdout || ''}` : ''
    throw new Error(`${command} ${args.join(' ')} failed with exit code ${result.status}${details}`)
  }
  return capture ? String(result.stdout || '').trim() : ''
}

function findPython(root, platform) {
  if (process.env.OPEN_AGENT_BUILD_PYTHON) return process.env.OPEN_AGENT_BUILD_PYTHON
  const candidates =
    platform === 'windows'
      ? [path.join(root, '.venv', 'Scripts', 'python.exe'), 'python']
      : [path.join(root, '.venv', 'bin', 'python'), 'python3', 'python']
  return candidates.find((candidate) => !path.isAbsolute(candidate) || fs.existsSync(candidate))
}

function rustTargetTriple() {
  const direct = spawnSync('rustc', ['--print', 'host-tuple'], { encoding: 'utf8' })
  if (direct.status === 0 && direct.stdout.trim()) return direct.stdout.trim()
  const verbose = run('rustc', ['-Vv'], { capture: true })
  const host = verbose.match(/^host:\s*(\S+)/m)?.[1]
  if (!host) throw new Error('Unable to determine the Rust host target triple')
  return host
}

function resolveWinptyDir(python) {
  return run(
    python,
    ['-c', 'import pathlib, winpty; print(pathlib.Path(winpty.__file__).parent)'],
    { capture: true },
  )
}

function recreateDirectory(directory) {
  fs.rmSync(directory, { recursive: true, force: true })
  fs.mkdirSync(directory, { recursive: true })
}

function requirePath(target, description) {
  if (!fs.existsSync(target)) throw new Error(`${description} was not created: ${target}`)
  return target
}

function copyDirectory(source, destination) {
  requirePath(source, 'Source directory')
  fs.cpSync(source, destination, {
    recursive: true,
    force: true,
    filter: shouldPackageDataPath,
  })
}

function filesHaveSameContent(source, destination) {
  if (!fs.existsSync(destination)) return false
  const sourceStat = fs.statSync(source)
  const destinationStat = fs.statSync(destination)
  if (!destinationStat.isFile() || sourceStat.size !== destinationStat.size) return false
  return fs.readFileSync(source).equals(fs.readFileSync(destination))
}

export function syncDirectory(source, destination) {
  requirePath(source, 'Source directory')
  fs.mkdirSync(destination, { recursive: true })

  for (const entry of fs.readdirSync(destination, { withFileTypes: true })) {
    const sourcePath = path.join(source, entry.name)
    const destinationPath = path.join(destination, entry.name)
    if (!fs.existsSync(sourcePath) || !shouldPackageDataPath(sourcePath)) {
      fs.rmSync(destinationPath, { recursive: true, force: true })
      continue
    }
    const sourceIsDirectory = fs.statSync(sourcePath).isDirectory()
    if (sourceIsDirectory !== entry.isDirectory()) {
      fs.rmSync(destinationPath, { recursive: true, force: true })
    }
  }

  for (const entry of fs.readdirSync(source, { withFileTypes: true })) {
    const sourcePath = path.join(source, entry.name)
    if (!shouldPackageDataPath(sourcePath)) continue
    const destinationPath = path.join(destination, entry.name)
    if (entry.isDirectory()) {
      syncDirectory(sourcePath, destinationPath)
    } else if (entry.isFile() && !filesHaveSameContent(sourcePath, destinationPath)) {
      fs.copyFileSync(sourcePath, destinationPath)
      const sourceStat = fs.statSync(sourcePath)
      fs.utimesSync(destinationPath, sourceStat.atime, sourceStat.mtime)
    }
  }
}

function stagePlanData(plan, stagingRoot, { clean = false } = {}) {
  if (clean) recreateDirectory(stagingRoot)
  else fs.mkdirSync(stagingRoot, { recursive: true })
  return {
    ...plan,
    data: plan.data.map((item, index) => {
      const stagedSource = path.join(stagingRoot, `${index}-${path.basename(item.source)}`)
      syncDirectory(item.source, stagedSource)
      return { ...item, source: stagedSource }
    }),
  }
}

function walkFiles(directory) {
  if (!fs.existsSync(directory)) return []
  const files = []
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const fullPath = path.join(directory, entry.name)
    if (entry.isDirectory()) files.push(...walkFiles(fullPath))
    else if (entry.isFile()) files.push(fullPath)
  }
  return files
}

export function webUiSourceDigest(root = DEFAULT_ROOT) {
  const webRoot = path.join(root, 'open_agent', 'app', 'web')
  const ignoredDirectories = new Set(['node_modules', 'coverage', 'dist'])
  const hash = crypto.createHash('sha256')
  for (const file of walkFiles(webRoot).sort()) {
    const relativePath = path.relative(webRoot, file)
    if (relativePath.split(path.sep).some((part) => ignoredDirectories.has(part))) continue
    hash.update(relativePath.split(path.sep).join('/'))
    hash.update('\0')
    hash.update(fs.readFileSync(file))
    hash.update('\0')
  }
  return hash.digest('hex')
}

function buildWebUi({ root, clean = false }) {
  const digest = webUiSourceDigest(root)
  const stampPath = path.join(root, 'build', 'cache', 'web-ui.sha256')
  const indexPath = path.join(root, 'open_agent', 'app', 'static', 'index.html')
  const cachedDigest = fs.existsSync(stampPath) ? fs.readFileSync(stampPath, 'utf8').trim() : ''
  if (!clean && cachedDigest === digest && fs.existsSync(indexPath)) {
    process.stdout.write('Web UI sources unchanged; reusing the existing production build.\n')
    return
  }
  run('npm', ['--prefix', path.join(root, 'open_agent', 'app', 'web'), 'run', 'build'])
  requirePath(indexPath, 'Web UI production build')
  fs.mkdirSync(path.dirname(stampPath), { recursive: true })
  fs.writeFileSync(stampPath, `${digest}\n`, 'utf8')
}

function clearBundleArtifacts(root, platform) {
  const extensions =
    platform === 'windows' ? new Set(['.exe', '.msi']) : new Set(['.deb', '.appimage'])
  for (const directory of tauriBundleDirectories(root, platform)) {
    for (const file of walkFiles(directory)) {
      if (extensions.has(path.extname(file).toLowerCase())) fs.rmSync(file, { force: true })
    }
  }
}

function copyBundleArtifacts(root, platform, destination) {
  const bundleRoot = path.join(root, 'desktop', 'src-tauri', 'target', 'release', 'bundle')
  const extensions = platform === 'windows' ? new Set(['.exe', '.msi']) : new Set(['.deb', '.appimage'])
  const artifacts = walkFiles(bundleRoot).filter((file) =>
    extensions.has(path.extname(file).toLowerCase()),
  )
  if (!artifacts.length) throw new Error(`No ${platform} Tauri bundle artifacts found in ${bundleRoot}`)
  fs.mkdirSync(destination, { recursive: true })
  for (const artifact of artifacts) {
    fs.copyFileSync(artifact, path.join(destination, path.basename(artifact)))
  }
}

function archiveCli(platform, portableDir, archivePath) {
  if (platform === 'windows') {
    run('tar.exe', ['-a', '-c', '-f', archivePath, '-C', portableDir, '.'])
  } else {
    run('tar', ['-czf', archivePath, '-C', portableDir, '.'])
  }
}

function writeChecksums(releaseDir) {
  const checksumPath = path.join(releaseDir, 'SHA256SUMS')
  const lines = walkFiles(releaseDir)
    .filter((file) => file !== checksumPath)
    .sort()
    .map((file) => {
      const digest = crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')
      return `${digest}  ${path.relative(releaseDir, file).split(path.sep).join('/')}`
    })
  fs.writeFileSync(checksumPath, `${lines.join('\n')}\n`, 'utf8')
}

function buildFrozenTarget({ kind, platform, targetTriple, root, python, clean = false }) {
  const base = path.join(root, 'build', 'pyinstaller', platform, kind)
  const distPath =
    kind === 'backend'
      ? path.join(root, 'desktop', 'src-tauri', 'binaries')
      : path.join(base, 'dist')
  const workPath = path.join(base, 'work')
  const specPath = path.join(base, 'spec')
  fs.mkdirSync(distPath, { recursive: true })
  if (clean) {
    recreateDirectory(workPath)
    recreateDirectory(specPath)
  } else {
    fs.mkdirSync(workPath, { recursive: true })
    fs.mkdirSync(specPath, { recursive: true })
  }

  const plan = stagePlanData(
    buildPyInstallerPlan({
      kind,
      platform,
      targetTriple,
      root,
      python,
      winptyDir:
        platform === 'windows' && kind === 'backend' ? resolveWinptyDir(python) : undefined,
    }),
    path.join(base, 'data'),
    { clean },
  )
  run(python, createPyInstallerArgs(plan, { root, distPath, workPath, specPath, clean }))
  return { plan, distPath }
}

export function buildMobileRelease({
  root = DEFAULT_ROOT,
  version,
  clean = false,
  webBuilt = false,
} = {}) {
  const releaseVersion = version || syncVersion(root)
  const layout = mobileReleaseLayout(root)
  process.stdout.write('[mobile] Building Android companion APK...\n')
  if (!webBuilt) buildWebUi({ root, clean })
  run('npm', createMobileBuildArgs(root, { clean }))
  const legacyReleaseDir = path.join(root, 'dist', 'mobile')
  for (const legacyName of [
    'OpenAgentSeal-Mobile-debug.apk',
    'release-manifest.json',
    'SHA256SUMS',
  ]) {
    fs.rmSync(path.join(legacyReleaseDir, legacyName), { force: true })
  }
  recreateDirectory(layout.releaseDir)
  fs.copyFileSync(requirePath(layout.sourceApk, 'Android debug APK'), layout.outputApk)
  fs.writeFileSync(
    path.join(layout.releaseDir, 'release-manifest.json'),
    `${JSON.stringify(
      {
        version: releaseVersion,
        platform: 'android',
        buildType: 'debug',
        appId: 'com.openagentseal.mobile',
      },
      null,
      2,
    )}\n`,
    'utf8',
  )
  writeChecksums(layout.releaseDir)
  process.stdout.write(`[mobile] Android release artifact: ${layout.outputApk}\n`)
  return layout
}

function collectCli({ root, layout, platform, architecture, version, cliBuild }) {
  const portableDir = path.join(layout.cliDir, 'portable')
  fs.mkdirSync(portableDir, { recursive: true })
  if (platform === 'windows') {
    const executable = requirePath(
      path.join(cliBuild.distPath, `${cliBuild.plan.name}.exe`),
      'Windows CLI executable',
    )
    fs.copyFileSync(executable, path.join(portableDir, 'openagentseal-cli.exe'))
  } else {
    copyDirectory(path.join(cliBuild.distPath, cliBuild.plan.name), portableDir)
  }

  const suffix = platform === 'windows' ? 'zip' : 'tar.gz'
  archiveCli(
    platform,
    portableDir,
    path.join(layout.cliDir, `OpenAgentSeal-CLI-${version}-${platform}-${architecture}.${suffix}`),
  )
}

function collectDesktop({ root, layout, platform, sidecarBuild }) {
  const installersDir = path.join(layout.desktopDir, 'installers')
  copyBundleArtifacts(root, platform, installersDir)
  if (platform !== 'windows') return

  const portableDir = path.join(layout.desktopDir, 'portable')
  fs.mkdirSync(portableDir, { recursive: true })
  fs.copyFileSync(
    requirePath(
      path.join(root, 'desktop', 'src-tauri', 'target', 'release', 'open-agent-seal-desktop.exe'),
      'Tauri desktop executable',
    ),
    path.join(portableDir, 'OpenAgentSeal.exe'),
  )
  fs.copyFileSync(
    requirePath(
      path.join(sidecarBuild.distPath, `${sidecarBuild.plan.name}.exe`),
      'Desktop backend sidecar',
    ),
    path.join(portableDir, `${sidecarBuild.plan.name}.exe`),
  )
  copyDirectory(path.join(root, 'open_agent', 'skills'), path.join(portableDir, 'skills'))
  copyDirectory(path.join(root, 'open_agent', 'config'), path.join(portableDir, 'config'))
}

export function runReleaseBuild(
  requestedTarget = 'all',
  root = DEFAULT_ROOT,
  { clean = false, skipMobile = false } = {},
) {
  if (!['all', 'desktop', 'cli', 'mobile'].includes(requestedTarget)) {
    throw new Error(`Unknown build target: ${requestedTarget}`)
  }
  const version = syncVersion(root, { skipAndroid: skipMobile })
  if (requestedTarget === 'mobile') return buildMobileRelease({ root, version, clean })

  const platform = normalizePlatform()
  const architecture = normalizeArchitecture()
  const targetTriple = rustTargetTriple()
  const python = findPython(root, platform)
  if (!python) throw new Error('No Python interpreter was found for packaging')

  const layout = releaseLayout(root, platform, architecture)
  const totalSteps = requestedTarget === 'all' && !skipMobile ? 5 : 4
  if (requestedTarget === 'all') recreateDirectory(layout.releaseDir)
  else fs.mkdirSync(layout.releaseDir, { recursive: true })
  if (requestedTarget === 'all' || requestedTarget === 'desktop') {
    recreateDirectory(layout.desktopDir)
  }
  if (requestedTarget === 'all' || requestedTarget === 'cli') {
    recreateDirectory(layout.cliDir)
  }
  fs.mkdirSync(layout.desktopDir, { recursive: true })
  fs.mkdirSync(layout.cliDir, { recursive: true })

  let cliBuild
  let sidecarBuild
  if (requestedTarget === 'all' || requestedTarget === 'cli') {
    process.stdout.write(`[1/${totalSteps}] Building ${platform} CLI...\n`)
    cliBuild = buildFrozenTarget({ kind: 'cli', platform, targetTriple, root, python, clean })
    collectCli({ root, layout, platform, architecture, version, cliBuild })
  }
  if (requestedTarget === 'all' || requestedTarget === 'desktop') {
    process.stdout.write(`[2/${totalSteps}] Building Web UI and ${platform} desktop backend...\n`)
    buildWebUi({ root, clean })
    sidecarBuild = buildFrozenTarget({
      kind: 'backend',
      platform,
      targetTriple,
      root,
      python,
      clean,
    })
    const tauriBuildOptions = {
      env: { ...process.env, APPIMAGE_EXTRACT_AND_RUN: '1' },
    }
    if (clean) {
      fs.rmSync(path.join(root, 'desktop', 'src-tauri', 'target', 'release'), {
        recursive: true,
        force: true,
      })
    }
    clearBundleArtifacts(root, platform)
    process.stdout.write(`[3/${totalSteps}] Compiling Web UI and Tauri app once...\n`)
    run('npm', createTauriCompileArgs(root), tauriBuildOptions)
    for (const { bundle, attempts } of desktopBundlePlan(platform)) {
      runWithRetry(
        () => run('npm', createTauriBundleArgs(platform, root, bundle), tauriBuildOptions),
        {
          attempts,
          onRetry: (attempt, attempts, error) => {
            process.stderr.write(
              `${bundle} build attempt ${attempt}/${attempts} failed: ${error.message}\n` +
                `Retrying ${bundle} build in ${attempt * 5}s...\n`,
            )
          },
        },
      )
    }
    collectDesktop({ root, layout, platform, sidecarBuild })
  }

  if (requestedTarget === 'all' && !skipMobile) {
    process.stdout.write(`[4/${totalSteps}] Packaging Android companion app...\n`)
    buildMobileRelease({ root, version, clean, webBuilt: true })
  }

  fs.writeFileSync(
    path.join(layout.releaseDir, 'release-manifest.json'),
    `${JSON.stringify({ version, platform, architecture, targetTriple }, null, 2)}\n`,
    'utf8',
  )
  writeChecksums(layout.releaseDir)
  process.stdout.write(`[${totalSteps}/${totalSteps}] Release artifacts: ${layout.releaseDir}\n`)
  return layout
}

function main() {
  const args = process.argv.slice(2)
  const requestedTarget = args.find((arg) => !arg.startsWith('--')) || 'all'
  runReleaseBuild(requestedTarget, DEFAULT_ROOT, {
    clean: args.includes('--clean'),
    skipMobile: args.includes('--skip-mobile'),
  })
}

const invokedPath = process.argv[1] ? pathToFileURL(path.resolve(process.argv[1])).href : ''
if (invokedPath === import.meta.url) {
  main()
}
