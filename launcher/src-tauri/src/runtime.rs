use std::collections::{hash_map::DefaultHasher, HashSet};
use std::env;
use std::ffi::OsString;
use std::fs::{self, File};
use std::hash::{Hash, Hasher};
use std::io::{Read, Write};
use std::net::{TcpStream, ToSocketAddrs};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};
#[cfg(windows)]
use std::time::{SystemTime, UNIX_EPOCH};

use serde::Serialize;

use crate::models::LauncherConfig;

#[cfg(not(windows))]
const KILL_PATH: &str = "/bin/kill";
#[cfg(not(windows))]
const LAUNCHCTL_PATH: &str = "/bin/launchctl";
#[cfg(not(windows))]
const LSOF_PATH: &str = "/usr/sbin/lsof";
const LOGIN_SHELL_PATH: &str = "/bin/zsh";
#[cfg(not(windows))]
const PS_PATH: &str = "/bin/ps";
#[cfg(windows)]
pub(crate) const CREATE_NO_WINDOW: u32 = 0x08000000;
const DEPENDENCY_MARKER_FILE: &str = ".course-navigator-deps.json";
const INSTALL_TARGET_MEDIA_TOOLS: &str = "media-tools";
const RUNTIME_TOOL_PATHS_ENV: &str = "COURSE_NAVIGATOR_RUNTIME_TOOL_PATHS";
#[cfg(windows)]
const FFMPEG_DOWNLOAD_URL: &str =
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip";
// The services themselves start in seconds; this covers slow disks and
// antivirus scans. A process that exits is reported immediately instead.
const SERVICE_START_TIMEOUT: Duration = Duration::from_secs(90);
// First-time installs download large Python wheels (torch via whisper).
const SETUP_COMMAND_TIMEOUT: Duration = Duration::from_secs(30 * 60);
const POLL_INTERVAL: Duration = Duration::from_millis(250);
const LOG_EXCERPT_LINES: usize = 8;
pub const START_CANCELLED: &str = "启动已取消";
const SERVICE_LOG: &str = "service";
#[cfg(windows)]
const TOOLS_LOG: &str = "tools";
#[cfg(windows)]
const TOOL_SCRIPT_TIMEOUT: Duration = Duration::from_secs(10 * 60);
const WEB_BUILD_INDEX: &str = "frontend/dist/index.html";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RuntimeCommand {
    pub program: String,
    pub args: Vec<String>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DependencyStatus {
    pub name: String,
    pub available: bool,
    pub purpose: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub install_target: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub install_label: Option<String>,
}

pub struct ServiceState {
    service: Mutex<Option<Child>>,
    operation: Mutex<Option<Operation>>,
    cancel_start: AtomicBool,
}

/// A start or stop that is still running on a background thread.
#[derive(Clone, Debug)]
pub struct Operation {
    pub state: &'static str,
    pub message: String,
}

pub struct OperationGuard<'a> {
    state: &'a ServiceState,
}

impl Drop for OperationGuard<'_> {
    fn drop(&mut self) {
        if let Ok(mut operation) = self.state.operation.lock() {
            *operation = None;
        }
    }
}

#[derive(Clone, Copy)]
enum StopSignal {
    Term,
    Kill,
}

impl StopSignal {
    #[cfg(not(windows))]
    fn as_arg(self) -> &'static str {
        match self {
            StopSignal::Term => "-TERM",
            StopSignal::Kill => "-KILL",
        }
    }
}

impl ServiceState {
    pub fn new() -> Self {
        Self {
            service: Mutex::new(None),
            operation: Mutex::new(None),
            cancel_start: AtomicBool::new(false),
        }
    }

    /// Claims the single start/stop slot; None while another one runs.
    pub fn begin_operation(&self, state: &'static str, message: &str) -> Option<OperationGuard<'_>> {
        let mut operation = self.operation.lock().ok()?;
        if operation.is_some() {
            return None;
        }
        *operation = Some(Operation {
            state,
            message: message.to_string(),
        });
        if state == "starting" {
            self.cancel_start.store(false, Ordering::SeqCst);
        }
        Some(OperationGuard { state: self })
    }

    pub fn current_operation(&self) -> Option<Operation> {
        self.operation.lock().ok()?.clone()
    }

    pub fn set_operation_message(&self, message: &str) {
        if let Ok(mut operation) = self.operation.lock() {
            if let Some(operation) = operation.as_mut() {
                operation.message = message.to_string();
            }
        }
    }

    /// Asks a running start to abort; returns whether a start was running.
    pub fn request_start_cancel(&self) -> bool {
        let starting = self
            .current_operation()
            .is_some_and(|operation| operation.state == "starting");
        if starting {
            self.cancel_start.store(true, Ordering::SeqCst);
            self.set_operation_message("正在取消启动...");
        }
        starting
    }

    pub fn wait_for_idle(&self, timeout: Duration) -> bool {
        let started = Instant::now();
        while self.current_operation().is_some() {
            if started.elapsed() >= timeout {
                return false;
            }
            thread::sleep(POLL_INTERVAL);
        }
        true
    }

    fn start_cancelled(&self) -> bool {
        self.cancel_start.load(Ordering::SeqCst)
    }

    /// True while the service process this launcher started has not exited.
    pub fn has_live_service(&self) -> bool {
        self.service
            .lock()
            .ok()
            .is_some_and(|mut child| child.as_mut().is_some_and(|child| matches!(child.try_wait(), Ok(None))))
    }
}

/// For destructive work (moving the Workspace, deleting cache files): a
/// service that is up but slow to answer its health check still counts.
pub fn service_may_be_running(state: Option<&ServiceState>, config: &LauncherConfig) -> bool {
    state.is_some_and(ServiceState::has_live_service) || any_configured_service_listening(config)
}

/// One local service on the web port serves both the pages and `/api`.
pub fn web_url(config: &LauncherConfig) -> String {
    format!("http://{}:{}", config.web_host, config.web_port)
}

pub fn api_url(config: &LauncherConfig) -> String {
    format!("{}/api", web_url(config))
}

pub fn configured_services_listening(config: &LauncherConfig) -> bool {
    course_api_ready(config) && course_web_ready(config)
}

pub fn any_configured_service_listening(config: &LauncherConfig) -> bool {
    endpoint_listening(&config.web_host, config.web_port)
}

pub fn resolve_available_ports(config: &LauncherConfig) -> (LauncherConfig, Vec<String>) {
    if configured_services_listening(config) {
        return (config.clone(), Vec::new());
    }

    let mut next = config.clone();
    let mut messages = Vec::new();
    if endpoint_listening(&config.web_host, config.web_port) {
        if let Some(port) = first_available_port(&config.web_host, config.web_port) {
            messages.push(format!(
                "网页端口 {} 被占用，已改用 {port}",
                config.web_port
            ));
            next.web_port = port;
        }
    }

    (next, messages)
}

fn first_available_port(host: &str, preferred: u16) -> Option<u16> {
    let start = preferred.saturating_add(1).max(1024);
    (start..=u16::MAX)
        .chain(1024..preferred)
        .find(|port| !endpoint_listening(host, *port))
}

pub fn owns_services(state: &ServiceState) -> bool {
    state
        .service
        .lock()
        .map(|service| service.is_some())
        .unwrap_or(false)
}

/// The FastAPI app also serves the built pages in `frontend/dist`, so the
/// launcher needs neither Node.js nor a separate web server.
pub fn app_command(config: &LauncherConfig) -> RuntimeCommand {
    if cfg!(windows) {
        RuntimeCommand {
            program: "uv".into(),
            // --frozen: run from the shipped uv.lock, never re-resolve it at start.
            args: vec![
                "run".into(),
                "--frozen".into(),
                "uvicorn".into(),
                "course_navigator.app:app".into(),
                "--app-dir".into(),
                "backend".into(),
                "--host".into(),
                config.web_host.clone(),
                "--port".into(),
                config.web_port.to_string(),
            ],
        }
    } else {
        let command = shell_command_with_bundled_tool_paths(&format!(
            "exec uv run --frozen uvicorn course_navigator.app:app --app-dir backend --host {} --port {}",
            shell_quote(&config.web_host),
            config.web_port
        ));
        RuntimeCommand {
            program: LOGIN_SHELL_PATH.into(),
            args: vec!["-lic".into(), command],
        }
    }
}

pub fn check_dependencies(project_root: &Path) -> Vec<DependencyStatus> {
    vec![
        DependencyStatus {
            name: "uv".into(),
            available: command_exists("uv"),
            purpose: "提供本地课程服务".into(),
            install_target: None,
            install_label: None,
        },
        DependencyStatus {
            name: "yt-dlp".into(),
            available: ytdlp_available(project_root),
            purpose: "提取在线视频信息和字幕".into(),
            install_target: None,
            install_label: None,
        },
        DependencyStatus {
            name: "ffmpeg / ffprobe".into(),
            available: media_tools_available(),
            purpose: "读取视频信息、抽取音频和处理媒体".into(),
            install_target: if cfg!(windows) {
                Some(INSTALL_TARGET_MEDIA_TOOLS.into())
            } else {
                None
            },
            install_label: if cfg!(windows) {
                Some(
                    if media_tools_available() {
                        "更新"
                    } else {
                        "准备"
                    }
                    .into(),
                )
            } else {
                None
            },
        },
    ]
}

fn ytdlp_available(project_root: &Path) -> bool {
    ytdlp_module_available(project_root)
}

fn ytdlp_module_available(project_root: &Path) -> bool {
    let mut command = service_command("uv");
    command
        .args(["run", "--no-sync", "python", "-m", "yt_dlp", "--version"])
        .current_dir(project_root)
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    command.output().is_ok_and(|output| output.status.success())
}

fn media_tools_available() -> bool {
    media_tools_are_available(command_exists)
}

fn media_tools_are_available(command_available: impl Fn(&str) -> bool) -> bool {
    command_available("ffmpeg") && command_available("ffprobe")
}

fn prepare_preferred_windows_tools(state: &ServiceState) {
    #[cfg(windows)]
    {
        let _ = prepare_latest_windows_tools(state);
    }
    #[cfg(not(windows))]
    let _ = state;
}

#[cfg(windows)]
fn prepare_latest_windows_tools(state: &ServiceState) -> Result<(), String> {
    let mut errors = Vec::new();
    if bundled_tool_program("ffmpeg").is_none() || bundled_tool_program("ffprobe").is_none() {
        if let Err(error) = download_latest_media_tools(state) {
            errors.push(format!("ffmpeg / ffprobe 更新失败: {error}"));
        }
    }
    if errors.is_empty() {
        Ok(())
    } else {
        Err(errors.join("\n"))
    }
}

#[cfg(windows)]
fn download_latest_media_tools(state: &ServiceState) -> Result<(), String> {
    let target_dir = installed_tools_root().join("ffmpeg");
    let temp_root = installed_tools_root()
        .join(".tmp")
        .join(unique_temp_name("ffmpeg"));
    let zip_path = temp_root.join("ffmpeg-release-essentials.zip");
    let extract_dir = temp_root.join("extract");
    fs::create_dir_all(&target_dir).map_err(|error| format!("无法创建媒体工具目录: {error}"))?;
    fs::create_dir_all(&extract_dir)
        .map_err(|error| format!("无法创建媒体工具临时目录: {error}"))?;

    let url = env::var("COURSE_NAVIGATOR_WINDOWS_FFMPEG_URL")
        .unwrap_or_else(|_| FFMPEG_DOWNLOAD_URL.to_string());
    let result = download_file_with_powershell(&url, &zip_path, state)
        .and_then(|()| expand_archive_with_powershell(&zip_path, &extract_dir, state))
        .and_then(|()| copy_media_tools_from_archive(&extract_dir, &target_dir, state));
    let _ = fs::remove_dir_all(&temp_root);
    result
}

#[cfg(windows)]
fn download_file_with_powershell(url: &str, target: &Path, state: &ServiceState) -> Result<(), String> {
    let script = format!(
        "$ErrorActionPreference = 'Stop'; New-Item -ItemType Directory -Force -Path (Split-Path -Parent {target}) | Out-Null; Invoke-WebRequest -UseBasicParsing -Uri {url} -OutFile {target}",
        url = powershell_quote(url),
        target = powershell_quote_path(target),
    );
    run_powershell_script(&script, "下载运行工具失败", state)
}

#[cfg(windows)]
fn expand_archive_with_powershell(zip_path: &Path, destination: &Path, state: &ServiceState) -> Result<(), String> {
    let script = format!(
        "$ErrorActionPreference = 'Stop'; Expand-Archive -LiteralPath {zip_path} -DestinationPath {destination} -Force",
        zip_path = powershell_quote_path(zip_path),
        destination = powershell_quote_path(destination),
    );
    run_powershell_script(&script, "解压运行工具失败", state)
}

#[cfg(windows)]
fn copy_media_tools_from_archive(source: &Path, target: &Path, state: &ServiceState) -> Result<(), String> {
    let script = format!(
        "$ErrorActionPreference = 'Stop'; $source = {source}; $target = {target}; $ffmpeg = Get-ChildItem -Path $source -Recurse -Filter 'ffmpeg.exe' | Select-Object -First 1; $ffprobe = Get-ChildItem -Path $source -Recurse -Filter 'ffprobe.exe' | Select-Object -First 1; if (-not $ffmpeg -or -not $ffprobe) {{ throw '下载的 ffmpeg 包缺少 ffmpeg.exe 或 ffprobe.exe' }}; New-Item -ItemType Directory -Force -Path $target | Out-Null; Copy-Item -LiteralPath $ffmpeg.FullName -Destination (Join-Path $target 'ffmpeg.exe') -Force; Copy-Item -LiteralPath $ffprobe.FullName -Destination (Join-Path $target 'ffprobe.exe') -Force",
        source = powershell_quote_path(source),
        target = powershell_quote_path(target),
    );
    run_powershell_script(&script, "安装媒体工具失败", state)
}

/// Runs a tool-install script with output in tools.log, honoring cancel and a timeout.
#[cfg(windows)]
fn run_powershell_script(script: &str, context: &str, state: &ServiceState) -> Result<(), String> {
    let log = open_fresh_log(TOOLS_LOG)?;
    let stderr = log
        .try_clone()
        .map_err(|error| format!("{context}: 无法写入日志: {error}"))?;
    // Windows PowerShell's progress bar slows Invoke-WebRequest and
    // Expand-Archive down several times over, and nobody sees it here.
    let script = format!("$ProgressPreference = 'SilentlyContinue'; {script}");
    let mut command = hidden_command("powershell");
    command
        .args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", &script])
        .stdin(Stdio::null())
        .stdout(log)
        .stderr(stderr);
    let mut child = spawn_managed(&mut command).map_err(|error| format!("{context}: {error}"))?;
    match wait_managed_child(&mut child, state, TOOL_SCRIPT_TIMEOUT, |_| {}) {
        Ok(ChildWait::Exited(status)) if status.success() => Ok(()),
        Ok(ChildWait::Exited(_)) => Err(format!("{context}: {}", log_excerpt(TOOLS_LOG))),
        Ok(ChildWait::Cancelled) => Err(START_CANCELLED.to_string()),
        Ok(ChildWait::TimedOut) => Err(format!(
            "{context}: 超过 {} 分钟仍未完成，已停止",
            TOOL_SCRIPT_TIMEOUT.as_secs() / 60
        )),
        Err(error) => Err(format!("{context}: {error}")),
    }
}

#[cfg(windows)]
fn powershell_quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "''"))
}

