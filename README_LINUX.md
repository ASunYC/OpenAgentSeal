# OpenAgentSeal Linux Web-only

Linux 第一版不打 Tauri 壳，只运行 Python/FastAPI 后端并托管 Vue Web UI。

## 支持范围

- 支持：聊天、资料库、智能体、模型、技能、MCP、插件、上下文压缩、运行事件。
- Linux Web-only 下隐藏：内置浏览器面板、沙盒终端面板、打开文件所在位置。
- 数据目录仍然是 `~/.open-agent/data`。
- 工作目录默认是仓库内 `workspace/`，可通过 `OPEN_AGENT_WORKSPACE` 修改。

## 环境要求

- Python 3.10+
- Node.js 18+
- npm

Ubuntu/Debian 示例：

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nodejs npm
```

如果系统仓库里的 Node.js 版本太旧，请使用 NodeSource、nvm 或其他方式安装 Node.js 18+。

## 安装

```bash
git clone https://github.com/ASunYC/OpenAgentSeal.git
cd OpenAgentSeal
bash scripts/linux/install.sh
```

脚本会创建 `.venv`、安装 Python 包、安装前端依赖并构建静态 Web UI。

如果你在 WSL 中运行同一个 Windows 工作区，并且仓库里已经存在 Windows 版 `.venv`，脚本会自动改用 `.venv-linux`。

## 启动 Web UI

```bash
bash scripts/linux/start-web.sh
```

默认监听：

```text
0.0.0.0:9998
```

本机访问：

```text
http://127.0.0.1:9998
```

局域网访问：

```text
http://<你的 Linux 机器 IP>:9998
```

## 常用环境变量

```bash
OPEN_AGENT_HOST=0.0.0.0
OPEN_AGENT_PORT=9998
OPEN_AGENT_WORKSPACE=/data/openagentseal/workspace
PYTHON_BIN=python3
OPEN_AGENT_VENV=/path/to/.venv
```

示例：

```bash
OPEN_AGENT_PORT=18080 OPEN_AGENT_WORKSPACE=/data/agent-workspace bash scripts/linux/start-web.sh
```

## systemd 示例

将下面内容保存为 `/etc/systemd/system/openagentseal.service`，按需替换路径和用户：

```ini
[Unit]
Description=OpenAgentSeal Web-only
After=network.target

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/opt/OpenAgentSeal
Environment=OPEN_AGENT_HOST=0.0.0.0
Environment=OPEN_AGENT_PORT=9998
Environment=OPEN_AGENT_WORKSPACE=/opt/OpenAgentSeal/workspace
ExecStart=/bin/bash /opt/OpenAgentSeal/scripts/linux/start-web.sh
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now openagentseal
sudo systemctl status openagentseal
```

## 资料库说明

Linux Web-only 运行在服务端浏览器模式下，资料库里的本机路径应当是 Linux 服务器上的路径。推荐把资料放到 `OPEN_AGENT_WORKSPACE` 下，或用资料库里的“添加服务器路径”输入绝对路径。

浏览器上传文件仍可作为聊天附件使用；如果要让智能体长期读取某个目录，优先把目录挂到服务器文件系统里再加入资料库。

## 与桌面版差异

Windows/Tauri 桌面版可以使用系统 WebView、内置浏览器面板、沙盒终端和资源管理器打开位置。Linux Web-only 第一版为了稳定，先隐藏这些桌面专属能力。
