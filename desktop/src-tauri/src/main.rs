use std::{
    env,
    fs::{File, OpenOptions},
    io::{Read, Write},
    net::{SocketAddr, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Mutex,
    time::Duration,
};

use tauri::{
    image::Image,
    menu::{MenuBuilder, MenuItemBuilder},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager,
};

const BACKEND_HOST: &str = "127.0.0.1";
const BACKEND_PORT: &str = "9998";

struct BackendProcess {
    child: Mutex<Option<Child>>,
}

impl BackendProcess {
    fn restart(&self) -> Result<(), String> {
        let mut child = self
            .child
            .lock()
            .map_err(|_| "Backend process lock is poisoned".to_string())?;

        if let Some(mut process) = child.take() {
            let _ = process.kill();
            let _ = process.wait();
        } else if backend_port_in_use() {
            return Err("Backend port is already owned by another process".to_string());
        }

        let mut backend = spawn_backend()?;
        if wait_for_backend_ready() {
            *child = Some(backend);
            Ok(())
        } else {
            let _ = backend.kill();
            let _ = backend.wait();
            Err("Python backend did not become ready within 20 seconds".to_string())
        }
    }
}

impl Drop for BackendProcess {
    fn drop(&mut self) {
        if let Ok(mut child) = self.child.lock() {
            if let Some(mut process) = child.take() {
                let _ = process.kill();
                let _ = process.wait();
            }
        }
    }
}

#[tauri::command]
fn backend_url() -> String {
    format!("http://{}:{}", BACKEND_HOST, BACKEND_PORT)
}

fn repo_root() -> Result<PathBuf, String> {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    manifest_dir
        .parent()
        .and_then(Path::parent)
        .map(Path::to_path_buf)
        .ok_or_else(|| "Failed to resolve repository root".to_string())
}

fn python_executable(root: &Path) -> PathBuf {
    if let Ok(executable) = env::var("OPEN_AGENT_DESKTOP_PYTHON") {
        return PathBuf::from(executable);
    }

    let venv_python = if cfg!(windows) {
        root.join(".venv").join("Scripts").join("python.exe")
    } else {
        root.join(".venv").join("bin").join("python")
    };

    if venv_python.exists() {
        venv_python
    } else {
        PathBuf::from("python")
    }
}

fn spawn_backend() -> Result<Child, String> {
    let root = repo_root()?;
    let python = python_executable(&root);
    let stdout = open_backend_log()?;
    let stderr = stdout
        .try_clone()
        .map_err(|error| format!("Failed to clone backend log handle: {error}"))?;

    let mut command = Command::new(python);
    command
        .current_dir(&root)
        .env("OPEN_AGENT_DESKTOP", "1")
        .env("PYTHONUTF8", "1")
        .env("PYTHONIOENCODING", "utf-8")
        .arg("-m")
        .arg("open_agent")
        .arg("--web-only")
        .arg("--no-browser")
        .arg("--host")
        .arg(BACKEND_HOST)
        .arg("--port")
        .arg(BACKEND_PORT)
        .arg("--workspace")
        .arg(&root)
        .stdin(Stdio::null())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr));

    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }

    command
        .spawn()
        .map_err(|error| format!("Failed to start Python backend: {error}"))
}

fn backend_log_path() -> Result<PathBuf, String> {
    Ok(repo_root()?.join("desktop-backend.log"))
}

fn open_backend_log() -> Result<File, String> {
    OpenOptions::new()
        .create(true)
        .append(true)
        .open(backend_log_path()?)
        .map_err(|error| format!("Failed to open backend log: {error}"))
}

fn append_desktop_log(message: &str) {
    if let Ok(mut log) = open_backend_log() {
        let _ = writeln!(log, "[desktop] {message}");
    }
}

fn backend_healthy() -> bool {
    let Ok(mut stream) = connect_backend() else {
        return false;
    };

    let request = format!(
        "GET /api/health HTTP/1.1\r\nHost: {}:{}\r\nConnection: close\r\n\r\n",
        BACKEND_HOST, BACKEND_PORT
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }

    let mut response = String::new();
    stream.read_to_string(&mut response).is_ok() && response.contains("200 OK")
}

fn backend_port_in_use() -> bool {
    connect_backend().is_ok()
}

fn wait_for_backend_ready() -> bool {
    for _ in 0..40 {
        if backend_healthy() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(500));
    }

    false
}

fn connect_backend() -> Result<TcpStream, String> {
    let address: SocketAddr = format!("{}:{}", BACKEND_HOST, BACKEND_PORT)
        .parse()
        .map_err(|error| format!("Invalid backend address: {error}"))?;

    TcpStream::connect_timeout(&address, Duration::from_millis(300))
        .map_err(|error| format!("Backend port is not accepting connections: {error}"))
}