#[cfg(windows)]
fn powershell_quote_path(path: &Path) -> String {
    powershell_quote(&path.to_string_lossy())
}

#[cfg(windows)]
fn unique_temp_name(prefix: &str) -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or_default();
    format!("{prefix}-{nanos}")
}

/// Runs on a background thread. `progress` receives user-facing step messages.
pub fn start_project_services(
    state: &ServiceState,
    config: &LauncherConfig,
    progress: &dyn Fn(&str),
) -> Result<(), String> {
    let project_root = std::path::Path::new(&config.project_root);
    if !project_root.exists() {
        return Err(format!("项目目录不存在: {}", config.project_root));
    }

    if owns_services(state) {
        return Err("服务已经由 Launcher 启动".to_string());
    }

    if configured_services_listening(config) {
        return Ok(());
    }
    if any_configured_service_listening(config) {
        return Err("网页端口已被其他程序占用；请先停止旧服务或换端口。".to_string());
    }
    if !web_build_present(project_root) {
        return Err(format!(
            "缺少网页文件 {}。请重新安装 Course Navigator；从源码运行时先执行 npm run build。",
            project_root.join(WEB_BUILD_INDEX).display()
        ));
    }
    progress("正在检查运行依赖...");
    ensure_project_dependencies(project_root, state, progress)?;
    if state.start_cancelled() {
        return Err(START_CANCELLED.to_string());
    }

    let app = app_command(config);

    progress("正在启动本地服务...");
    let (stdout, stderr) = service_log_stdio(SERVICE_LOG);
    let mut command = service_command(&app.program);
    apply_service_env(&mut command, config);
    command
        .args(&app.args)
        .current_dir(project_root)
        .stdin(Stdio::null())
        .stdout(stdout)
        .stderr(stderr);
    let child = spawn_managed(&mut command).map_err(|error| format!("服务启动失败: {error}"))?;

    *state.service.lock().map_err(|_| "服务状态锁失效".to_string())? = Some(child);
    if let Err(error) = wait_for_services_ready(state, config, progress) {
        let _ = stop_configured_services(state, config);
        return Err(error);
    }
    Ok(())
}

fn wait_for_services_ready(
    state: &ServiceState,
    config: &LauncherConfig,
    progress: &dyn Fn(&str),
) -> Result<(), String> {
    let started = Instant::now();
    let mut last_report = 0;
    loop {
        if configured_services_listening(config) {
            return Ok(());
        }
        if state.start_cancelled() {
            return Err(START_CANCELLED.to_string());
        }
        if let Some(message) = exited_service_message(state) {
            return Err(message);
        }
        let elapsed = started.elapsed();
        if elapsed >= SERVICE_START_TIMEOUT {
            return Err(not_ready_message(config, elapsed));
        }
        let seconds = elapsed.as_secs();
        if seconds >= last_report + 5 {
            last_report = seconds;
            progress(&format!("正在等待服务就绪（已等待 {seconds} 秒）..."));
        }
        thread::sleep(POLL_INTERVAL);
    }
}

fn exited_service_message(state: &ServiceState) -> Option<String> {
    let mut child = state.service.lock().ok()?;
    let status = child.as_mut()?.try_wait().ok()??;
    Some(format!(
        "服务进程已退出（{status}）。\n{}",
        log_excerpt(SERVICE_LOG)
    ))
}

fn not_ready_message(config: &LauncherConfig, elapsed: Duration) -> String {
    let missing = match (course_api_ready(config), course_web_ready(config)) {
        (false, false) => "API 和网页都未响应",
        (false, true) => "API 未响应",
        _ => "网页未响应",
    };
    format!(
        "服务在 {} 秒内没有就绪（{missing}）。\n{}",
        elapsed.as_secs(),
        log_excerpt(SERVICE_LOG)
    )
}

pub fn logs_dir() -> PathBuf {
    crate::config::application_support_dir().join("logs")
}

fn log_path(name: &str) -> PathBuf {
    logs_dir().join(format!("{name}.log"))
}

/// Starts a fresh `<name>.log`, keeping the previous run as `<name>.previous.log`.
fn open_fresh_log(name: &str) -> Result<File, String> {
    let dir = logs_dir();
    fs::create_dir_all(&dir).map_err(|error| format!("无法创建日志目录: {error}"))?;
    let path = log_path(name);
    if path.exists() {
        let _ = fs::rename(&path, dir.join(format!("{name}.previous.log")));
    }
    File::create(&path).map_err(|error| format!("无法写入日志 {}: {error}", path.display()))
}

fn service_log_stdio(name: &str) -> (Stdio, Stdio) {
    // Logging must never prevent the service from starting.
    match open_fresh_log(name).and_then(|file| {
        let stderr = file
            .try_clone()
            .map_err(|error| format!("无法写入日志: {error}"))?;
        Ok((file, stderr))
    }) {
        Ok((stdout, stderr)) => (Stdio::from(stdout), Stdio::from(stderr)),
        Err(_) => (Stdio::null(), Stdio::null()),
    }
}

fn log_excerpt(name: &str) -> String {
    let path = log_path(name);
    let excerpt = fs::read(&path)
        .map(|bytes| last_lines(&String::from_utf8_lossy(&bytes), LOG_EXCERPT_LINES))
        .unwrap_or_default();
    if excerpt.is_empty() {
        format!("（日志为空）完整日志：{}", path.display())
    } else {
        format!("{excerpt}\n完整日志：{}", path.display())
    }
}

