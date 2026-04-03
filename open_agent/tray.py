#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Open Agent - 系统托盘

新的托盘菜单结构：
1. Open Web - 打开浏览器
2. New Agent - 创建新的后台Agent
3. New CLI Agent - 打开新终端创建CLI Agent
4. Open Service - 打开服务窗口
5. Help - 帮助文档
6. About - 关于
7. Exit - 退出
"""

import logging
import platform
import subprocess
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

logger = logging.getLogger(__name__)

# 检查托盘依赖是否可用
try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False
    logger.warning("pystray or PIL not available, tray functionality disabled")


class TrayManager:
    """托盘管理器
    
    新架构：
    - 服务永远只有1个
    - 托盘永远只有1个
    - 所有Agent通过AgentService管理
    """
    
    _instance: Optional['TrayManager'] = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9998,
        workspace_dir: str = None,
    ):
        """初始化托盘管理器
        
        Args:
            host: Web服务器主机
            port: Web服务器端口
            workspace_dir: 工作目录
        """
        if self._initialized:
            return
        
        self.host = host
        self.port = port
        self.workspace_dir = Path(workspace_dir) if workspace_dir else Path.cwd()
        self.web_url = f"http://{host}:{port}"
        
        # 托盘图标
        self._icon = None
        self._running = False
        
        # 回调函数
        self._on_exit_callback: Optional[Callable] = None
        self._on_open_web_callback: Optional[Callable] = None
        self._on_new_agent_callback: Optional[Callable] = None
        self._on_new_cli_callback: Optional[Callable] = None
        
        # 日志文件
        self.log_dir = Path.home() / ".open-agent" / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        self._initialized = True
        logger.info(f"TrayManager initialized: {self.web_url}")
    
    @classmethod
    def get_instance(cls) -> 'TrayManager':
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @classmethod
    def initialize(
        cls,
        host: str = "127.0.0.1",
        port: int = 9998,
        workspace_dir: str = None,
    ) -> 'TrayManager':
        """初始化单例"""
        instance = cls(host=host, port=port, workspace_dir=workspace_dir)
        return instance
    
    def set_callbacks(
        self,
        on_exit: Callable = None,
        on_open_web: Callable = None,
        on_new_agent: Callable = None,
        on_new_cli: Callable = None,
    ):
        """设置回调函数
        
        Args:
            on_exit: 退出回调
            on_open_web: 打开Web回调
            on_new_agent: 创建新Agent回调
            on_new_cli: 创建CLI Agent回调
        """
        self._on_exit_callback = on_exit
        self._on_open_web_callback = on_open_web
        self._on_new_agent_callback = on_new_agent
        self._on_new_cli_callback = on_new_cli
    
    def create_icon(self):
        """创建托盘图标"""
        if not TRAY_AVAILABLE:
            logger.warning("Tray not available, skipping icon creation")
            return None
        
        try:
            # 创建图标图像
            size = 64
            image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            
            # 绘制机器人头像
            margin = 8
            draw.rounded_rectangle(
                [margin, margin, size - margin, size - margin],
                radius=10,
                fill=(52, 152, 219, 255),  # 蓝色背景
                outline=(41, 128, 185, 255),
                width=2,
            )
            
            # 眼睛
            eye_y = 26
            eye_size = 6
            draw.ellipse((20, eye_y, 20 + eye_size, eye_y + eye_size), fill=(255, 255, 255, 255))
            draw.ellipse((size - 20 - eye_size, eye_y, size - 20, eye_y + eye_size), fill=(255, 255, 255, 255))
            
            # 瞳孔
            pupil_size = 3
            draw.ellipse((22, eye_y + 2, 22 + pupil_size, eye_y + 2 + pupil_size), fill=(0, 0, 0, 255))
            draw.ellipse((size - 22 - pupil_size, eye_y + 2, size - 22, eye_y + 2 + pupil_size), fill=(0, 0, 0, 255))
            
            # 微笑
            smile_y = size - 24
            draw.arc([20, smile_y - 8, size - 20, smile_y + 12], start=0, end=180, fill=(255, 255, 255, 255), width=3)
            
            # 创建菜单
            menu = pystray.Menu(
                # Open Web
                pystray.MenuItem(
                    "🌐 Open Web",
                    self._on_open_web,
                    default=True,
                ),
                pystray.Menu.SEPARATOR,
                
                # New Agent
                pystray.MenuItem(
                    "🤖 New Agent",
                    self._on_new_agent,
                ),
                
                # New CLI Agent
                pystray.MenuItem(
                    "💻 New CLI Agent",
                    self._on_new_cli,
                ),
                
                pystray.Menu.SEPARATOR,
                
                # Open Service
                pystray.MenuItem(
                    "⚙️ Open Service",
                    self._on_open_service,
                ),
                
                # Help
                pystray.MenuItem(
                    "❓ Help",
                    self._on_help,
                ),
                
                # About
                pystray.MenuItem(
                    "ℹ️ About",
                    self._on_about,
                ),
                
                pystray.Menu.SEPARATOR,
                
                # Exit
                pystray.MenuItem(
                    "🚪 Exit",
                    self._on_exit,
                ),
            )
            
            self._icon = pystray.Icon("OpenAgent", image, "Open Agent", menu)
            return self._icon
            
        except Exception as e:
            logger.error(f"Failed to create tray icon: {e}")
            return None
    
    def start(self):
        """启动托盘（在后台线程运行）"""
        if not TRAY_AVAILABLE:
            logger.warning("Tray not available, skipping start")
            return False
        
        if self._running:
            logger.warning("Tray already running")
            return True
        
        self._icon = self.create_icon()
        if not self._icon:
            return False
        
        self._running = True
        
        # 在后台线程运行托盘
        def run_tray():
            try:
                self._icon.run()
            except Exception as e:
                logger.error(f"Tray run error: {e}")
            finally:
                self._running = False
        
        self._thread = threading.Thread(target=run_tray, daemon=True)
        self._thread.start()
        
        logger.info("Tray started")
        return True
    
    def stop(self):
        """停止托盘"""
        if self._icon:
            try:
                self._icon.stop()
            except Exception as e:
                logger.error(f"Error stopping tray: {e}")
        
        self._running = False
        logger.info("Tray stopped")
    
    # ==================== 菜单回调 ====================
    
    def _on_open_web(self, icon, item):
        """打开Web界面"""
        logger.info(f"Opening Web UI: {self.web_url}")
        
        # 调用回调（如果有）
        if self._on_open_web_callback:
            try:
                self._on_open_web_callback()
            except Exception as e:
                logger.error(f"Open web callback error: {e}")
        
        # 打开浏览器
        self._open_browser(self.web_url)
    
    def _on_new_agent(self, icon, item):
        """创建新Agent"""
        logger.info("Creating new agent...")
        
        # 调用回调（如果有）
        if self._on_new_agent_callback:
            try:
                self._on_new_agent_callback()
            except Exception as e:
                logger.error(f"New agent callback error: {e}")
        
        # 通过AgentService创建Agent
        try:
            from open_agent.agent_service import get_agent_service
            service = get_agent_service()
            info = service.create_agent(
                agent_type="background",
                name=f"Agent {datetime.now().strftime('%H:%M')}",
            )
            logger.info(f"Created agent: {info.agent_id}")
            self._show_notification(f"已创建新 Agent: {info.agent_id}")
        except Exception as e:
            logger.error(f"Failed to create agent: {e}")
            self._show_notification(f"创建 Agent 失败: {e}")
    
    def _on_new_cli(self, icon, item):
        """创建新的CLI Agent"""
        logger.info("Opening new CLI terminal...")
        
        # 调用回调（如果有）
        if self._on_new_cli_callback:
            try:
                self._on_new_cli_callback()
            except Exception as e:
                logger.error(f"New CLI callback error: {e}")
        
        # 打开新终端
        self._open_cli_terminal()
    
    def _on_open_service(self, icon, item):
        """打开服务窗口"""
        logger.info("Opening service window...")
        
        # 打开Web界面的服务页面
        service_url = f"{self.web_url}/#service"
        self._open_browser(service_url)
    
    def _on_help(self, icon, item):
        """显示帮助"""
        logger.info("Showing help...")
        self._show_help_dialog()
    
    def _on_about(self, icon, item):
        """显示关于"""
        logger.info("Showing about...")
        self._show_about_dialog()
    
    def _on_exit(self, icon, item):
        """退出程序"""
        logger.info("Exit requested from tray")
        
        # 调用回调（如果有）
        if self._on_exit_callback:
            try:
                self._on_exit_callback()
            except Exception as e:
                logger.error(f"Exit callback error: {e}")
        
        # 停止托盘
        self.stop()
    
    # ==================== 辅助方法 ====================
    
    def _open_browser(self, url: str):
        """打开浏览器"""
        try:
            success = webbrowser.open(url)
            if success:
                logger.info(f"Browser opened: {url}")
                return
        except Exception as e:
            logger.warning(f"webbrowser.open failed: {e}")
        
        # 备选方法
        system = platform.system()
        try:
            if system == "Windows":
                subprocess.run(["cmd", "/c", "start", url], check=False)
            elif system == "Darwin":
                subprocess.run(["open", url], check=False)
            else:
                subprocess.run(["xdg-open", url], check=False)
            logger.info(f"Browser opened via subprocess: {url}")
        except Exception as e:
            logger.error(f"Failed to open browser: {e}")
    
    def _open_cli_terminal(self):
        """打开CLI终端"""
        system = platform.system()
        
        try:
            # 获取Python路径
            python_exe = self._get_python_exe()
            
            # 获取源码目录（PYTHONPATH）
            # 打包后源码被提取到 workspace_dir（即 OPENAGENT_DIR）
            source_dir = str(self.workspace_dir)
            
            if system == "Windows":
                # 设置 PYTHONPATH 环境变量，确保能找到 open_agent 模块
                env_setup = f'set PYTHONPATH={source_dir} && '
                cmd = f'start cmd /k "{env_setup}\\"{python_exe}\\" -m open_agent.cli --cli-only"'
                subprocess.Popen(cmd, shell=True, cwd=str(self.workspace_dir))
            elif system == "Darwin":
                # macOS: 设置 PYTHONPATH 并运行
                script = f'tell application "Terminal" to do script "cd \\"{self.workspace_dir}\\" && export PYTHONPATH=\\"{source_dir}\\" && \\"{python_exe}\\" -m open_agent.cli --cli-only"'
                subprocess.Popen(["osascript", "-e", script])
            elif system == "Linux":
                # 尝试不同的终端，设置 PYTHONPATH
                env = {'PYTHONPATH': source_dir}
                terminals = [
                    ("gnome-terminal", ["gnome-terminal", "--", python_exe, "-m", "open_agent.cli", "--cli-only"]),
                    ("xterm", ["xterm", "-e", python_exe, "-m", "open_agent.cli", "--cli-only"]),
                    ("konsole", ["konsole", "-e", python_exe, "-m", "open_agent.cli", "--cli-only"]),
                ]
                for name, args in terminals:
                    try:
                        subprocess.Popen(args, cwd=str(self.workspace_dir), env=env)
                        break
                    except FileNotFoundError:
                        continue
            
            logger.info(f"CLI terminal opened with PYTHONPATH={source_dir}")
        except Exception as e:
            logger.error(f"Failed to open CLI terminal: {e}")
    
    def _get_python_exe(self) -> str:
        """获取Python可执行文件路径"""
        import sys
        
        # 优先使用虚拟环境中的Python
        venv_dir = self.workspace_dir / ".venv"
        if venv_dir.exists():
            if platform.system() == "Windows":
                venv_python = venv_dir / "Scripts" / "python.exe"
            else:
                venv_python = venv_dir / "bin" / "python"
            
            if venv_python.exists():
                return str(venv_python)
        
        return sys.executable
    
    def _show_notification(self, message: str):
        """显示通知"""
        if self._icon:
            try:
                self._icon.notify(message)
            except Exception as e:
                logger.error(f"Failed to show notification: {e}")
    
    def _show_help_dialog(self):
        """显示帮助对话框"""
        help_text = """Open Agent - 帮助