fn show_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn open_backend_in_browser() -> Result<(), String> {
    open_target(&backend_url())
}

fn open_backend_log_file() -> Result<(), String> {
    let path = backend_log_path()?;
    if !path.exists() {
        let _ = File::create(&path).map_err(|error| format!("Failed to create log file: {error}"))?;
    }
    open_target(path.to_string_lossy().as_ref())
}

fn open_target(target: &str) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    let mut command = {
        let mut command = Command::new("rundll32");
        command.arg("url.dll,FileProtocolHandler").arg(target);
        command
    };

    #[cfg(target_os = "macos")]
    let mut command = {
        let mut command = Command::new("open");
        command.arg(target);
        command
    };

    #[cfg(all(unix, not(target_os = "macos")))]
    let mut command = {
        let mut command = Command::new("xdg-open");
        command.arg(target);
        command
    };

    command
        .spawn()
        .map(|_| ())
        .map_err(|error| format!("Failed to open {target}: {error}"))
}

fn robot_tray_icon() -> Image<'static> {
    const SIZE: u32 = 32;
    let mut rgba = vec![0; (SIZE * SIZE * 4) as usize];

    fn put(rgba: &mut [u8], x: u32, y: u32, color: [u8; 4]) {
        let offset = ((y * 32 + x) * 4) as usize;
        rgba[offset..offset + 4].copy_from_slice(&color);
    }

    fn rect(rgba: &mut [u8], x0: u32, y0: u32, x1: u32, y1: u32, color: [u8; 4]) {
        for y in y0..=y1 {
            for x in x0..=x1 {
                put(rgba, x, y, color);
            }
        }
    }

    let body = [96, 165, 250, 255];
    let edge = [191, 219, 254, 255];
    let eye = [15, 23, 42, 255];
    let smile = [30, 64, 175, 255];
    let antenna = [147, 197, 253, 255];

    rect(&mut rgba, 9, 10, 22, 11, edge);
    rect(&mut rgba, 7, 12, 24, 24, body);
    rect(&mut rgba, 8, 13, 23, 23, edge);
    rect(&mut rgba, 10, 15, 12, 17, eye);
    rect(&mut rgba, 19, 15, 21, 17, eye);
    rect(&mut rgba, 13, 21, 18, 22, smile);
    rect(&mut rgba, 15, 7, 16, 9, antenna);
    rect(&mut rgba, 14, 5, 17, 6, antenna);
    rect(&mut rgba, 4, 16, 6, 21, body);
    rect(&mut rgba, 25, 16, 27, 21, body);

    Image::new_owned(rgba, SIZE, SIZE)
}

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            let backend = if backend_healthy() {
                None
            } else if backend_port_in_use() {
                return Err(format!(
                    "{}:{} is already in use by another service",
                    BACKEND_HOST, BACKEND_PORT
                )
                .into());
            } else {
                let backend = spawn_backend()?;
                if !wait_for_backend_ready() {
                    return Err("Python backend did not become ready within 20 seconds; see desktop-backend.log".into());
                }
                Some(backend)
            };

            app.manage(BackendProcess {
                child: Mutex::new(backend),
            });

            let open = MenuItemBuilder::with_id("open", "Open Window").build(app)?;
            let browser = MenuItemBuilder::with_id("browser", "Open in Browser").build(app)?;
            let restart = MenuItemBuilder::with_id("restart", "Restart Backend").build(app)?;
            let logs = MenuItemBuilder::with_id("logs", "Open Backend Log").build(app)?;
            let quit = MenuItemBuilder::with_id("quit", "Quit").build(app)?;
            let menu = MenuBuilder::new(app)
                .items(&[&open, &browser, &restart, &logs, &quit])
                .build()?;

            TrayIconBuilder::new()
                .icon(robot_tray_icon())
                .tooltip("OpenAgentSeal")
                .menu(&menu)
                .on_menu_event(|app, event| match event.id().as_ref() {
                    "open" => show_main_window(app),
                    "browser" => {
                        if let Err(error) = open_backend_in_browser() {
                            append_desktop_log(&format!("Failed to open browser: {error}"));
                        }
                    }
                    "restart" => {
                        let state = app.state::<BackendProcess>();
                        if let Err(error) = state.restart() {
                            append_desktop_log(&format!("Failed to restart backend: {error}"));
                        }
                    }
                    "logs" => {
                        if let Err(error) = open_backend_log_file() {
                            append_desktop_log(&format!("Failed to open backend log: {error}"));
                        }
                    }
                    "quit" => app.exit(0),
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        show_main_window(&tray.app_handle());
                    }
                })
                .build(app)?;

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .invoke_handler(tauri::generate_handler![backend_url])
        .run(tauri::generate_context!())
        .expect("error while running OpenAgentSeal desktop shell");
}