fn last_lines(text: &str, count: usize) -> String {
    let lines = text
        .lines()
        .map(str::trim_end)
        .filter(|line| !line.trim().is_empty())
        .collect::<Vec<_>>();
    lines[lines.len().saturating_sub(count)..].join("\n")
}

fn apply_service_env(command: &mut Command, config: &LauncherConfig) {
    command
        .env("COURSE_NAVIGATOR_API_HOST", &config.api_host)
        .env("COURSE_NAVIGATOR_API_PORT", config.api_port.to_string())
        .env("COURSE_NAVIGATOR_WEB_HOST", &config.web_host)
        .env("COURSE_NAVIGATOR_WEB_PORT", config.web_port.to_string())
        .env("COURSE_NAVIGATOR_WORKSPACE_DIR", &config.workspace_dir);
    if let Some(tool_paths) = runtime_tool_paths_env_value() {
        command.env(RUNTIME_TOOL_PATHS_ENV, tool_paths);
    }
}

pub fn stop_project_services(state: &ServiceState) -> Result<(), String> {
    if let Some(child) = state
        .service
        .lock()
        .map_err(|_| "服务状态锁失效".to_string())?
        .take()
    {
        stop_child(child)?;
    }
    Ok(())
}

pub fn stop_configured_services(
    state: &ServiceState,
    config: &LauncherConfig,
) -> Result<bool, String> {
    let stopped_owned = if owns_services(state) {
        stop_project_services(state)?;
        true
    } else {
        false
    };
    let stopped_listeners = stop_configured_listeners(config, StopSignal::Term)?;

    if stopped_owned || stopped_listeners {
        if wait_for_configured_services_to_stop(config).is_ok() {
            return Ok(true);
        }
        let killed_listeners = stop_configured_listeners(config, StopSignal::Kill)?;
        if killed_listeners && wait_for_configured_services_to_stop(config).is_ok() {
            return Ok(true);
        }
        Err("已发送停止信号，但端口仍在监听；请稍后再检查或手动结束残留进程。".to_string())
    } else if any_configured_service_listening(config) {
        Err("端口上有服务在运行，但没有安全识别为当前项目服务；未执行停止。".to_string())
    } else {
        Ok(false)
    }
}

#[cfg(not(windows))]
fn stop_configured_listeners(config: &LauncherConfig, signal: StopSignal) -> Result<bool, String> {
    let mut groups = HashSet::new();
    let mut direct_pids = HashSet::new();
    let current_pgid = process_group_id(std::process::id());
    for (host, port) in [
        (&config.api_host, config.api_port),
        (&config.web_host, config.web_port),
    ] {
        if !endpoint_listening(host, port) {
            continue;
        }
        for pid in listening_pids(port) {
            let command = process_command(pid);
            let cwd = process_cwd(pid);
            if is_project_service_command_with_cwd(&command, cwd.as_deref(), config, port) {
                if let Some(pgid) = process_group_id(pid) {
                    insert_service_group(&mut groups, pgid, current_pgid);
                } else {
                    direct_pids.insert(pid);
                }
            }
        }
    }

    let stopped_any = !groups.is_empty() || !direct_pids.is_empty();
    remove_launchd_jobs_for_processes(&groups, &direct_pids)?;
    for pgid in groups {
        stop_process_group(pgid, signal)?;
    }
    for pid in direct_pids {
        stop_pid(pid, signal)?;
    }

    Ok(stopped_any)
}

#[cfg(windows)]
fn stop_configured_listeners(config: &LauncherConfig, signal: StopSignal) -> Result<bool, String> {
    let mut direct_pids = HashSet::new();
    for (host, port) in [
        (&config.api_host, config.api_port),
        (&config.web_host, config.web_port),
    ] {
        if !endpoint_listening(host, port) {
            continue;
        }
        for pid in listening_pids(port) {
            let command = process_command(pid);
            if is_project_service_command_with_cwd(&command, None, config, port) {
                direct_pids.insert(pid);
            }
        }
    }

    let stopped_any = !direct_pids.is_empty();
    for pid in direct_pids {
        stop_pid(pid, signal)?;
    }

    Ok(stopped_any)
}

#[cfg(not(windows))]
fn insert_service_group(groups: &mut HashSet<u32>, pgid: u32, current_pgid: Option<u32>) {
    if Some(pgid) != current_pgid {
        groups.insert(pgid);
    }
}

#[cfg(not(windows))]
fn remove_launchd_jobs_for_processes(
    groups: &HashSet<u32>,
    direct_pids: &HashSet<u32>,
) -> Result<(), String> {
    for label in launchd_labels_for_processes(groups, direct_pids) {
        let _ = Command::new(LAUNCHCTL_PATH)
            .args(["remove", &label])
            .status()
            .map_err(|error| format!("停止 launchd 服务 {label} 失败: {error}"))?;
    }
    Ok(())
}

#[cfg(not(windows))]
fn launchd_labels_for_processes(groups: &HashSet<u32>, direct_pids: &HashSet<u32>) -> Vec<String> {
    let Ok(output) = Command::new(LAUNCHCTL_PATH).arg("list").output() else {
        return Vec::new();
    };
    if !output.status.success() {
        return Vec::new();
    }
    parse_launchctl_list(
        &String::from_utf8_lossy(&output.stdout),
        groups,
        direct_pids,
    )
}

#[cfg(not(windows))]
fn parse_launchctl_list(
    raw: &str,
    groups: &HashSet<u32>,
    direct_pids: &HashSet<u32>,
) -> Vec<String> {
    raw.lines()
        .filter_map(|line| {
            let mut parts = line.split_whitespace();
            let pid = parts.next()?.parse::<u32>().ok()?;
            let _status = parts.next()?;
            let label = parts.next()?.to_string();
            let is_course_job = label.starts_with("course-navigator-api-")
                || label.starts_with("course-navigator-web-");
            if is_course_job && (groups.contains(&pid) || direct_pids.contains(&pid)) {
                Some(label)
            } else {
                None
            }
        })
        .collect()
}

fn wait_for_configured_services_to_stop(config: &LauncherConfig) -> Result<(), String> {
    for _ in 0..20 {
        if !any_configured_service_listening(config) {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(100));
    }
    Err("已发送停止信号，但端口仍在监听；请稍后再检查或手动结束残留进程。".to_string())
}

#[cfg(windows)]
fn stop_child(mut child: Child) -> Result<(), String> {
    if child
        .try_wait()
        .map_err(|error| format!("检查服务状态失败: {error}"))?
        .is_none()
    {
        stop_pid(child.id(), StopSignal::Kill)?;
    }
    let _ = child.wait();
    Ok(())
}

#[cfg(not(windows))]
fn stop_child(mut child: Child) -> Result<(), String> {
    if child
        .try_wait()
        .map_err(|error| format!("检查服务状态失败: {error}"))?
        .is_none()
    {
        if let Some(pgid) = process_group_id(child.id()) {
            if Some(pgid) == process_group_id(std::process::id()) {
                child
                    .kill()
                    .map_err(|error| format!("停止服务失败: {error}"))?;
                return child
                    .wait()
                    .map(|_| ())
                    .map_err(|error| format!("等待服务退出失败: {error}"));
            }
            stop_process_group(pgid, StopSignal::Term)?;
            if !wait_for_child_exit(&mut child)? {
                stop_process_group(pgid, StopSignal::Kill)?;
            }
        } else {
            child
                .kill()
                .map_err(|error| format!("停止服务失败: {error}"))?;
        }
    }
    child
        .wait()
        .map_err(|error| format!("等待服务退出失败: {error}"))?;
    Ok(())
}

#[cfg(not(windows))]
fn wait_for_child_exit(child: &mut Child) -> Result<bool, String> {
    for _ in 0..20 {
        if child
            .try_wait()
            .map_err(|error| format!("检查服务状态失败: {error}"))?
            .is_some()
        {
            return Ok(true);
        }
        thread::sleep(Duration::from_millis(100));
    }
    Ok(false)
}

#[cfg(not(windows))]
fn listening_pids(port: u16) -> Vec<u32> {
    let Ok(output) = Command::new(LSOF_PATH)
        .args([&format!("-tiTCP:{port}"), "-sTCP:LISTEN"])
        .output()
    else {
        return Vec::new();
    };
    if !output.status.success() {
        return Vec::new();
    }
    String::from_utf8_lossy(&output.stdout)
        .lines()
        .filter_map(|line| line.trim().parse::<u32>().ok())
        .collect()
}

/// netstat answers in milliseconds where starting PowerShell takes seconds.
#[cfg(windows)]
fn listening_pids(port: u16) -> Vec<u32> {
    let Ok(output) = hidden_command("netstat").arg("-ano").output() else {
        return Vec::new();
    };
    let mut pids = listening_pids_in_netstat(&String::from_utf8_lossy(&output.stdout), port);
    pids.sort_unstable();
    pids.dedup();
    pids
}

/// Rows are `Proto Local Foreign State PID`. The state column is localized,
/// so a listener is recognized by its unconnected foreign port 0 instead.
#[cfg(any(windows, test))]
fn listening_pids_in_netstat(output: &str, port: u16) -> Vec<u32> {
    let port = port.to_string();
    output
        .lines()
        .filter_map(|line| {
            let fields = line.split_whitespace().collect::<Vec<_>>();
            let [proto, local, foreign, _state, pid] = fields.as_slice() else {
                return None;
            };
            let local_port = local.rsplit_once(':')?.1;
            let foreign_port = foreign.rsplit_once(':')?.1;
            (proto.eq_ignore_ascii_case("TCP") && local_port == port && foreign_port == "0")
                .then(|| pid.parse().ok())
                .flatten()
        })
        .collect()
}

#[cfg(not(windows))]
fn process_command(pid: u32) -> String {
    let Ok(output) = Command::new(PS_PATH)
        .args(["-p", &pid.to_string(), "-o", "command="])
        .output()
    else {
        return String::new();
    };
    String::from_utf8_lossy(&output.stdout).trim().to_string()
}

#[cfg(windows)]
fn process_command(pid: u32) -> String {
    let script = format!(
        "(Get-CimInstance Win32_Process -Filter \"ProcessId = {pid}\" -ErrorAction SilentlyContinue).CommandLine"
    );
    let Ok(output) = hidden_command("powershell")
        .args(["-NoProfile", "-Command", &script])
        .output()
    else {
        return String::new();
    };
    String::from_utf8_lossy(&output.stdout).trim().to_string()
}

#[cfg(not(windows))]
fn process_cwd(pid: u32) -> Option<String> {
    let output = Command::new(LSOF_PATH)
        .args(["-a", "-p", &pid.to_string(), "-d", "cwd", "-Fn"])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    parse_lsof_cwd(&String::from_utf8_lossy(&output.stdout))
}