命令行指令:
  /help        - 显示帮助
  /clear       - 清空会话
  /history     - 查看消息数量
  /stats       - 会话统计
  /switch      - 切换模型
  /exit        - 退出

托盘菜单:
  Open Web     - 打开Web界面
  New Agent    - 创建后台Agent
  New CLI Agent - 打开新CLI终端
  Open Service - 打开服务管理
  Help         - 显示帮助
  About        - 关于信息
  Exit         - 退出程序

快捷键:
  Esc          - 取消当前操作
  Ctrl+C       - 退出
  Tab          - 自动补全

更多信息请访问文档。"""
        
        self._show_message_box("Open Agent - 帮助", help_text)
    
    def _show_about_dialog(self):
        """显示关于对话框"""
        try:
            version_file = Path(__file__).parent.parent / "VERSION.md"
            version = "V0.0.0"
            date = ""
            
            if version_file.exists():
                content = version_file.read_text(encoding="utf-8")
                for line in content.split("\n"):
                    if line.startswith("## Version:"):
                        version = line.replace("## Version:", "").strip()
                    elif line.startswith("## Release Date:"):
                        date = line.replace("## Release Date:", "").strip()
        except Exception:
            version = "V0.0.0"
            date = ""
        
        about_text = f"""Open Agent

版本: {version}
发布日期: {date}

