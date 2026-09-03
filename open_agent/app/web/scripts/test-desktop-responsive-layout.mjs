import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const appPath = new URL('../src/DesktopApp.vue', import.meta.url)
const sidebarPath = new URL('../src/components/DesktopSidebar.vue', import.meta.url)
const [source, sidebar] = await Promise.all([
  readFile(appPath, 'utf8'),
  readFile(sidebarPath, 'utf8'),
])

assert.match(source, /<DesktopSidebar\b/, 'DesktopApp must render the fixed desktop sidebar')
for (const binding of [
  '@new-chat="startNewChat"',
  '@open-browser="openBrowserHome"',
  '@open-runtime="openRuntimePanel"',
  '@open-sandbox="openSandboxPanel"',
  '@open-settings="openSettings"',
  '@open-workspace="toggleSourceWorkspace"',
]) {
  assert.ok(source.includes(binding), `DesktopSidebar must preserve the existing ${binding} behavior`)
}
assert.match(
  sidebar,
  /sidebar-new-chat[\s\S]*?emit\('new-chat'\)/,
  'The upper-left sidebar must expose the existing new-chat action',
)
for (const action of ['runtime', 'browser', 'sandbox', 'settings']) {
  assert.match(sidebar, new RegExp(`emit\\('open-${action}'\\)`), `Sidebar must expose ${action}`)
}
assert.match(
  sidebar,
  /sidebar-workspace[\s\S]*?<slot name="workspace"/,
  'The lower-left sidebar must directly host the existing workspace content',
)
assert.match(sidebar, /\.desktop-sidebar\s*\{\s*box-sizing:\s*border-box;/, 'Sidebar padding must not clip the bottom workspace section')
assert.match(
  sidebar,
  /\.desktop-sidebar\.workspace-open \.sidebar-brand span,[\s\S]*?display:\s*block;/,
  'Opening the workspace must keep the upper-left brand and navigation visible',
)
assert.match(
  source,
  /<template #workspace>[\s\S]*?<WorkspaceManager/,
  'DesktopApp must render WorkspaceManager inside the sidebar workspace slot',
)
assert.doesNotMatch(source, /class="source-workspace-panel"/, 'Workspace must not render as a separate chat column')
assert.doesNotMatch(source, /class="source-resizer"/, 'The removed workspace column must not leave a resizer')
assert.doesNotMatch(source, /sourceWorkspaceWidth|SOURCE_WORKSPACE_MIN_WIDTH/, 'Removed workspace column width state must not survive')

assert.match(
  source,
  /\.workspace-panel\s*\{[\s\S]*?margin:\s*0;[\s\S]*?border-radius:\s*0;[\s\S]*?box-shadow:\s*none;/,
  'The right workspace shell must be a flat edge-attached panel',
)

assert.match(
  source,
  /@media \(max-width: 980px\)[\s\S]*?\.desktop-sidebar-host\s*\{[\s\S]*?width:\s*68px;/,
  'High-DPI compact viewports must collapse the fixed sidebar before a side panel overflows',
)
assert.match(
  source,
  /@media \(max-width: 1168px\)[\s\S]*?\.desktop-sidebar-host\.workspace-open\s*\{[\s\S]*?position:\s*absolute;[\s\S]*?width:\s*340px;/,
  'Compact viewports must expand workspace within the left sidebar as an overlay instead of a new column',
)
assert.equal(945 - 68 - 420 - 320 - 8 >= 0, true, 'The 945px high-DPI viewport must fit chat and one workspace panel')
assert.match(source, /const WORKSPACE_MIN_CHAT_WIDTH = 420/, 'JavaScript width clamping must match the chat panel CSS minimum')
assert.equal(1169 - 340 - 420 - 320 - 8 >= 0, true, 'The inline workspace breakpoint must cover the first width that can fit all panels')
assert.match(
  source,
  /chatBodyRef\.value\?\.getBoundingClientRect\(\)/,
  'Workspace width clamping must use the chat body width after the fixed sidebar is applied',
)