#[cfg(not(windows))]
fn parse_lsof_cwd(raw: &str) -> Option<String> {
    raw.lines()
        .find_map(|line| line.strip_prefix('n').map(str::to_string))
}

#[cfg(not(windows))]
fn process_group_id(pid: u32) -> Option<u32> {
    let output = Command::new(PS_PATH)
        .args(["-p", &pid.to_string(), "-o", "pgid="])
        .output()
        .ok()?;
    String::from_utf8_lossy(&output.stdout)
        .trim()
        .parse::<u32>()
        .ok()
}

fn is_project_service_command_with_cwd(
    command: &str,
    cwd: Option<&str>,
    config: &LauncherConfig,
    port: u16,
) -> bool {
    if !matches_project_root(command, cwd, config) {
        return false;
    }
    // The service now listens on the web port; older versions ran the API on
    // the API port and Vite on the web port, and those leftovers are stopped too.
    if (port == config.web_port || port == config.api_port)
        && command.contains("course_navigator.app:app")
        && command_contains_port(command, port)
    {
        return true;
    }
    port == config.web_port
        && (command.contains("vite") || command.contains("npm run dev"))
        && command_contains_port(command, port)
}

fn matches_project_root(command: &str, cwd: Option<&str>, config: &LauncherConfig) -> bool {
    let root = config.project_root.trim();
    if root.is_empty() {
        return false;
    }
    if command_mentions_path(command, root) {
        return true;
    }
    let root_path = Path::new(root);
    cwd.is_some_and(|cwd| {
        let cwd_path = Path::new(cwd);
        cwd_path == root_path || cwd_path.starts_with(root_path)
    })
}

/// True when `root` appears as a whole path in `command`, so `/app/project`
/// does not match a process started from `/app/project-other`.
fn command_mentions_path(command: &str, root: &str) -> bool {
    let root = root.trim_end_matches(['/', '\\']);
    if root.is_empty() {
        return false;
    }
    let (command, root) = if cfg!(windows) {
        (command.to_lowercase(), root.to_lowercase())
    } else {
        (command.to_string(), root.to_string())
    };
    command.match_indices(&root).any(|(start, _)| {
        let starts_path = command[..start]
            .chars()
            .next_back()
            .is_none_or(|previous| matches!(previous, '"' | '\'' | '=') || previous.is_whitespace());
        let ends_path = command[start + root.len()..]
            .chars()
            .next()
            .is_none_or(|next| matches!(next, '/' | '\\' | '"' | '\'') || next.is_whitespace());
        starts_path && ends_path
    })
}

fn command_contains_port(command: &str, port: u16) -> bool {
    let port = port.to_string();
    command.split_whitespace().any(|part| {
        part == port || part == format!("--port={port}") || part.ends_with(&format!(":{port}"))
    })
}

#[cfg(not(windows))]
fn stop_process_group(pgid: u32, signal: StopSignal) -> Result<(), String> {
    let status = Command::new(KILL_PATH)
        .args([signal.as_arg(), &format!("-{pgid}")])
        .status()
        .map_err(|error| format!("停止进程组 {pgid} 失败: {error}"))?;
    if status.success() {
        Ok(())
    } else {
        Err(format!("停止进程组 {pgid} 失败"))
    }
}

#[cfg(not(windows))]
fn stop_pid(pid: u32, signal: StopSignal) -> Result<(), String> {
    let status = Command::new(KILL_PATH)
        .args([signal.as_arg(), &pid.to_string()])
        .status()
        .map_err(|error| format!("停止进程 {pid} 失败: {error}"))?;
    if status.success() {
        Ok(())
    } else {
        Err(format!("停止进程 {pid} 失败"))
    }
}

#[cfg(windows)]
fn stop_pid(pid: u32, signal: StopSignal) -> Result<(), String> {
    let args = windows_taskkill_args(pid, signal);
    let status = hidden_command("taskkill")
        .args(args)
        .status()
        .map_err(|error| format!("停止进程 {pid} 失败: {error}"))?;
    if status.success() {
        Ok(())
    } else {
        Err(format!("停止进程 {pid} 失败"))
    }
}

#[cfg(windows)]
fn windows_taskkill_args(pid: u32, _signal: StopSignal) -> Vec<String> {
    vec![
        "/PID".to_string(),
        pid.to_string(),
        "/T".to_string(),
        "/F".to_string(),
    ]
}

fn command_exists(name: &str) -> bool {
    if bundled_tool_program(name).is_some() {
        return true;
    }
    if cfg!(windows) {
        hidden_command("cmd")
            .args(["/C", "where", tool_command_name(name)])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map(|status| status.success())
            .unwrap_or(false)
    } else {
        hidden_command(LOGIN_SHELL_PATH)
            .arg("-lic")
            .arg(shell_command_with_bundled_tool_paths(&format!(
                "command -v {name} >/dev/null 2>&1"
            )))
            .status()
            .map(|status| status.success())
            .unwrap_or(false)
    }
}

fn ensure_project_dependencies(
    project_root: &Path,
    state: &ServiceState,
    progress: &dyn Fn(&str),
) -> Result<(), String> {
    if !command_exists("uv") {
        return Err("缺少运行依赖: uv。请安装后再启动。".to_string());
    }
    // The download is large and failures are not fatal; never pay for it on
    // every start when ffmpeg is already reachable on PATH.
    if cfg!(windows) && !media_tools_available() {
        progress("正在下载 ffmpeg / ffprobe...");
        prepare_preferred_windows_tools(state);
        if state.start_cancelled() {
            return Err(START_CANCELLED.to_string());
        }
    }

    let commands = project_setup_commands(project_root);
    if !commands.is_empty() {
        let log = open_fresh_log("setup")?;
        for command in &commands {
            run_setup_command(project_root, command, &log, state, progress)?;
        }
    }
    write_dependency_marker(project_root)?;
    Ok(())
}

fn project_setup_commands(project_root: &Path) -> Vec<RuntimeCommand> {
    let mut commands = Vec::new();
    let python_fingerprint = dependency_fingerprint(project_root, &["pyproject.toml", "uv.lock"]);
    if !project_root.join(".venv").exists()
        || !dependency_marker_matches(project_root, "python", &python_fingerprint)
    {
        commands.push(setup_uv_command());
    }
    commands
}

fn setup_uv_command() -> RuntimeCommand {
    if cfg!(windows) {
        // --frozen keeps uv from rewriting uv.lock, which would change the
        // dependency fingerprint and force another sync on the next start.
        RuntimeCommand {
            program: "uv".into(),
            args: vec!["sync".into(), "--frozen".into()],
        }
    } else {
        RuntimeCommand {
            program: LOGIN_SHELL_PATH.into(),
            args: vec![
                "-lic".into(),
                shell_command_with_bundled_tool_paths("uv sync --frozen"),
            ],
        }
    }
}

fn tool_command_name(name: &str) -> &str {
    if cfg!(windows) {
        match name {
            "uv" => "uv.exe",
            "ffmpeg" => "ffmpeg.exe",
            "ffprobe" => "ffprobe.exe",
            other => other,
        }
    } else {
        name
    }
}

fn dependency_marker_matches(project_root: &Path, key: &str, fingerprint: &str) -> bool {
    let Ok(raw) = fs::read_to_string(project_root.join(DEPENDENCY_MARKER_FILE)) else {
        return false;
    };
    let Ok(value) = serde_json::from_str::<serde_json::Value>(&raw) else {
        return false;
    };
    value
        .get(key)
        .and_then(|value| value.as_str())
        .is_some_and(|stored| stored == fingerprint)
}

fn write_dependency_marker(project_root: &Path) -> Result<(), String> {
    let marker = serde_json::json!({
        "python": dependency_fingerprint(project_root, &["pyproject.toml", "uv.lock"]),
    });
    let raw = serde_json::to_string_pretty(&marker)
        .map_err(|error| format!("无法序列化依赖状态: {error}"))?;
    fs::write(
        project_root.join(DEPENDENCY_MARKER_FILE),
        format!("{raw}\n"),
    )
    .map_err(|error| format!("无法写入依赖状态: {error}"))
}

fn dependency_fingerprint(project_root: &Path, files: &[&str]) -> String {
    let mut hasher = DefaultHasher::new();
    for file in files {
        file.hash(&mut hasher);
        match fs::read(project_root.join(file)) {
            Ok(bytes) => bytes.hash(&mut hasher),
            Err(_) => "missing".hash(&mut hasher),
        }
    }
    format!("{:016x}", hasher.finish())
}

/// Runs one install step with output in setup.log, honoring cancel and a timeout.
fn run_setup_command(
    project_root: &Path,
    command: &RuntimeCommand,
    log: &File,
    state: &ServiceState,
    progress: &dyn Fn(&str),
) -> Result<(), String> {
    let label = "Python 依赖";
    let log_error = |error: std::io::Error| format!("无法写入安装日志: {error}");
    let mut header = log.try_clone().map_err(log_error)?;
    let _ = writeln!(header, "\n$ {} {}", command.program, command.args.join(" "));
    let mut setup = service_command(&command.program);
    setup
        .args(&command.args)
        .current_dir(project_root)
        .stdin(Stdio::null())
        .stdout(log.try_clone().map_err(log_error)?)
        .stderr(log.try_clone().map_err(log_error)?);
    let mut child = spawn_managed(&mut setup).map_err(|error| format!("准备{label}失败: {error}"))?;

    let mut last_report = None;
    let waited = wait_managed_child(&mut child, state, SETUP_COMMAND_TIMEOUT, |elapsed| {
        let seconds = elapsed.as_secs();
        if last_report.map_or(true, |last| seconds >= last + 10) {
            last_report = Some(seconds);
            progress(&format!(
                "正在安装{label}（已用时 {seconds} 秒），首次启动可能需要几分钟..."
            ));
        }
    });
    match waited {
        Ok(ChildWait::Exited(status)) if status.success() => Ok(()),
        Ok(ChildWait::Exited(status)) => Err(format!(
            "准备{label}失败（{status}）。\n{}",
            log_excerpt("setup")
        )),
        Ok(ChildWait::Cancelled) => Err(START_CANCELLED.to_string()),
        Ok(ChildWait::TimedOut) => Err(format!(
            "准备{label}超过 {} 分钟仍未完成，已停止。请检查网络后重试。\n{}",
            SETUP_COMMAND_TIMEOUT.as_secs() / 60,
            log_excerpt("setup")
        )),
        Err(error) => Err(format!("检查{label}安装状态失败: {error}")),
    }
}