一个智能AI助手，支持:
• 多种大语言模型
• 文件操作
• 代码执行
• 网络搜索
• MCP协议扩展

© 2024 Open Agent Team"""
        
        self._show_message_box("Open Agent - 关于", about_text)
    
    def _show_message_box(self, title: str, message: str):
        """显示消息框"""
        system = platform.system()
        
        try:
            if system == "Windows":
                # Windows: 使用PowerShell
                ps_script = f'''
Add-Type -AssemblyName PresentationFramework
[System.Windows.MessageBox]::Show(@"{message}", "{title}", "OK", "Information")
'''
                subprocess.Popen(["powershell", "-Command", ps_script], shell=True)
            elif system == "Darwin":
                # macOS: 使用osascript
                script = f'display dialog "{message}" with title "{title}" buttons "OK"'
                subprocess.Popen(["osascript", "-e", script])
            elif system == "Linux":
                # Linux: 尝试zenity
                try:
                    subprocess.Popen(["zenity", "--info", f"--title={title}", f"--text={message}"])
                except FileNotFoundError:
                    logger.info(f"Message: {title} - {message}")
        except Exception as e:
            logger.error(f"Failed to show message box: {e}")
            logger.info(f"Message: {title} - {message}")


# ==================== 便捷函数 ====================

_tray_manager: Optional[TrayManager] = None


def is_tray_available() -> bool:
    """检查托盘是否可用"""
    return TRAY_AVAILABLE


def get_tray_manager() -> TrayManager:
    """获取托盘管理器实例"""
    global _tray_manager
    if _tray_manager is None:
        _tray_manager = TrayManager.get_instance()
    return _tray_manager


def init_tray(
    host: str = "127.0.0.1",
    port: int = 9998,
    workspace_dir: str = None,
) -> TrayManager:
    """初始化托盘"""
    global _tray_manager
    _tray_manager = TrayManager.initialize(
        host=host,
        port=port,
        workspace_dir=workspace_dir,
    )
    return _tray_manager


def start_tray(
    host: str = "127.0.0.1",
    port: int = 9998,
    workspace_dir: str = None,
    on_exit: Callable = None,
    on_open_web: Callable = None,
    on_new_agent: Callable = None,
    on_new_cli: Callable = None,
) -> bool:
    """启动托盘
    
    Args:
        host: Web服务器主机
        port: Web服务器端口
        workspace_dir: 工作目录
        on_exit: 退出回调
        on_open_web: 打开Web回调
        on_new_agent: 创建新Agent回调
        on_new_cli: 创建CLI Agent回调
        
    Returns:
        是否成功启动
    """
    global _tray_manager
    
    if not TRAY_AVAILABLE:
        logger.warning("Tray not available")
        return False
    
    _tray_manager = TrayManager.initialize(
        host=host,
        port=port,
        workspace_dir=workspace_dir,
    )
    
    _tray_manager.set_callbacks(
        on_exit=on_exit,
        on_open_web=on_open_web,
        on_new_agent=on_new_agent,
        on_new_cli=on_new_cli,
    )
    
    return _tray_manager.start()


def stop_tray():
    """停止托盘"""
    global _tray_manager
    if _tray_manager:
        _tray_manager.stop()


# 兼容旧接口
def init_embedded_tray(**kwargs):
    """兼容旧接口"""
    return init_tray(**kwargs)


def start_embedded_tray() -> bool:
    """兼容旧接口"""
    global _tray_manager
    if _tray_manager:
        return _tray_manager.start()
    return False


def stop_embedded_tray():
    """兼容旧接口"""
    stop_tray()


def get_embedded_tray():
    """兼容旧接口"""
    return _tray_manager


def minimize_to_tray() -> bool:
    """最小化到托盘"""
    return True


def restore_from_tray() -> bool:
    """从托盘恢复"""
    return True


def is_launcher_managed() -> bool:
    """是否由launcher管理"""
    return True