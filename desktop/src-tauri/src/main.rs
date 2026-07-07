#![cfg_attr(target_os = "windows", windows_subsystem = "windows")]

use std::{
    env,
    fs::{File, OpenOptions},
    io::{Read, Write},
    net::{SocketAddr, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Mutex,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use tauri::{
    image::Image,
    menu::{MenuBuilder, MenuItemBuilder},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Emitter, Manager,
};

const BACKEND_BIND_HOST: &str = "0.0.0.0";
const BACKEND_CONNECT_HOST: &str = "127.0.0.1";
const BACKEND_PORT: &str = "9998";
const SIDECAR_NAME: &str = "open-agent-backend-x86_64-pc-windows-msvc.exe";
const ABOUT_URL: &str = "https://github.com/ASunYC";

struct BackendProcess {
    child: Mutex<Option<Child>>,
    command: BackendCommand,
}

impl BackendProcess {
    fn ensure_started(&self) -> Result<(), String> {
        if backend_healthy() {
            return Ok(());
        }

        let mut child = self
            .child
            .lock()
            .map_err(|_| "Backend process lock is poisoned".to_string())?;

        if backend_port_in_use() {
            return Err("Backend port is already owned by another process".to_string());
        }

        let mut backend = spawn_backend(&self.command)?;
        if wait_for_backend_ready() {
            *child = Some(backend);
            Ok(())
        } else {
            let _ = backend.kill();
            let _ = backend.wait();
            Err("Python backend did not become ready within 20 seconds".to_string())
        }
    }

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

        let mut backend = spawn_backend(&self.command)?;
        if wait_for_backend_ready() {
            *child = Some(backend);
            Ok(())
        } else {
            let _ = backend.kill();
            let _ = backend.wait();
            Err("Python backend did not become ready within 20 seconds".to_string())
        }
    }

    fn open_cli_terminal(&self) -> Result<(), String> {
        open_cli_terminal(&self.command)
    }
}

enum BackendCommand {
    Sidecar { path: PathBuf, workspace: PathBuf },
    Python { executable: PathBuf, root: PathBuf },
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
    format!("http://{}:{}", BACKEND_CONNECT_HOST, BACKEND_PORT)
}

#[tauri::command]
fn open_path(target: String) -> Result<(), String> {
    open_target(&target)
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

fn resolve_backend_command(app: &tauri::App) -> BackendCommand {
    let root = repo_root().unwrap_or_else(|_| PathBuf::from("."));

    #[cfg(debug_assertions)]
    {
        let use_sidecar = env::var("OPEN_AGENT_DESKTOP_USE_SIDECAR")
            .map(|value| matches!(value.as_str(), "1" | "true" | "TRUE" | "yes" | "YES"))
            .unwrap_or(false);
        if !use_sidecar {
            return BackendCommand::Python {
                executable: python_executable(&root),
                root,
            };
        }
    }

    if let Some(path) = find_sidecar(app) {
        return BackendCommand::Sidecar {
            path,
            workspace: PathBuf::from(env::var("OPEN_AGENT_DESKTOP_WORKSPACE").unwrap_or_else(
                |_| {
                    PathBuf::from(env::var("USERPROFILE").unwrap_or_else(|_| ".".to_string()))
                        .join("OpenAgentSeal")
                        .to_string_lossy()
                        .into_owned()
                },
            )),
        };
    }

    BackendCommand::Python {
        executable: python_executable(&root),
        root,
    }
}

fn find_sidecar(app: &tauri::App) -> Option<PathBuf> {
    let mut candidates = Vec::new();

    if let Ok(current_exe) = env::current_exe() {
        if let Some(parent) = current_exe.parent() {
            candidates.push(parent.join(SIDECAR_NAME));
            candidates.push(parent.join("binaries").join(SIDECAR_NAME));
        }
    }

    if let Ok(resource_dir) = app.path().resource_dir() {
        candidates.push(resource_dir.join(SIDECAR_NAME));
        candidates.push(resource_dir.join("binaries").join(SIDECAR_NAME));
        candidates.push(resource_dir.join("resources").join(SIDECAR_NAME));
    }

    if let Ok(root) = repo_root() {
        candidates.push(
            root.join("desktop")
                .join("src-tauri")
                .join("binaries")
                .join(SIDECAR_NAME),
        );
    }

    candidates.into_iter().find(|path| path.exists())
}

fn spawn_backend(command_config: &BackendCommand) -> Result<Child, String> {
    let stdout = open_backend_log()?;
    let stderr = stdout
        .try_clone()
        .map_err(|error| format!("Failed to clone backend log handle: {error}"))?;

    let mut command = match command_config {
        BackendCommand::Sidecar { path, workspace } => {
            let mut command = Command::new(path);
            if let Some(parent) = path.parent() {
                command.current_dir(parent);
            }
            command
                .env("OPEN_AGENT_DESKTOP_WORKSPACE", workspace)
                .env("OPEN_AGENT_DESKTOP_HOST", BACKEND_BIND_HOST)
                .env("OPEN_AGENT_DESKTOP_PORT", BACKEND_PORT);
            command
        }
        BackendCommand::Python { executable, root } => {
            let mut command = Command::new(executable);
            command
                .current_dir(root)
                .arg("-m")
                .arg("open_agent")
                .arg("--web-only")
                .arg("--no-browser")
                .arg("--host")
                .arg(BACKEND_BIND_HOST)
                .arg("--port")
                .arg(BACKEND_PORT)
                .arg("--workspace")
                .arg(root);
            command
        }
    };

    command
        .env("OPEN_AGENT_DESKTOP", "1")
        .env("PYTHONUTF8", "1")
        .env("PYTHONIOENCODING", "utf-8")
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
    let base_dir = env::var("LOCALAPPDATA")
        .or_else(|_| env::var("APPDATA"))
        .or_else(|_| env::var("USERPROFILE"))
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."));
    let log_dir = base_dir.join("OpenAgentSeal");
    std::fs::create_dir_all(&log_dir)
        .map_err(|error| format!("Failed to create backend log directory: {error}"))?;
    Ok(log_dir.join("desktop-backend.log"))
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
        BACKEND_CONNECT_HOST, BACKEND_PORT
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
    let address: SocketAddr = format!("{}:{}", BACKEND_CONNECT_HOST, BACKEND_PORT)
        .parse()
        .map_err(|error| format!("Invalid backend address: {error}"))?;

    TcpStream::connect_timeout(&address, Duration::from_millis(300))
        .map_err(|error| format!("Backend port is not accepting connections: {error}"))
}

fn show_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        match backend_url().parse() {
            Ok(url) => {
                if let Err(error) = window.navigate(url) {
                    append_desktop_log(&format!("Failed to navigate main window: {error}"));
                }
            }
            Err(error) => append_desktop_log(&format!("Invalid backend URL: {error}")),
        }
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn finish_startup(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("splash") {
        let _ = window.close();
    }
    show_main_window(app);
}

fn open_backend_in_browser() -> Result<(), String> {
    open_target(&backend_url())
}

fn is_allowed_main_navigation(url: &tauri::Url) -> bool {
    match url.scheme() {
        "about" | "asset" | "data" | "file" | "tauri" => true,
        "http" | "https" => {
            let host = url.host_str().unwrap_or_default();
            matches!(host, "127.0.0.1" | "localhost" | "tauri.localhost")
        }
        _ => false,
    }
}

fn open_backend_log_file() -> Result<(), String> {
    let path = backend_log_path()?;
    if !path.exists() {
        let _ =
            File::create(&path).map_err(|error| format!("Failed to create log file: {error}"))?;
    }
    open_target(path.to_string_lossy().as_ref())
}

fn current_user_label() -> String {
    let username = env::var("USERNAME")
        .or_else(|_| env::var("USER"))
        .unwrap_or_else(|_| "Unknown".to_string());
    format!("User  {username}")
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

#[cfg(any(target_os = "macos", all(unix, not(target_os = "macos"))))]
fn quote_shell_arg(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\\''"))
}

#[cfg(target_os = "windows")]
fn quote_cmd_script_arg(value: &str) -> Result<String, String> {
    if value.contains(['\0', '\r', '\n']) {
        return Err("CLI command contains a control character".to_string());
    }
    if value.contains('"') {
        return Err("CLI command contains an unsupported double quote".to_string());
    }
    if value.contains('%') {
        return Err("CLI command contains an unsupported percent sign".to_string());
    }

    Ok(format!("\"{value}\""))
}

#[cfg(target_os = "windows")]
fn cmd_script_set_value(value: &str) -> Result<String, String> {
    if value.contains(['\0', '\r', '\n', '"', '%']) {
        return Err("CLI command contains a value that cannot be used in a cmd script".to_string());
    }
    Ok(value.to_string())
}

#[cfg(target_os = "windows")]
fn write_cli_cmd_script(program: &Path, args: &[String], cwd: &Path) -> Result<PathBuf, String> {
    let mut command_line = vec![quote_cmd_script_arg(&program.to_string_lossy())?];
    command_line.extend(
        args.iter()
            .map(|arg| quote_cmd_script_arg(arg))
            .collect::<Result<Vec<_>, _>>()?,
    );

    let cwd = quote_cmd_script_arg(&cwd.to_string_lossy())?;
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| format!("Failed to generate CLI script name: {error}"))?
        .as_millis();
    let script_path = env::temp_dir().join(format!(
        "open-agent-seal-cli-{}-{timestamp}.cmd",
        std::process::id()
    ));
    let runtime_temp = cmd_script_set_value(
        &env::temp_dir()
            .join(format!(
                "open-agent-seal-cli-runtime-{}-{timestamp}",
                std::process::id()
            ))
            .to_string_lossy(),
    )?;

    let script = format!(
        "@echo off\r\n\
         setlocal DisableDelayedExpansion\r\n\
         chcp 65001 >NUL\r\n\
         set \"PYTHONUTF8=1\"\r\n\
         set \"PYTHONIOENCODING=utf-8\"\r\n\
         set \"TERM=\"\r\n\
         set \"OPEN_AGENT_CLI_TEMP={runtime_temp}\"\r\n\
         if not exist \"%OPEN_AGENT_CLI_TEMP%\" mkdir \"%OPEN_AGENT_CLI_TEMP%\"\r\n\
         set \"TEMP=%OPEN_AGENT_CLI_TEMP%\"\r\n\
         set \"TMP=%OPEN_AGENT_CLI_TEMP%\"\r\n\
         cd /d {cwd}\r\n\
         if errorlevel 1 (\r\n\
         \techo Failed to change directory to {cwd}\r\n\
         \tgoto :end\r\n\
         )\r\n\
         {}\r\n\
         set \"OPEN_AGENT_CLI_EXIT=%ERRORLEVEL%\"\r\n\
         echo.\r\n\
         echo OpenAgentSeal CLI exited with code %OPEN_AGENT_CLI_EXIT%.\r\n\
         :end\r\n\
         endlocal\r\n",
        command_line.join(" ")
    );

    std::fs::write(&script_path, script)
        .map_err(|error| format!("Failed to write CLI launch script: {error}"))?;
    append_desktop_log(&format!(
        "Wrote CLI script: {}",
        script_path.to_string_lossy()
    ));
    Ok(script_path)
}

#[cfg(target_os = "windows")]
fn write_cli_launcher_script(cli_script_path: &Path) -> Result<PathBuf, String> {
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| format!("Failed to generate CLI launcher name: {error}"))?
        .as_millis();
    let launcher_path = env::temp_dir().join(format!(
        "open-agent-seal-cli-launcher-{}-{timestamp}.cmd",
        std::process::id()
    ));
    let cli_script = quote_cmd_script_arg(&cli_script_path.to_string_lossy())?;
    let launcher = format!(
        "@echo off\r\n\
         start \"\" cmd.exe /D /V:OFF /K {cli_script}\r\n"
    );

    std::fs::write(&launcher_path, launcher)
        .map_err(|error| format!("Failed to write CLI launcher script: {error}"))?;
    append_desktop_log(&format!(
        "Wrote CLI launcher script: {}",
        launcher_path.to_string_lossy()
    ));
    Ok(launcher_path)
}

fn source_python_cli_parts(workspace: &Path) -> Option<(PathBuf, Vec<String>, PathBuf)> {
    let root = repo_root().ok()?;
    if !root.join("open_agent").join("__main__.py").exists() {
        return None;
    }

    let executable = python_executable(&root);
    if env::var("OPEN_AGENT_DESKTOP_PYTHON").is_err() && !executable.exists() {
        return None;
    }

    Some((
        executable,
        vec![
            "-m".to_string(),
            "open_agent".to_string(),
            "--cli-only".to_string(),
            "--config".to_string(),
            "--workspace".to_string(),
            workspace.to_string_lossy().into_owned(),
        ],
        root,
    ))
}

fn cli_command_parts(command_config: &BackendCommand) -> (PathBuf, Vec<String>, PathBuf) {
    match command_config {
        BackendCommand::Sidecar { path, workspace } => {
            if let Some(command_parts) = source_python_cli_parts(workspace) {
                return command_parts;
            }

            let cwd = path
                .parent()
                .map(Path::to_path_buf)
                .unwrap_or_else(|| PathBuf::from("."));
            (
                path.clone(),
                vec![
                    "--cli-only".to_string(),
                    "--config".to_string(),
                    "--workspace".to_string(),
                    workspace.to_string_lossy().into_owned(),
                ],
                cwd,
            )
        }
        BackendCommand::Python { executable, root } => (
            executable.clone(),
            vec![
                "-m".to_string(),
                "open_agent".to_string(),
                "--cli-only".to_string(),
                "--config".to_string(),
                "--workspace".to_string(),
                root.to_string_lossy().into_owned(),
            ],
            root.clone(),
        ),
    }
}

fn open_cli_terminal(command_config: &BackendCommand) -> Result<(), String> {
    let (program, args, cwd) = cli_command_parts(command_config);

    #[cfg(target_os = "windows")]
    {
        let script_path = write_cli_cmd_script(&program, &args, &cwd)?;
        let launcher_path = write_cli_launcher_script(&script_path)?;
        append_desktop_log(&format!(
            "Opening CLI terminal via launcher: {}",
            launcher_path.to_string_lossy()
        ));

        let mut cmd = Command::new("cmd");
        cmd.arg("/D")
            .arg("/C")
            .arg(&launcher_path)
            .current_dir(&cwd)
            .env("PYTHONUTF8", "1")
            .env("PYTHONIOENCODING", "utf-8")
            .env_remove("TERM");

        cmd.spawn()
            .map(|_| {
                append_desktop_log("CLI launcher process spawned");
            })
            .map_err(|error| format!("Failed to open CLI terminal: {error}"))
    }

    #[cfg(target_os = "macos")]
    {
        let program = program.to_string_lossy().into_owned();
        let cwd = cwd.to_string_lossy().into_owned();
        let mut command_line = vec![quote_shell_arg(&program)];
        command_line.extend(args.iter().map(|arg| quote_shell_arg(arg)));
        let script = format!(
            "tell application \"Terminal\" to do script \"cd {} && {}\"",
            quote_shell_arg(&cwd),
            command_line.join(" ")
        );

        return Command::new("osascript")
            .arg("-e")
            .arg(script)
            .spawn()
            .map(|_| ())
            .map_err(|error| format!("Failed to open CLI terminal: {error}"));
    }

    #[cfg(all(unix, not(target_os = "macos")))]
    {
        let mut terminal_args = vec!["--".to_string(), program.to_string_lossy().into_owned()];
        terminal_args.extend(args);

        for terminal in ["gnome-terminal", "konsole", "xterm"] {
            let mut command = Command::new(terminal);
            if terminal == "xterm" || terminal == "konsole" {
                command.arg("-e");
                command.arg(&terminal_args[1]);
                command.args(&terminal_args[2..]);
            } else {
                command.args(&terminal_args);
            }
            command.current_dir(&cwd);
            if command.spawn().is_ok() {
                return Ok(());
            }
        }

        Err("No supported terminal emulator found for CLI launch".to_string())
    }
}

fn fallback_tray_icon() -> Image<'static> {
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

fn app_tray_icon() -> Image<'static> {
    Image::from_bytes(include_bytes!("../../../icon.ico")).unwrap_or_else(|error| {
        append_desktop_log(&format!("Failed to load icon.ico for tray icon: {error}"));
        fallback_tray_icon()
    })
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(
            tauri::plugin::Builder::<tauri::Wry>::new("navigation-guard")
                .on_navigation(|webview, url| {
                    if webview.label() == "main" && !is_allowed_main_navigation(url) {
                        let target = url.as_str().to_string();
                        let _ = webview.emit("external-navigation-requested", target.clone());
                        append_desktop_log(&format!(
                            "Blocked external navigation in main window: {target}"
                        ));
                        return false;
                    }

                    true
                })
                .build(),
        )
        .setup(|app| {
            let backend_command = resolve_backend_command(app);
            app.manage(BackendProcess {
                child: Mutex::new(None),
                command: backend_command,
            });

            let app_handle = app.handle().clone();
            std::thread::spawn(move || {
                let startup_result = {
                    let state = app_handle.state::<BackendProcess>();
                    state.ensure_started()
                };

                if let Err(error) = startup_result {
                    append_desktop_log(&format!("Failed to initialize backend: {error}"));
                }

                finish_startup(&app_handle);
            });

            let frontend_header = MenuItemBuilder::new("Frontend").enabled(false).build(app)?;
            let open = MenuItemBuilder::with_id("open", "Open Window").build(app)?;
            let browser = MenuItemBuilder::with_id("browser", "Open in Browser").build(app)?;

            let backend_header = MenuItemBuilder::new("Backend").enabled(false).build(app)?;
            let cli = MenuItemBuilder::with_id("cli", "Open CLI").build(app)?;
            let restart = MenuItemBuilder::with_id("restart", "Restart Backend").build(app)?;
            let logs = MenuItemBuilder::with_id("logs", "Open Backend Log").build(app)?;

            let account_header = MenuItemBuilder::new("Account").enabled(false).build(app)?;
            let user = MenuItemBuilder::new(current_user_label())
                .enabled(false)
                .build(app)?;

            let info_header = MenuItemBuilder::new("Info").enabled(false).build(app)?;
            let version = MenuItemBuilder::new(format!("Version  v{}", env!("CARGO_PKG_VERSION")))
                .enabled(false)
                .build(app)?;
            let about = MenuItemBuilder::with_id("about", "About Us").build(app)?;

            let quit = MenuItemBuilder::with_id("quit", "Quit").build(app)?;
            let menu = MenuBuilder::new(app)
                .item(&frontend_header)
                .items(&[&open, &browser])
                .separator()
                .item(&backend_header)
                .items(&[&cli, &restart, &logs])
                .separator()
                .item(&account_header)
                .item(&user)
                .separator()
                .item(&info_header)
                .items(&[&version, &about])
                .separator()
                .item(&quit)
                .build()?;

            TrayIconBuilder::new()
                .icon(app_tray_icon())
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
                    "cli" => {
                        append_desktop_log("Open CLI requested");
                        let state = app.state::<BackendProcess>();
                        if let Err(error) = state.open_cli_terminal() {
                            append_desktop_log(&format!("Failed to open CLI terminal: {error}"));
                        }
                    }
                    "logs" => {
                        if let Err(error) = open_backend_log_file() {
                            append_desktop_log(&format!("Failed to open backend log: {error}"));
                        }
                    }
                    "about" => {
                        if let Err(error) = open_target(ABOUT_URL) {
                            append_desktop_log(&format!("Failed to open About Us URL: {error}"));
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
            if window.label() == "main" {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .invoke_handler(tauri::generate_handler![backend_url, open_path])
        .run(tauri::generate_context!())
        .expect("error while running OpenAgentSeal desktop shell");
}