enum ChildWait {
    Exited(std::process::ExitStatus),
    Cancelled,
    TimedOut,
}

/// Polls a managed child until it exits, the start is cancelled or the timeout
/// passes. Cancellation, timeout and polling errors stop its whole tree.
fn wait_managed_child(
    child: &mut Child,
    state: &ServiceState,
    timeout: Duration,
    mut on_tick: impl FnMut(Duration),
) -> std::io::Result<ChildWait> {
    let started = Instant::now();
    loop {
        match child.try_wait() {
            Ok(Some(status)) => return Ok(ChildWait::Exited(status)),
            Ok(None) => {}
            Err(error) => {
                kill_child_tree(child);
                return Err(error);
            }
        }
        if state.start_cancelled() {
            kill_child_tree(child);
            return Ok(ChildWait::Cancelled);
        }
        let elapsed = started.elapsed();
        if elapsed >= timeout {
            kill_child_tree(child);
            return Ok(ChildWait::TimedOut);
        }
        on_tick(elapsed);
        thread::sleep(POLL_INTERVAL);
    }
}

fn kill_child_tree(child: &mut Child) {
    #[cfg(windows)]
    let _ = stop_pid(child.id(), StopSignal::Kill);
    // service_command puts the child in its own process group (pgid == pid).
    #[cfg(not(windows))]
    let _ = stop_process_group(child.id(), StopSignal::Kill);
    let _ = child.kill();
    let _ = child.wait();
}

fn service_command(program: &str) -> Command {
    let mut command = hidden_command(program);
    set_service_process_group(&mut command);
    command
}

/// Spawns a service or setup process; on Windows it joins the launcher's
/// kill-on-close job so it cannot outlive the launcher.
fn spawn_managed(command: &mut Command) -> std::io::Result<Child> {
    #[cfg(windows)]
    {
        crate::job::spawn_in_job(command, CREATE_NO_WINDOW)
    }
    #[cfg(not(windows))]
    {
        command.spawn()
    }
}

fn web_build_present(project_root: &Path) -> bool {
    project_root.join(WEB_BUILD_INDEX).is_file()
}

fn hidden_command(program: &str) -> Command {
    let mut command = Command::new(program);
    set_hidden_window(&mut command);
    prepend_bundled_tool_paths(&mut command);
    command
}

#[cfg(windows)]
fn set_hidden_window(command: &mut Command) {
    use std::os::windows::process::CommandExt;

    command.creation_flags(CREATE_NO_WINDOW);
}

#[cfg(not(windows))]
fn set_hidden_window(_command: &mut Command) {}

fn prepend_bundled_tool_paths(command: &mut Command) {
    let tool_paths = bundled_tool_paths();
    if tool_paths.is_empty() {
        return;
    }
    let existing_path = env::var_os("PATH").unwrap_or_default();
    let paths = tool_paths
        .into_iter()
        .chain(env::split_paths(&existing_path))
        .collect::<Vec<_>>();
    if let Ok(joined) = env::join_paths(paths) {
        command.env("PATH", joined);
    }
}

fn bundled_tool_paths() -> Vec<PathBuf> {
    let mut roots = Vec::new();
    if let Some(root) = bundled_tools_root() {
        roots.push(root);
    }
    roots.push(installed_tools_root());
    roots
        .into_iter()
        .flat_map(|root| tool_path_entries_from_root(&root))
        .filter(|path| path.exists())
        .collect()
}

fn tool_path_entries_from_root(root: &Path) -> Vec<PathBuf> {
    if cfg!(windows) {
        // node is only the JavaScript runtime yt-dlp needs; npm is not shipped.
        ["node", "uv", "ffmpeg"]
            .into_iter()
            .map(|name| root.join(name))
            .collect()
    } else {
        vec![
            root.join("node").join("bin"),
            root.join("uv"),
            root.join("ffmpeg"),
        ]
    }
}

fn bundled_tool_program(name: &str) -> Option<PathBuf> {
    let executable = tool_command_name(name);
    bundled_tool_paths()
        .into_iter()
        .map(|dir| dir.join(executable))
        .find(|path| path.exists())
}

fn runtime_tool_paths_env_value() -> Option<OsString> {
    runtime_tool_paths_env_value_from(&bundled_tool_paths())
}

fn runtime_tool_paths_env_value_from(paths: &[PathBuf]) -> Option<OsString> {
    if paths.is_empty() {
        return None;
    }
    env::join_paths(paths).ok()
}

fn bundled_tools_root() -> Option<PathBuf> {
    let exe = env::current_exe().ok()?;
    bundled_tools_root_from_exe(&exe, platform_tool_dir())
}

fn bundled_tools_root_from_exe(exe: &Path, platform_dir: &str) -> Option<PathBuf> {
    if cfg!(target_os = "macos") {
        exe.parent()?.parent().map(|contents_dir| {
            contents_dir
                .join("Resources")
                .join("runtime-tools")
                .join(platform_dir)
        })
    } else {
        exe.parent()
            .map(|dir| dir.join("runtime-tools").join(platform_dir))
    }
}

/// Removes what older versions left in the user's tool folder: a standalone
/// yt-dlp (now a Python dependency) and temp folders of interrupted downloads.
pub fn remove_legacy_tool_files() {
    remove_legacy_tool_files_in(&installed_tools_root());
}

fn remove_legacy_tool_files_in(root: &Path) {
    for name in LEGACY_TOOL_DIRS {
        let _ = fs::remove_dir_all(root.join(name));
    }
}

const LEGACY_TOOL_DIRS: [&str; 2] = ["ytdlp", ".tmp"];

fn installed_tools_root() -> PathBuf {
    crate::config::application_support_dir()
        .join("runtime-tools")
        .join(platform_tool_dir())
}

fn platform_tool_dir() -> &'static str {
    if cfg!(windows) {
        "windows"
    } else if cfg!(all(target_os = "macos", target_arch = "aarch64")) {
        "darwin-arm64"
    } else if cfg!(all(target_os = "macos", target_arch = "x86_64")) {
        "darwin-x64"
    } else {
        "unix"
    }
}

#[cfg(unix)]
fn set_service_process_group(command: &mut Command) {
    use std::os::unix::process::CommandExt;

    command.process_group(0);
}

#[cfg(not(unix))]
fn set_service_process_group(_command: &mut Command) {}

fn shell_quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\\''"))
}

#[cfg(not(windows))]
fn shell_command_with_bundled_tool_paths(command: &str) -> String {
    shell_command_with_tool_paths(command, &bundled_tool_paths())
}

#[cfg(windows)]
fn shell_command_with_bundled_tool_paths(command: &str) -> String {
    command.to_string()
}

#[cfg(not(windows))]
fn shell_command_with_tool_paths(command: &str, paths: &[PathBuf]) -> String {
    if paths.is_empty() {
        return command.to_string();
    }
    let joined = paths
        .iter()
        .map(|path| shell_quote(&path.to_string_lossy()))
        .collect::<Vec<_>>()
        .join(":");
    format!("export PATH={joined}:$PATH; {command}")
}

pub fn endpoint_listening(host: &str, port: u16) -> bool {
    // Connecting to a wildcard address fails on Windows; a service bound there
    // also answers on loopback.
    let Ok(addresses) = (service_connect_host(host), port).to_socket_addrs() else {
        return false;
    };
    addresses
        .into_iter()
        .any(|address| TcpStream::connect_timeout(&address, Duration::from_millis(180)).is_ok())
}

fn course_api_ready(config: &LauncherConfig) -> bool {
    http_get(&config.web_host, config.web_port, "/api/health").is_some_and(|response| {
        http_response_ok(&response)
            && (response.contains("\"name\":\"Course Navigator\"")
                || response.contains("\"name\": \"Course Navigator\""))
    })
}

fn course_web_ready(config: &LauncherConfig) -> bool {
    http_get(&config.web_host, config.web_port, "/").is_some_and(|response| {
        http_response_ok(&response) && response.contains("<title>Course Navigator</title>")
    })
}

fn http_response_ok(response: &str) -> bool {
    response.starts_with("HTTP/1.1 200") || response.starts_with("HTTP/1.0 200")
}

/// A wildcard bind address accepts connections but cannot be connected to.
fn service_connect_host(host: &str) -> &str {
    match host.trim() {
        "" | "0.0.0.0" | "::" | "[::]" => "127.0.0.1",
        host => host,
    }
}

/// Sends a JSON request to the running service, which serves the API on the
/// web port.
pub(crate) fn send_service_json(
    config: &LauncherConfig,
    method: &str,
    path: &str,
    body: Option<&serde_json::Value>,
) -> Result<(), String> {
    let host = service_connect_host(&config.web_host);
    let addr = (host, config.web_port)
        .to_socket_addrs()
        .map_err(|error| format!("无法解析服务地址: {error}"))?
        .next()
        .ok_or_else(|| "无法解析服务地址".to_string())?;
    let mut stream = TcpStream::connect_timeout(&addr, Duration::from_millis(500))
        .map_err(|error| format!("无法连接服务: {error}"))?;
    let _ = stream.set_read_timeout(Some(Duration::from_secs(5)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(1200)));

    let raw = body
        .map(serde_json::to_string)
        .transpose()
        .map_err(|error| format!("无法序列化服务请求: {error}"))?
        .unwrap_or_default();
    let request = format!(
        "{method} {path} HTTP/1.1\r\nHost: {host}:{}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        config.web_port,
        raw.len(),
        raw
    );
    stream
        .write_all(request.as_bytes())
        .map_err(|error| format!("无法写入服务请求: {error}"))?;
    let mut response = String::new();
    let _ = stream.read_to_string(&mut response);
    if response.starts_with("HTTP/1.1 2") || response.starts_with("HTTP/1.0 2") {
        Ok(())
    } else {
        let status = response.lines().next().unwrap_or("无响应");
        Err(format!("服务请求 {path} 失败: {status}"))
    }
}

