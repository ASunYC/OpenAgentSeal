# Technical Design

## Architecture

- 新增纯展示与事件派发的 `DesktopSidebar.vue`，作为 `.app-container` 的直接子元素。
- `DesktopApp.vue` 继续作为编排层，侧栏事件直接连接现有 `startNewChat`、`openRuntimePanel`、`openBrowserHome`、`openSandboxPanel`、`openSettings` 和工作区入口。
- 通过 `DesktopSidebar` 的工作区插槽将现有 `WorkspaceManager` 及其附属输入表单移入左栏；其事件仍由 `DesktopApp.vue` 处理。
- 删除聊天区中的来源工作区列和对应拖动分隔条；右侧工具面板只改变外壳布局、间距、边框、圆角和响应式行为。

## Layout Contract

- 宽屏：固定左栏（下半部分可展开工作区）+ 主聊天 + 按需显示的右侧工具面板。
- 左右工具外壳贴边，`margin: 0`、`border-radius: 0`、`box-shadow: none`，用分隔线表达层级。
- 窄屏：常态侧栏收为图标栏；展开工作区时在同一左栏内覆盖展开，不额外挤压主聊天；右侧工具面板采用可滚动策略。
- 全屏工具面板只覆盖主聊天区域，固定左栏仍可见。

## State and Data Flow

- 侧栏不持有 store，不引入第二状态源。
- 活跃面板、功能可用性、当前工作目录和加载状态均由 `DesktopApp.vue` 通过 props 传入。
- 侧栏只 emit 用户意图；所有业务副作用仍由现有函数执行。

## Compatibility

- 不修改后端 API、Tauri command、Pinia store 或持久化格式。
- 保留当前高 DPI 修复，并把响应式断言更新为新的侧栏/贴边面板契约。

## Risks and Rollback

- 删除旧来源面板宽度和拖动状态，右栏宽度只以聊天容器实际宽度约束。
- 旧静态响应式测试锁定纵向堆叠规则，必须先改测试再改实现。
- 回滚点为新侧栏组件、根模板接线和独立布局 CSS，不触碰业务数据层。
