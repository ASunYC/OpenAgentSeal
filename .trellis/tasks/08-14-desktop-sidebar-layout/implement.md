# Implementation Plan

1. 先扩展响应式布局契约测试，覆盖固定侧栏、贴边面板、窄屏收起和高 DPI 视口约束，并确认测试失败。
2. 新增 `DesktopSidebar.vue`，实现左上品牌/快捷入口、收起状态和左下内嵌工作区容器，仅通过 props/emits/slot 通信。
3. 在 `DesktopApp.vue` 根布局接入侧栏，将事件连接到现有处理函数，并把 `WorkspaceManager` 及附属表单移入侧栏工作区插槽。
4. 删除聊天区独立来源工作区列及分隔条；将右侧工具面板改为贴边直角外壳，调整宽度约束和窄屏策略。
5. 运行布局契约测试、Vue 类型检查、生产构建和 `git diff --check`。
6. 启动桌面客户端，在 200% DPI 环境核对左上导航、工作目录入口、沙盒和左右面板外观。

## Validation Commands

- `npm.cmd run test:desktop-layout`
- `npm.cmd run build:check`
- `git diff --check`

## Risky Files

- `open_agent/app/web/src/DesktopApp.vue`
- `open_agent/app/web/src/components/DesktopSidebar.vue`
- `open_agent/app/web/scripts/test-desktop-responsive-layout.mjs`