fn http_get(host: &str, port: u16, path: &str) -> Option<String> {
    let host = service_connect_host(host);
    let address = (host, port).to_socket_addrs().ok()?.next()?;
    let mut stream = TcpStream::connect_timeout(&address, Duration::from_millis(220)).ok()?;
    // A closed port fails at connect; a live dev server can take over half a
    // second to answer its first requests, which must not read as "down".
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(600)));
    let request = format!("GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n");
    stream.write_all(request.as_bytes()).ok()?;
    let mut response = String::new();
    stream.read_to_string(&mut response).ok()?;
    Some(response)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::LauncherConfig;
    use std::net::TcpListener;

    fn config() -> LauncherConfig {
        LauncherConfig {
            project_root: "/repo".into(),
            api_host: "127.0.0.1".into(),
            api_port: 8100,
            web_host: "127.0.0.1".into(),
            web_port: 5188,
            workspace_dir: "/repo/course-navigator-workspace".into(),
            open_browser_on_start: true,
        }
    }

    fn unused_local_port() -> u16 {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind unused local port");
        listener
            .local_addr()
            .expect("read unused local port")
            .port()
    }

    #[test]
    fn project_root_matches_only_whole_paths() {
        let config = config();
        assert!(matches_project_root("python /repo/.venv/bin/python -m x", None, &config));
        assert!(matches_project_root("node \"/repo\" --port 5188", None, &config));
        assert!(matches_project_root("node /repo", None, &config));
        assert!(!matches_project_root("python /repo-other/.venv/bin/python", None, &config));
        assert!(!matches_project_root("python /repository/app.py", None, &config));
        assert!(!matches_project_root("node /archive/repo/node_modules/.bin/vite --port 15173", None, &config));
        assert!(matches_project_root("uvicorn app --app-dir=/repo/backend", None, &config));
        assert!(matches_project_root("python app.py", Some("/repo/backend"), &config));
        assert!(!matches_project_root("python app.py", Some("/repo-other"), &config));
    }

    #[test]
    fn an_unresponsive_service_still_counts_as_running_for_destructive_work() {
        // Accepts connections but never answers, like a busy or stuck service.
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind web port");
        let mut config = config();
        config.web_port = listener.local_addr().expect("web addr").port();

        assert!(!configured_services_listening(&config));
        assert!(service_may_be_running(None, &config));
        assert!(crate::asr_cache::cleanup(None, &config).is_err());

        drop(listener);
        assert!(!service_may_be_running(Some(&ServiceState::new()), &config));
    }

    #[test]
    fn a_silent_service_on_a_wildcard_address_blocks_cleanup_and_model_save() {
        let listener = TcpListener::bind("0.0.0.0:0").expect("bind wildcard web port");
        let (root, audio) = project_with_cached_audio("wildcard");

        let mut config = config();
        config.project_root = root.to_string_lossy().to_string();
        config.web_host = "0.0.0.0".into();
        config.web_port = listener.local_addr().expect("web addr").port();

        assert!(endpoint_listening(&config.web_host, config.web_port));
        assert!(!configured_services_listening(&config));
        assert!(service_may_be_running(None, &config));
        let error = crate::asr_cache::cleanup(None, &config).expect_err("cleanup refused");
        assert!(error.contains("服务没有响应"), "{error}");
        assert_eq!(std::fs::read(&audio).expect("cached audio kept"), b"audio");
        let error = crate::model_config::set_online_asr_provider(None, &config, "openai")
            .expect_err("save reports the unsynced service");
        assert!(error.contains("服务没有响应"), "{error}");

        drop(listener);
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn a_live_child_counts_as_running_before_its_port_listens() {
        let (root, audio) = project_with_cached_audio("live-child");

        let mut config = config();
        config.project_root = root.to_string_lossy().to_string();
        config.web_port = unused_local_port();

        #[cfg(windows)]
        let mut command = Command::new("ping");
        #[cfg(windows)]
        command.args(["-n", "60", "127.0.0.1"]);
        #[cfg(not(windows))]
        let mut command = Command::new("sleep");
        #[cfg(not(windows))]
        command.arg("60");
        let child = command
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("spawn long-running child");
        let state = ServiceState::new();
        *state.service.lock().expect("service lock") = Some(child);

        assert!(!any_configured_service_listening(&config));
        assert!(service_may_be_running(Some(&state), &config));
        let error = crate::asr_cache::cleanup(Some(&state), &config).expect_err("cleanup refused");
        assert!(error.contains("服务没有响应"), "{error}");
        assert_eq!(std::fs::read(&audio).expect("cached audio kept"), b"audio");
        let error = crate::model_config::set_online_asr_provider(Some(&state), &config, "openai")
            .expect_err("save reports the unsynced service");
        assert!(error.contains("服务没有响应"), "{error}");

        if let Some(mut child) = state.service.lock().expect("service lock").take() {
            let _ = child.kill();
            let _ = child.wait();
        }
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn service_requests_never_connect_to_a_wildcard_address() {
        assert_eq!(service_connect_host("0.0.0.0"), "127.0.0.1");
        assert_eq!(service_connect_host("::"), "127.0.0.1");
        assert_eq!(service_connect_host("localhost"), "localhost");
    }

    #[test]
    fn service_requests_use_the_web_port() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind web port");
        let mut config = config();
        config.web_port = listener.local_addr().expect("web addr").port();
        config.api_port = unused_local_port();
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept");
            let mut buffer = [0_u8; 1024];
            let size = stream.read(&mut buffer).expect("read request");
            stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}")
                .expect("write response");
            String::from_utf8_lossy(&buffer[..size]).to_string()
        });

        send_service_json(&config, "PUT", "/api/settings/model", Some(&serde_json::json!({})))
            .expect("request reaches the web port");
        assert!(server.join().expect("server").starts_with("PUT /api/settings/model HTTP/1.1"));
    }

    #[test]
    #[cfg(not(windows))]
    fn app_command_serves_on_the_web_port() {
        let command = app_command(&config());
        assert_eq!(command.program, LOGIN_SHELL_PATH);
        assert!(command
            .args
            .iter()
            .any(|arg| arg.contains("uv run --frozen uvicorn")));
        assert!(command.args.iter().any(|arg| arg.contains("--port 5188")));
    }

    #[test]
    #[cfg(windows)]
    fn windows_app_command_does_not_depend_on_unix_shell() {
        let app = app_command(&config());

        assert_ne!(app.program, LOGIN_SHELL_PATH);
        assert_eq!(app.program, "uv");
        assert_eq!(
            app.args,
            vec![
                "run",
                "--frozen",
                "uvicorn",
                "course_navigator.app:app",
                "--app-dir",
                "backend",
                "--host",
                "127.0.0.1",
                "--port",
                "5188"
            ]
        );
    }

    #[test]
    fn pages_and_api_share_the_web_origin() {
        assert_eq!(web_url(&config()), "http://127.0.0.1:5188");
        assert_eq!(api_url(&config()), "http://127.0.0.1:5188/api");
    }

    #[test]
    fn start_requires_the_built_web_pages() {
        let root = temp_project_dir("missing-web-build");
        let mut config = config();
        config.project_root = root.display().to_string();
        config.web_port = unused_local_port();
        let state = ServiceState::new();

        let error = start_project_services(&state, &config, &|_| {}).expect_err("no build");

        assert!(error.contains("frontend"));
        assert!(error.contains("npm run build"));
        assert!(!owns_services(&state));
        std::fs::create_dir_all(root.join("frontend/dist")).expect("dist");
        std::fs::write(root.join(WEB_BUILD_INDEX), "<title>Course Navigator</title>").expect("index");
        assert!(web_build_present(&root));
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn shell_quote_wraps_values_for_login_shell_commands() {
        assert_eq!(shell_quote("127.0.0.1"), "'127.0.0.1'");
        assert_eq!(shell_quote("can't"), "'can'\\''t'");
    }

    #[test]
    #[cfg(not(windows))]
    fn login_shell_commands_can_pin_bundled_tool_paths() {
        let paths = vec![
            PathBuf::from("/Applications/Course Navigator.app/Contents/Resources/runtime-tools/darwin-arm64/node/bin"),
            PathBuf::from("/Applications/Course Navigator.app/Contents/Resources/runtime-tools/darwin-arm64/uv"),
        ];

        assert_eq!(
            shell_command_with_tool_paths("exec uv run uvicorn", &paths),
            "export PATH='/Applications/Course Navigator.app/Contents/Resources/runtime-tools/darwin-arm64/node/bin':'/Applications/Course Navigator.app/Contents/Resources/runtime-tools/darwin-arm64/uv':$PATH; exec uv run uvicorn"
        );
    }

    #[test]
    fn runtime_tool_paths_env_value_preserves_path_entries() {
        let paths = vec![PathBuf::from("/runtime/node"), PathBuf::from("/runtime/uv")];
        let joined = runtime_tool_paths_env_value_from(&paths).expect("join tool paths");

        assert_eq!(env::split_paths(&joined).collect::<Vec<_>>(), paths);
    }

    #[test]
    fn only_one_start_or_stop_runs_at_a_time() {
        let state = ServiceState::new();
        let guard = state.begin_operation("starting", "正在检查运行依赖...");
        assert!(guard.is_some());
        assert!(state.begin_operation("stopping", "正在停止").is_none());
        assert_eq!(state.current_operation().map(|op| op.state), Some("starting"));
        drop(guard);
        assert!(state.current_operation().is_none());
        assert!(state.begin_operation("stopping", "正在停止").is_some());
    }

    #[test]
    fn stop_request_cancels_only_a_running_start() {
        let state = ServiceState::new();
        assert!(!state.request_start_cancel());
        assert!(!state.start_cancelled());

        let guard = state.begin_operation("starting", "正在启动");
        assert!(state.request_start_cancel());
        assert!(state.start_cancelled());
        assert_eq!(
            state.current_operation().map(|op| op.message),
            Some("正在取消启动...".to_string())
        );
        drop(guard);

        // A new start clears the previous cancellation.
        let _guard = state.begin_operation("starting", "正在启动");
        assert!(!state.start_cancelled());
    }

    fn long_running_command() -> Command {
        let mut command = if cfg!(windows) {
            let mut command = service_command("ping");
            command.args(["-n", "30", "127.0.0.1"]);
            command
        } else {
            let mut command = service_command("sleep");
            command.arg("30");
            command
        };
        command.stdout(Stdio::null());
        command
    }

    #[test]
    fn waiting_on_a_child_stops_it_on_timeout_or_cancelled_start() {
        let state = ServiceState::new();
        let _guard = state.begin_operation("starting", "正在启动");

        let mut child = spawn_managed(&mut long_running_command()).unwrap();
        let started = Instant::now();
        let waited = wait_managed_child(&mut child, &state, Duration::from_millis(300), |_| {});
        assert!(matches!(waited, Ok(ChildWait::TimedOut)));
        assert!(started.elapsed() < Duration::from_secs(10));
        assert!(child.try_wait().unwrap().is_some());

        let mut child = spawn_managed(&mut long_running_command()).unwrap();
        assert!(state.request_start_cancel());
        let waited = wait_managed_child(&mut child, &state, Duration::from_secs(60), |_| {});
        assert!(matches!(waited, Ok(ChildWait::Cancelled)));
        assert!(child.try_wait().unwrap().is_some());
    }

    #[test]
    fn netstat_rows_yield_only_listeners_on_the_port() {
        let output = "\
活动连接

  协议  本地地址          外部地址        状态           PID
  TCP    0.0.0.0:15173          0.0.0.0:0              侦听           4100
  TCP    127.0.0.1:15173        127.0.0.1:52000        ESTABLISHED     4100
  TCP    127.0.0.1:52000        127.0.0.1:15173        ESTABLISHED     7300
  TCP    0.0.0.0:151730         0.0.0.0:0              LISTENING       8800
  TCP    0.0.0.0:5173           0.0.0.0:0              LISTENING       8801
  TCP    [::]:15173             [::]:0                 LISTENING       4200
  UDP    0.0.0.0:15173          *:*                                    9900
";
        assert_eq!(listening_pids_in_netstat(output, 15173), vec![4100, 4200]);
        assert!(listening_pids_in_netstat(output, 8000).is_empty());
    }

    #[test]
    #[cfg(windows)]
    fn listening_pids_finds_a_live_listener() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        assert_eq!(listening_pids(port), vec![std::process::id()]);
    }

    #[test]
    fn waiting_for_idle_reports_a_stuck_operation() {
        let state = ServiceState::new();
        assert!(state.wait_for_idle(Duration::from_millis(10)));
        let _guard = state.begin_operation("starting", "正在启动");
        assert!(!state.wait_for_idle(Duration::from_millis(10)));
    }

    #[test]
    fn log_excerpt_keeps_the_last_non_empty_lines() {
        let text = "one\n\ntwo\r\nthree  \n   \nfour\n";
        assert_eq!(last_lines(text, 3), "two\nthree\nfour");
        assert_eq!(last_lines(text, 10), "one\ntwo\nthree\nfour");
        assert_eq!(last_lines("", 3), "");
    }

    /// Real start/stop against a prepared project copy with installed
    /// dependencies. Opt-in: set COURSE_NAVIGATOR_E2E_PROJECT and run with
    /// `cargo test --lib real_start -- --ignored --nocapture`. APPDATA is
    /// redirected so logs and the dependency marker stay out of the user's data.
    #[test]
    #[ignore]
    fn real_start_reports_ready_services_and_exited_processes() {
        let Some(project) = env::var_os("COURSE_NAVIGATOR_E2E_PROJECT") else {
            return;
        };
        let project = PathBuf::from(project);
        let support = project.join(".e2e-appdata");
        env::set_var("APPDATA", &support);
        env::set_var("HOME", &support);
        write_dependency_marker(&project).expect("dependency marker");

        let mut config = config();
        config.project_root = project.display().to_string();
        config.workspace_dir = project.join("workspace").display().to_string();
        config.api_port = unused_local_port();
        config.web_port = unused_local_port();
        let state = ServiceState::new();
        // Stop the services even when an assertion fails, or they outlive the test.
        struct StopOnDrop<'a>(&'a ServiceState, &'a LauncherConfig);
        impl Drop for StopOnDrop<'_> {
            fn drop(&mut self) {
                let _ = stop_configured_services(self.0, self.1);
            }
        }
        let _stop = StopOnDrop(&state, &config);
        let messages = Mutex::new(Vec::<String>::new());
        let progress = |message: &str| messages.lock().unwrap().push(message.to_string());

        let started = Instant::now();
        let result = start_project_services(&state, &config, &progress);
        println!("start: {:?} after {:?}", result, started.elapsed());
        println!("progress: {:?}", messages.lock().unwrap());
        assert!(result.is_ok());
        assert!(configured_services_listening(&config));
        assert!(fs::read_to_string(log_path(SERVICE_LOG)).unwrap().contains("Uvicorn running"));
        // Launcher requests pass the service's host check. A read keeps the
        // project's .env and caches untouched.
        send_service_json(&config, "GET", "/api/settings/asr-cache", None).expect("launcher request");
        assert!(stop_configured_services(&state, &config).expect("stop"));
        assert!(!any_configured_service_listening(&config));

        // A service that exits during startup is reported at once with its log.
        let backend = project.join("backend");
        let hidden = project.join("backend-hidden");
        fs::rename(&backend, &hidden).expect("hide backend");
        let started = Instant::now();
        let result = start_project_services(&state, &config, &progress);
        fs::rename(&hidden, &backend).expect("restore backend");
        let _ = stop_configured_services(&state, &config);
        println!("broken start: {:?} after {:?}", result, started.elapsed());
        let error = result.expect_err("start without backend must fail");
        assert!(error.contains("服务进程已退出"));
        assert!(error.contains("完整日志"));
        assert!(started.elapsed() < SERVICE_START_TIMEOUT);
    }

    #[test]
    fn stopping_empty_service_state_is_ok() {
        let state = ServiceState::new();

        assert!(stop_project_services(&state).is_ok());
    }

    #[test]
    fn endpoint_listening_detects_open_local_port() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind test listener");
        let port = listener.local_addr().expect("read listener address").port();

        assert!(endpoint_listening("127.0.0.1", port));
    }

    #[test]
    fn resolve_available_ports_keeps_free_config_unchanged() {
        let mut config = config();
        config.api_port = unused_local_port();
        config.web_port = unused_local_port();

        let (resolved, messages) = resolve_available_ports(&config);

        assert_eq!(resolved, config);
        assert!(messages.is_empty());
    }

    #[test]
    fn resolve_available_ports_moves_away_from_unrelated_listener() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind test listener");
        let occupied_port = listener.local_addr().expect("read listener address").port();
        let mut config = config();
        config.web_port = occupied_port;

        let (resolved, messages) = resolve_available_ports(&config);

        assert_ne!(resolved.web_port, occupied_port);
        assert!(!endpoint_listening("127.0.0.1", resolved.web_port));
        assert_eq!(resolved.api_port, config.api_port);
        assert!(messages
            .iter()
            .any(|message| message.contains(&format!("网页端口 {occupied_port} 被占用"))));
    }

    #[test]
    fn resolve_available_ports_ignores_the_unused_api_port() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind test listener");
        let mut config = config();
        config.api_port = listener.local_addr().expect("read listener address").port();
        config.web_port = unused_local_port();

        let (resolved, messages) = resolve_available_ports(&config);

        assert_eq!(resolved, config);
        assert!(messages.is_empty());
    }

    #[test]
    fn project_service_command_matches_configured_api_port() {
        let command =
            "/repo/.venv/bin/python /repo/.venv/bin/uvicorn course_navigator.app:app --port 8100";

        assert!(is_project_service_command_with_cwd(
            command,
            None,
            &config(),
            8100
        ));
    }

    #[test]
    fn project_service_command_matches_app_on_web_port() {
        let command = "uv run --frozen uvicorn course_navigator.app:app --app-dir backend --host 127.0.0.1 --port 5188";

        assert!(is_project_service_command_with_cwd(
            command,
            Some("/repo"),
            &config(),
            5188
        ));
    }

    #[test]
    fn project_service_command_matches_configured_vite_port() {
        let command = "node /repo/node_modules/.bin/vite --host 127.0.0.1 --port 5188";

        assert!(is_project_service_command_with_cwd(
            command,
            None,
            &config(),
            5188
        ));
    }

    #[test]
    fn project_service_command_matches_npm_dev_parent() {
        let command = "npm run dev --port 5188 --host 127.0.0.1";

        assert!(is_project_service_command_with_cwd(
            command,
            Some("/repo"),
            &config(),
            5188
        ));
    }

    #[test]
    fn project_service_command_matches_uvicorn_parent() {
        let command = "uv run uvicorn course_navigator.app:app --app-dir backend --host 127.0.0.1 --port 8100";

        assert!(is_project_service_command_with_cwd(
            command,
            Some("/repo"),
            &config(),
            8100
        ));
    }

    #[test]
    fn project_service_command_rejects_unrelated_port_owner() {
        let command = "/usr/bin/python -m http.server 8100";

        assert!(!is_project_service_command_with_cwd(
            command,
            Some("/repo"),
            &config(),
            8100
        ));
    }

    #[test]
    fn project_service_command_rejects_unrelated_project_root_listener() {
        let command = "/repo/.venv/bin/python -m http.server 8100";

        assert!(!is_project_service_command_with_cwd(
            command,
            None,
            &config(),
            8100
        ));
    }

    #[test]
    fn project_service_command_rejects_matching_vite_port_from_other_project() {
        let command = "npm run dev --port 5188 --host 127.0.0.1";

        assert!(!is_project_service_command_with_cwd(
            command,
            Some("/other-project"),
            &config(),
            5188
        ));
    }

    #[test]
    #[cfg(not(windows))]
    fn lsof_cwd_parser_extracts_name_line() {
        let raw = "p12345\nn/Users/example/Course Navigator\n";

        assert_eq!(
            parse_lsof_cwd(raw),
            Some("/Users/example/Course Navigator".to_string())
        );
    }

    #[test]
    #[cfg(target_os = "macos")]
    fn macos_bundled_tools_root_uses_app_resources_dir() {
        let exe = Path::new("/Applications/Course Navigator.app/Contents/MacOS/Course Navigator");

        assert_eq!(
            bundled_tools_root_from_exe(exe, "darwin-arm64"),
            Some(PathBuf::from(
                "/Applications/Course Navigator.app/Contents/Resources/runtime-tools/darwin-arm64"
            ))
        );
    }

    #[test]
    #[cfg(target_os = "macos")]
    fn macos_tool_path_entries_include_portable_tool_bins() {
        let root = Path::new(
            "/Applications/Course Navigator.app/Contents/Resources/runtime-tools/darwin-arm64",
        );

        assert_eq!(
            tool_path_entries_from_root(root),
            vec![
                root.join("node").join("bin"),
                root.join("uv"),
                root.join("ffmpeg"),
            ]
        );
    }

    #[test]
    #[cfg(not(windows))]
    fn service_command_starts_in_separate_process_group() {
        if !command_exists("python3") {
            return;
        }

        let mut child = service_command("python3")
            .args(["-c", "import time; time.sleep(5)"])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("spawn isolated child");

        let child_pgid = process_group_id(child.id()).expect("child pgid");
        let current_pgid = process_group_id(std::process::id()).expect("current pgid");

        assert_ne!(child_pgid, current_pgid);
        let _ = stop_process_group(child_pgid, StopSignal::Kill);
        let _ = child.wait();
    }

    #[test]
    #[cfg(not(windows))]
    fn service_group_target_skips_current_launcher_group() {
        let mut groups = HashSet::new();

        insert_service_group(&mut groups, 42, Some(42));

        assert!(groups.is_empty());

        insert_service_group(&mut groups, 43, Some(42));

        assert!(groups.contains(&43));
    }

    #[test]
    #[cfg(not(windows))]
    fn stop_configured_services_kills_project_listener_group() {
        if !command_exists("python3") {
            return;
        }

        let probe = TcpListener::bind("127.0.0.1:0").expect("bind probe listener");
        let port = probe
            .local_addr()
            .expect("read probe listener address")
            .port();
        drop(probe);

        let project_root = std::env::current_dir().expect("read current dir");
        let script = format!(
            "import os, socket, time; os.setsid(); s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(('127.0.0.1', {port})); s.listen(); time.sleep(60)"
        );
        let mut child = Command::new("python3")
            .args([
                "-c",
                &script,
                "course_navigator.app:app",
                "--port",
                &port.to_string(),
            ])
            .current_dir(&project_root)
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("spawn listener");

        for _ in 0..50 {
            if endpoint_listening("127.0.0.1", port) {
                break;
            }
            thread::sleep(Duration::from_millis(50));
        }
        assert!(endpoint_listening("127.0.0.1", port));

        let state = ServiceState::new();
        let mut config = config();
        config.project_root = project_root.to_string_lossy().to_string();
        config.api_port = port;

        assert!(stop_configured_services(&state, &config).expect("stop listener"));
        assert!(!endpoint_listening("127.0.0.1", port));
        let _ = child.wait();
    }

    #[test]
    #[cfg(not(windows))]
    fn launchctl_parser_matches_course_jobs_for_parent_processes() {
        let mut groups = HashSet::new();
        groups.insert(57574);
        groups.insert(57576);
        let direct_pids = HashSet::new();
        let raw = "\
57574\t-15\tcourse-navigator-web-1777838763
57576\t143\tcourse-navigator-api-1777838763
-\t0\tcom.apple.unrelated
12345\t0\tother-course-navigator-web
";

        let labels = parse_launchctl_list(raw, &groups, &direct_pids);

        assert_eq!(
            labels,
            vec![
                "course-navigator-web-1777838763".to_string(),
                "course-navigator-api-1777838763".to_string(),
            ]
        );
    }

    #[test]
    #[cfg(not(windows))]
    fn project_setup_commands_install_missing_python_dependencies_only() {
        let root = temp_project_dir("setup-missing");
        std::fs::write(root.join("package-lock.json"), "{}").expect("package lock");

        let commands = project_setup_commands(&root);

        assert_eq!(
            commands,
            vec![RuntimeCommand {
                program: LOGIN_SHELL_PATH.into(),
                args: vec!["-lic".into(), "uv sync --frozen".into()],
            }]
        );
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    #[cfg(windows)]
    fn windows_project_setup_commands_use_native_programs() {
        let root = temp_project_dir("setup-windows-missing");
        std::fs::write(root.join("package-lock.json"), "{}").expect("package lock");

        let commands = project_setup_commands(&root);

        // The web pages ship prebuilt; npm is never needed at runtime.
        assert_eq!(
            commands,
            vec![RuntimeCommand {
                program: "uv".into(),
                args: vec!["sync".into(), "--frozen".into()],
            }]
        );
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    #[cfg(windows)]
    fn windows_taskkill_uses_force_for_managed_service_trees() {
        let args = windows_taskkill_args(47548, StopSignal::Term);

        assert!(args.iter().any(|arg| arg == "/T"));
        assert!(args.iter().any(|arg| arg == "/F"));
    }

    #[test]
    fn legacy_tool_files_are_removed_but_media_tools_stay() {
        let root = temp_project_dir("legacy-tools");
        for dir in LEGACY_TOOL_DIRS {
            std::fs::create_dir_all(root.join(dir).join("leftover")).expect("legacy dir");
        }
        std::fs::create_dir_all(root.join("ffmpeg")).expect("ffmpeg dir");
        std::fs::write(root.join("ffmpeg/ffmpeg.exe"), "ffmpeg").expect("ffmpeg");

        remove_legacy_tool_files_in(&root);

        assert!(LEGACY_TOOL_DIRS.iter().all(|dir| !root.join(dir).exists()));
        assert!(root.join("ffmpeg/ffmpeg.exe").exists());
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn media_tools_require_ffmpeg_and_ffprobe() {
        assert!(media_tools_are_available(|_| true));
        assert!(!media_tools_are_available(|name| name == "ffmpeg"));
        assert!(!media_tools_are_available(|name| name == "ffprobe"));
    }

    #[test]
    fn dependency_labels_describe_tool_purpose_without_install_copy() {
        let dependencies = check_dependencies(Path::new("."));
        let media = dependencies
            .iter()
            .find(|dependency| dependency.name == "ffmpeg / ffprobe")
            .expect("media dependency row");
        let ytdlp = dependencies
            .iter()
            .find(|dependency| dependency.name == "yt-dlp")
            .expect("yt-dlp dependency row");

        assert!(!media.purpose.contains("稍后安装"));
        assert!(!media.purpose.contains("版本"));
        assert!(!media.purpose.contains("内置"));
        assert!(media.purpose.contains("读取视频信息"));
        assert!(ytdlp.purpose.contains("提取在线视频"));
        assert!(dependencies
            .iter()
            .all(|dependency| !dependency.purpose.contains("启动")));
        assert!(dependencies
            .iter()
            .all(|dependency| !dependency.purpose.contains("准备")));
        assert!(dependencies
            .iter()
            .all(|dependency| dependency.name != "node" && dependency.name != "npm"));
    }

    #[test]
    #[cfg(windows)]
    fn stop_child_terminates_windows_child_processes() {
        let root = temp_project_dir("stop-windows-tree");
        let pid_file = root.join("child.pid");
        let script = format!(
            "$child = Start-Process -FilePath powershell -ArgumentList '-NoProfile','-Command','Start-Sleep -Seconds 60' -PassThru; Set-Content -Path {} -Value $child.Id; Start-Sleep -Seconds 60",
            powershell_single_quoted_path(&pid_file)
        );
        let parent = hidden_command("powershell")
            .args(["-NoProfile", "-Command", &script])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("spawn parent service process");

        for _ in 0..50 {
            if pid_file.exists() {
                break;
            }
            thread::sleep(Duration::from_millis(100));
        }
        let child_pid = std::fs::read_to_string(&pid_file)
            .expect("child pid file")
            .trim()
            .parse::<u32>()
            .expect("child pid");
        assert!(windows_process_exists(child_pid));

        stop_child(parent).expect("stop parent service tree");
        let child_stopped = wait_for_windows_process_exit(child_pid);
        if !child_stopped {
            let _ = stop_pid(child_pid, StopSignal::Kill);
        }

        assert!(child_stopped);
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn project_setup_commands_skip_existing_dependency_directories() {
        let root = temp_project_dir("setup-ready");
        std::fs::create_dir_all(root.join(".venv")).expect("venv");
        std::fs::create_dir_all(root.join("node_modules")).expect("node modules");
        std::fs::write(root.join("pyproject.toml"), "[project]\n").expect("pyproject");
        std::fs::write(root.join("uv.lock"), "uv").expect("uv lock");
        std::fs::write(root.join("package.json"), "{}").expect("package");
        std::fs::write(root.join("package-lock.json"), "{}").expect("package lock");
        write_dependency_marker(&root).expect("marker");

        assert!(project_setup_commands(&root).is_empty());
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn project_setup_commands_rerun_when_lockfiles_change() {
        let root = temp_project_dir("setup-stale");
        std::fs::create_dir_all(root.join(".venv")).expect("venv");
        std::fs::create_dir_all(root.join("node_modules")).expect("node modules");
        std::fs::write(root.join("pyproject.toml"), "[project]\n").expect("pyproject");
        std::fs::write(root.join("uv.lock"), "uv-v1").expect("uv lock");
        std::fs::write(root.join("package.json"), "{}").expect("package");
        std::fs::write(root.join("package-lock.json"), "{\"version\":1}").expect("package lock");
        write_dependency_marker(&root).expect("marker");

        std::fs::write(root.join("package-lock.json"), "{\"version\":2}")
            .expect("update package lock");
        assert!(project_setup_commands(&root).is_empty());

        std::fs::write(root.join("uv.lock"), "uv-v2").expect("update uv lock");
        let commands = project_setup_commands(&root);

        assert_eq!(commands.len(), 1);
        assert_eq!(commands[0], setup_uv_command());
        let _ = std::fs::remove_dir_all(root);
    }

    /// A project with one model profile and one cached audio file.
    fn project_with_cached_audio(label: &str) -> (std::path::PathBuf, std::path::PathBuf) {
        let root = temp_project_dir(label);
        std::fs::write(
            root.join(".env"),
            r#"COURSE_NAVIGATOR_MODEL_PROFILES="[{\"id\":\"default\",\"name\":\"Test\",\"provider_type\":\"openai\",\"base_url\":\"https://api.example.com/v1\",\"model\":\"test\",\"api_key\":\"sk-test\"}]"
"#,
        )
        .expect("write project env");
        let audio = root.join(".course-navigator/subtitles/item/audio.mp3");
        std::fs::create_dir_all(audio.parent().expect("audio dir")).expect("create cache dir");
        std::fs::write(&audio, b"audio").expect("write cached audio");
        (root, audio)
    }

    fn temp_project_dir(label: &str) -> std::path::PathBuf {        let root = std::env::temp_dir().join(format!(
            "course-navigator-runtime-{label}-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("time")
                .as_nanos()
        ));
        std::fs::create_dir_all(&root).expect("temp project");
        root
    }

    #[cfg(windows)]
    fn powershell_single_quoted_path(path: &Path) -> String {
        format!("'{}'", path.to_string_lossy().replace('\'', "''"))
    }

    #[cfg(windows)]
    fn windows_process_exists(pid: u32) -> bool {
        let script =
            format!("if (Get-Process -Id {pid} -ErrorAction SilentlyContinue) {{ exit 0 }} else {{ exit 1 }}");
        hidden_command("powershell")
            .args(["-NoProfile", "-Command", &script])
            .status()
            .is_ok_and(|status| status.success())
    }

    #[cfg(windows)]
    fn wait_for_windows_process_exit(pid: u32) -> bool {
        for _ in 0..50 {
            if !windows_process_exists(pid) {
                return true;
            }
            thread::sleep(Duration::from_millis(100));
        }
        false
    }
}
