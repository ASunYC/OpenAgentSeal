# OpenAgentSeal Linux x64

OpenAgentSeal 为 Linux x64 提供 Tauri 桌面应用和独立 CLI。正式 Linux 产物在固定版本的 Ubuntu 22.04 Docker 环境中构建。

## 在 Windows 上通过 Docker 构建

环境要求：

- Docker Desktop，使用 Linux containers
- Docker Buildx
- OpenAgentSeal 源码工作区

执行：

```powershell
cd desktop
npm run build:linux:docker
```

首次构建会在 Docker 中安装 Tauri、Rust、Node.js、Python 和 WebKitGTK 工具链，耗时会比较长；后续构建会复用 npm、Python 虚拟环境、PyInstaller、Cargo 和 Tauri 编译缓存。只要依赖清单和 Dockerfile 没有变化，修改业务源码不会重新安装依赖。

产物目录：

```text
dist/OpenAgentSeal-linux-x64/
├── desktop/installers/OpenAgentSeal_0.1.0_amd64.deb
├── desktop/installers/OpenAgentSeal_0.1.0_amd64.AppImage
├── cli/OpenAgentSeal-CLI-0.1.0-linux-x64.tar.gz
├── release-manifest.json
└── SHA256SUMS
```

## 安装桌面应用

Ubuntu 或 Debian 可以安装 DEB：

```bash
sudo apt install ./OpenAgentSeal_0.1.0_amd64.deb
```

也可以直接运行 AppImage：

```bash
chmod +x OpenAgentSeal_0.1.0_amd64.AppImage
./OpenAgentSeal_0.1.0_amd64.AppImage
```

桌面后端日志优先写入 `$XDG_STATE_HOME/OpenAgentSeal`；未设置该变量时写入 `~/.local/state/OpenAgentSeal`。

## 运行独立 CLI

```bash
mkdir OpenAgentSeal-CLI-0.1.0-linux-x64
tar -xzf OpenAgentSeal-CLI-0.1.0-linux-x64.tar.gz \
  -C OpenAgentSeal-CLI-0.1.0-linux-x64
cd OpenAgentSeal-CLI-0.1.0-linux-x64
./openagentseal-cli --version
./openagentseal-cli
```

CLI 压缩包自带 Python 运行时和应用依赖，目标机器不需要另外安装 Python。

## 从源码启动 Web-only 模式

服务端仍可使用源码版 Linux Web 模式：

```bash
bash scripts/linux/install.sh
bash scripts/linux/start-web.sh
```

默认监听 `0.0.0.0:9998`。可以通过 `OPEN_AGENT_HOST`、`OPEN_AGENT_PORT`、`OPEN_AGENT_WORKSPACE`、`PYTHON_BIN` 和 `OPEN_AGENT_VENV` 覆盖运行参数。
