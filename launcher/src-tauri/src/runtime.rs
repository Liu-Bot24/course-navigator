use std::collections::{hash_map::DefaultHasher, HashSet};
use std::env;
use std::fs;
use std::hash::{Hash, Hasher};
use std::io::{Read, Write};
use std::net::{TcpStream, ToSocketAddrs};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;
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
const CREATE_NO_WINDOW: u32 = 0x08000000;
const DEPENDENCY_MARKER_FILE: &str = ".course-navigator-deps.json";
const INSTALL_TARGET_MEDIA_TOOLS: &str = "media-tools";
#[cfg(windows)]
const FFMPEG_DOWNLOAD_URL: &str = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip";

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
    api: Mutex<Option<Child>>,
    web: Mutex<Option<Child>>,
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
            api: Mutex::new(None),
            web: Mutex::new(None),
        }
    }
}

pub fn configured_services_listening(config: &LauncherConfig) -> bool {
    course_api_ready(config) && course_web_ready(config)
}

pub fn any_configured_service_listening(config: &LauncherConfig) -> bool {
    endpoint_listening(&config.api_host, config.api_port)
        || endpoint_listening(&config.web_host, config.web_port)
}

pub fn resolve_available_ports(config: &LauncherConfig) -> (LauncherConfig, Vec<String>) {
    if configured_services_listening(config) {
        return (config.clone(), Vec::new());
    }

    let mut next = config.clone();
    let mut messages = Vec::new();
    if endpoint_listening(&config.api_host, config.api_port) && !course_api_ready(config) {
        if let Some(port) = first_available_port(&config.api_host, config.api_port) {
            messages.push(format!("API 端口 {} 被占用，已改用 {port}", config.api_port));
            next.api_port = port;
        }
    }
    if endpoint_listening(&config.web_host, config.web_port) && !course_web_ready(config) {
        if let Some(port) = first_available_port(&config.web_host, config.web_port) {
            messages.push(format!("网页端口 {} 被占用，已改用 {port}", config.web_port));
            next.web_port = port;
        }
    }
    if next.api_host == next.web_host && next.api_port == next.web_port {
        if let Some(port) = first_available_port(&next.web_host, next.web_port) {
            messages.push(format!("网页端口与 API 端口冲突，已改用 {port}"));
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
    let api_owned = state.api.lock().map(|api| api.is_some()).unwrap_or(false);
    let web_owned = state.web.lock().map(|web| web.is_some()).unwrap_or(false);
    api_owned || web_owned
}

pub fn api_command(config: &LauncherConfig) -> RuntimeCommand {
    if cfg!(windows) {
        RuntimeCommand {
            program: "uv".into(),
            args: vec![
                "run".into(),
                "uvicorn".into(),
                "course_navigator.app:app".into(),
                "--app-dir".into(),
                "backend".into(),
                "--host".into(),
                config.api_host.clone(),
                "--port".into(),
                config.api_port.to_string(),
            ],
        }
    } else {
        RuntimeCommand {
            program: LOGIN_SHELL_PATH.into(),
            args: vec!["-lic".into(), format!("exec uv run uvicorn course_navigator.app:app --app-dir backend --host {} --port {}", shell_quote(&config.api_host), config.api_port)],
        }
    }
}

pub fn web_command(config: &LauncherConfig) -> RuntimeCommand {
    if cfg!(windows) {
        RuntimeCommand {
            program: "npm.cmd".into(),
            args: vec![
                "run".into(),
                "dev".into(),
                "--".into(),
                "--host".into(),
                config.web_host.clone(),
                "--port".into(),
                config.web_port.to_string(),
            ],
        }
    } else {
        RuntimeCommand {
            program: LOGIN_SHELL_PATH.into(),
            args: vec![
                "-lic".into(),
                format!(
                    "exec npm run dev -- --host {} --port {}",
                    shell_quote(&config.web_host),
                    config.web_port
                ),
            ],
        }
    }
}

pub fn check_dependencies(project_root: &Path) -> Vec<DependencyStatus> {
    vec![
        DependencyStatus {
            name: "node".into(),
            available: command_exists("node")
                && node_version().is_some_and(|version| node_version_supported(&version)),
            purpose: "显示学习网页界面".into(),
            install_target: None,
            install_label: None,
        },
        DependencyStatus {
            name: "npm".into(),
            available: command_exists("npm"),
            purpose: "加载网页所需资源".into(),
            install_target: None,
            install_label: None,
        },
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
                Some(if media_tools_available() { "更新" } else { "准备" }.into())
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

fn prepare_preferred_windows_tools() {
    #[cfg(windows)]
    {
        let _ = prepare_latest_windows_tools();
    }
}

#[cfg(windows)]
fn prepare_latest_windows_tools() -> Result<(), String> {
    let mut errors = Vec::new();
    if windows_tool_program("ffmpeg").is_none()
        || windows_tool_program("ffprobe").is_none()
    {
        if let Err(error) = download_latest_media_tools() {
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
fn download_latest_media_tools() -> Result<(), String> {
    let target_dir = installed_windows_tools_root().join("ffmpeg");
    let temp_root = installed_windows_tools_root()
        .join(".tmp")
        .join(unique_temp_name("ffmpeg"));
    let zip_path = temp_root.join("ffmpeg-release-essentials.zip");
    let extract_dir = temp_root.join("extract");
    fs::create_dir_all(&target_dir).map_err(|error| format!("无法创建媒体工具目录: {error}"))?;
    fs::create_dir_all(&extract_dir).map_err(|error| format!("无法创建媒体工具临时目录: {error}"))?;

    let url = env::var("COURSE_NAVIGATOR_WINDOWS_FFMPEG_URL")
        .unwrap_or_else(|_| FFMPEG_DOWNLOAD_URL.to_string());
    let result = download_file_with_powershell(&url, &zip_path)
        .and_then(|()| expand_archive_with_powershell(&zip_path, &extract_dir))
        .and_then(|()| copy_media_tools_from_archive(&extract_dir, &target_dir));
    let _ = fs::remove_dir_all(&temp_root);
    result
}

#[cfg(windows)]
fn download_file_with_powershell(url: &str, target: &Path) -> Result<(), String> {
    let script = format!(
        "$ErrorActionPreference = 'Stop'; New-Item -ItemType Directory -Force -Path (Split-Path -Parent {target}) | Out-Null; Invoke-WebRequest -UseBasicParsing -Uri {url} -OutFile {target}",
        url = powershell_quote(url),
        target = powershell_quote_path(target),
    );
    run_powershell_script(&script, "下载运行工具失败")
}

#[cfg(windows)]
fn expand_archive_with_powershell(zip_path: &Path, destination: &Path) -> Result<(), String> {
    let script = format!(
        "$ErrorActionPreference = 'Stop'; Expand-Archive -LiteralPath {zip_path} -DestinationPath {destination} -Force",
        zip_path = powershell_quote_path(zip_path),
        destination = powershell_quote_path(destination),
    );
    run_powershell_script(&script, "解压运行工具失败")
}

#[cfg(windows)]
fn copy_media_tools_from_archive(source: &Path, target: &Path) -> Result<(), String> {
    let script = format!(
        "$ErrorActionPreference = 'Stop'; $source = {source}; $target = {target}; $ffmpeg = Get-ChildItem -Path $source -Recurse -Filter 'ffmpeg.exe' | Select-Object -First 1; $ffprobe = Get-ChildItem -Path $source -Recurse -Filter 'ffprobe.exe' | Select-Object -First 1; if (-not $ffmpeg -or -not $ffprobe) {{ throw '下载的 ffmpeg 包缺少 ffmpeg.exe 或 ffprobe.exe' }}; New-Item -ItemType Directory -Force -Path $target | Out-Null; Copy-Item -LiteralPath $ffmpeg.FullName -Destination (Join-Path $target 'ffmpeg.exe') -Force; Copy-Item -LiteralPath $ffprobe.FullName -Destination (Join-Path $target 'ffprobe.exe') -Force",
        source = powershell_quote_path(source),
        target = powershell_quote_path(target),
    );
    run_powershell_script(&script, "安装媒体工具失败")
}

#[cfg(windows)]
fn run_powershell_script(script: &str, context: &str) -> Result<(), String> {
    let output = hidden_command("powershell")
        .args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script])
        .output()
        .map_err(|error| format!("{context}: {error}"))?;
    if output.status.success() {
        Ok(())
    } else {
        Err(format!(
            "{context}: {}",
            command_failure_summary(
                &String::from_utf8_lossy(&output.stderr),
                &String::from_utf8_lossy(&output.stdout)
            )
        ))
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

pub fn start_project_services(state: &ServiceState, config: &LauncherConfig) -> Result<(), String> {
    let project_root = std::path::Path::new(&config.project_root);
    if !project_root.exists() {
        return Err(format!("项目目录不存在: {}", config.project_root));
    }

    {
        let api = state.api.lock().map_err(|_| "API 状态锁失效".to_string())?;
        let web = state.web.lock().map_err(|_| "Web 状态锁失效".to_string())?;
        if api.is_some() || web.is_some() {
            return Err("服务已经由 Launcher 启动".to_string());
        }
    }

    if configured_services_listening(config) {
        return Ok(());
    }
    if any_configured_service_listening(config) {
        return Err(
            "检测到 API 或网页端口已被占用，但服务不完整；请先停止旧服务或换端口。".to_string(),
        );
    }
    ensure_project_dependencies(project_root)?;

    let api = api_command(config);
    let web = web_command(config);

    let mut api_command = service_command(&api.program);
    apply_service_env(&mut api_command, config);
    let api_child = api_command
        .args(&api.args)
        .current_dir(project_root)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|error| format!("API 启动失败: {error}"))?;

    let mut web_command = service_command(&web.program);
    apply_service_env(&mut web_command, config);
    let web_child = match web_command
        .args(&web.args)
        .current_dir(project_root)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
    {
        Ok(child) => child,
        Err(error) => {
            let _ = stop_child(api_child);
            return Err(format!("Web 启动失败: {error}"));
        }
    };

    *state.api.lock().map_err(|_| "API 状态锁失效".to_string())? = Some(api_child);
    *state.web.lock().map_err(|_| "Web 状态锁失效".to_string())? = Some(web_child);
    if wait_for_configured_services_to_start(config).is_err() {
        let _ = stop_configured_services(state, config);
        return Err(
            "服务已启动命令，但端口没有按预期响应；请确认 uv、npm 和项目依赖可用。".to_string(),
        );
    }
    Ok(())
}

fn apply_service_env(command: &mut Command, config: &LauncherConfig) {
    command
        .env("COURSE_NAVIGATOR_API_HOST", &config.api_host)
        .env("COURSE_NAVIGATOR_API_PORT", config.api_port.to_string())
        .env("COURSE_NAVIGATOR_WEB_HOST", &config.web_host)
        .env("COURSE_NAVIGATOR_WEB_PORT", config.web_port.to_string())
        .env("COURSE_NAVIGATOR_WORKSPACE_DIR", &config.workspace_dir);
}

pub fn stop_project_services(state: &ServiceState) -> Result<(), String> {
    if let Some(child) = state
        .api
        .lock()
        .map_err(|_| "API 状态锁失效".to_string())?
        .take()
    {
        stop_child(child)?;
    }
    if let Some(child) = state
        .web
        .lock()
        .map_err(|_| "Web 状态锁失效".to_string())?
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

fn wait_for_configured_services_to_start(config: &LauncherConfig) -> Result<(), String> {
    for _ in 0..80 {
        if configured_services_listening(config) {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(150));
    }
    Err("端口未按预期启动".to_string())
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

#[cfg(windows)]
fn listening_pids(port: u16) -> Vec<u32> {
    let script = format!(
        "Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess"
    );
    let Ok(output) = hidden_command("powershell")
        .args(["-NoProfile", "-Command", &script])
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
    if port == config.api_port
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
    if command.contains(root) {
        return true;
    }
    let root_path = Path::new(root);
    cwd.is_some_and(|cwd| {
        let cwd_path = Path::new(cwd);
        cwd_path == root_path || cwd_path.starts_with(root_path)
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
    if windows_tool_program(name).is_some() {
        return true;
    }
    if cfg!(windows) {
        hidden_command("cmd")
            .args(["/C", "where", windows_command_name(name)])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map(|status| status.success())
            .unwrap_or(false)
    } else {
        hidden_command(LOGIN_SHELL_PATH)
            .arg("-lic")
            .arg(format!("command -v {name} >/dev/null 2>&1"))
            .status()
            .map(|status| status.success())
            .unwrap_or(false)
    }
}

fn ensure_project_dependencies(project_root: &Path) -> Result<(), String> {
    let missing_commands = ["node", "npm", "uv"]
        .into_iter()
        .filter(|name| !command_exists(name))
        .collect::<Vec<_>>();
    if !missing_commands.is_empty() {
        return Err(format!(
            "缺少运行依赖: {}。请安装后再启动。",
            missing_commands.join(", ")
        ));
    }
    ensure_supported_node_version()?;
    prepare_preferred_windows_tools();

    for command in project_setup_commands(project_root) {
        run_setup_command(project_root, &command)?;
    }
    write_dependency_marker(project_root)?;
    Ok(())
}

fn project_setup_commands(project_root: &Path) -> Vec<RuntimeCommand> {
    let mut commands = Vec::new();
    let python_fingerprint = dependency_fingerprint(project_root, &["pyproject.toml", "uv.lock"]);
    let node_fingerprint =
        dependency_fingerprint(project_root, &["package.json", "package-lock.json"]);
    if !project_root.join(".venv").exists()
        || !dependency_marker_matches(project_root, "python", &python_fingerprint)
    {
        commands.push(setup_uv_command());
    }
    if !project_root.join("node_modules").exists()
        || !dependency_marker_matches(project_root, "node", &node_fingerprint)
    {
        commands.push(setup_npm_command(project_root));
    }
    commands
}

fn setup_uv_command() -> RuntimeCommand {
    if cfg!(windows) {
        RuntimeCommand {
            program: "uv".into(),
            args: vec!["sync".into()],
        }
    } else {
        RuntimeCommand {
            program: LOGIN_SHELL_PATH.into(),
            args: vec!["-lic".into(), "uv sync".into()],
        }
    }
}

fn setup_npm_command(project_root: &Path) -> RuntimeCommand {
    let subcommand = if project_root.join("package-lock.json").exists() {
        "ci"
    } else {
        "install"
    };
    if cfg!(windows) {
        RuntimeCommand {
            program: "npm.cmd".into(),
            args: vec![subcommand.into()],
        }
    } else {
        RuntimeCommand {
            program: LOGIN_SHELL_PATH.into(),
            args: vec![
                "-lic".into(),
                "if [ -f package-lock.json ]; then npm ci; else npm install; fi".into(),
            ],
        }
    }
}

fn ensure_supported_node_version() -> Result<(), String> {
    let Some(version) = node_version() else {
        return Err(
            "无法读取 Node.js 版本。请安装 Node.js 20.19+（20 系列）或 22.12+（22 及更新版本）。"
                .into(),
        );
    };
    if node_version_supported(&version) {
        Ok(())
    } else {
        Err(format!(
            "Node.js 版本过低: {version}。请安装 Node.js 20.19+（20 系列）或 22.12+（22 及更新版本）。"
        ))
    }
}

fn node_version() -> Option<String> {
    let mut command = if cfg!(windows) {
        let mut command = hidden_command("node");
        command.args(["-p", "process.versions.node"]);
        command
    } else {
        let mut command = hidden_command(LOGIN_SHELL_PATH);
        command.args(["-lic", "node -p \"process.versions.node\""]);
        command
    };
    let output = command.output().ok()?;
    if !output.status.success() {
        return None;
    }
    let version = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if version.is_empty() {
        None
    } else {
        Some(version)
    }
}

fn windows_command_name(name: &str) -> &str {
    match name {
        "npm" => "npm.cmd",
        "uv" => "uv.exe",
        "ffmpeg" => "ffmpeg.exe",
        "ffprobe" => "ffprobe.exe",
        other => other,
    }
}

fn node_version_supported(version: &str) -> bool {
    let parts = version
        .trim_start_matches('v')
        .split('.')
        .filter_map(|part| part.parse::<u32>().ok())
        .collect::<Vec<_>>();
    let [major, minor, ..] = parts.as_slice() else {
        return false;
    };
    (*major == 20 && *minor >= 19) || (*major == 22 && *minor >= 12) || *major > 22
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
        "node": dependency_fingerprint(project_root, &["package.json", "package-lock.json"]),
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

fn run_setup_command(project_root: &Path, command: &RuntimeCommand) -> Result<(), String> {
    let output = hidden_command(&command.program)
        .args(&command.args)
        .current_dir(project_root)
        .output()
        .map_err(|error| format!("准备运行依赖失败: {error}"))?;
    if output.status.success() {
        return Ok(());
    }
    let stderr = String::from_utf8_lossy(&output.stderr);
    let stdout = String::from_utf8_lossy(&output.stdout);
    Err(format!(
        "准备运行依赖失败: {}",
        command_failure_summary(&stderr, &stdout)
    ))
}

fn command_failure_summary(stderr: &str, stdout: &str) -> String {
    let summary = stderr
        .lines()
        .chain(stdout.lines())
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .rev()
        .take(6)
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
        .collect::<Vec<_>>()
        .join("\n");
    if summary.is_empty() {
        "命令没有返回错误详情".to_string()
    } else {
        summary
    }
}

fn service_command(program: &str) -> Command {
    let mut command = hidden_command(program);
    set_service_process_group(&mut command);
    command
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
    let tool_paths = windows_tool_paths();
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

#[cfg(windows)]
fn windows_tool_paths() -> Vec<PathBuf> {
    let mut roots = Vec::new();
    if let Some(root) = bundled_windows_tools_root() {
        roots.push(root);
    }
    roots.push(installed_windows_tools_root());
    ["node", "uv", "ffmpeg"]
        .into_iter()
        .flat_map(|name| roots.iter().map(move |root| root.join(name)))
        .filter(|path| path.exists())
        .collect()
}

#[cfg(not(windows))]
fn windows_tool_paths() -> Vec<PathBuf> {
    Vec::new()
}

#[cfg(windows)]
fn windows_tool_program(name: &str) -> Option<PathBuf> {
    let executable = windows_command_name(name);
    windows_tool_paths()
        .into_iter()
        .map(|dir| dir.join(executable))
        .find(|path| path.exists())
}

#[cfg(not(windows))]
fn windows_tool_program(_name: &str) -> Option<PathBuf> {
    None
}

#[cfg(windows)]
fn bundled_windows_tools_root() -> Option<PathBuf> {
    env::current_exe()
        .ok()?
        .parent()
        .map(|dir| dir.join("runtime-tools").join("windows"))
}

#[cfg(windows)]
fn installed_windows_tools_root() -> PathBuf {
    crate::config::application_support_dir()
        .join("runtime-tools")
        .join("windows")
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

pub fn endpoint_listening(host: &str, port: u16) -> bool {
    let Ok(addresses) = (host, port).to_socket_addrs() else {
        return false;
    };
    addresses
        .into_iter()
        .any(|address| TcpStream::connect_timeout(&address, Duration::from_millis(180)).is_ok())
}

fn course_api_ready(config: &LauncherConfig) -> bool {
    http_get(&config.api_host, config.api_port, "/api/health").is_some_and(|response| {
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

fn http_get(host: &str, port: u16, path: &str) -> Option<String> {
    let address = (host, port).to_socket_addrs().ok()?.next()?;
    let mut stream = TcpStream::connect_timeout(&address, Duration::from_millis(220)).ok()?;
    let _ = stream.set_read_timeout(Some(Duration::from_millis(600)));
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
    #[cfg(not(windows))]
    fn api_command_uses_configured_port() {
        let command = api_command(&config());
        assert_eq!(command.program, LOGIN_SHELL_PATH);
        assert!(command
            .args
            .iter()
            .any(|arg| arg.contains("uv run uvicorn")));
        assert!(command.args.iter().any(|arg| arg.contains("--port 8100")));
    }

    #[test]
    #[cfg(not(windows))]
    fn web_command_uses_configured_port() {
        let command = web_command(&config());
        assert_eq!(command.program, LOGIN_SHELL_PATH);
        assert!(command.args.iter().any(|arg| arg.contains("npm run dev")));
        assert!(command.args.iter().any(|arg| arg.contains("--port 5188")));
    }

    #[test]
    #[cfg(windows)]
    fn windows_runtime_commands_do_not_depend_on_unix_shell() {
        let api = api_command(&config());
        let web = web_command(&config());

        assert_ne!(api.program, LOGIN_SHELL_PATH);
        assert_eq!(api.program, "uv");
        assert_eq!(
            api.args,
            vec![
                "run",
                "uvicorn",
                "course_navigator.app:app",
                "--app-dir",
                "backend",
                "--host",
                "127.0.0.1",
                "--port",
                "8100"
            ]
        );
        assert_eq!(web.program, "npm.cmd");
        assert_eq!(
            web.args,
            vec!["run", "dev", "--", "--host", "127.0.0.1", "--port", "5188"]
        );
    }

    #[test]
    fn shell_quote_wraps_values_for_login_shell_commands() {
        assert_eq!(shell_quote("127.0.0.1"), "'127.0.0.1'");
        assert_eq!(shell_quote("can't"), "'can'\\''t'");
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
        config.api_port = occupied_port;
        config.web_port = unused_local_port();

        let (resolved, messages) = resolve_available_ports(&config);

        assert_ne!(resolved.api_port, occupied_port);
        assert!(!endpoint_listening("127.0.0.1", resolved.api_port));
        assert_ne!(resolved.api_port, resolved.web_port);
        assert!(!endpoint_listening("127.0.0.1", resolved.web_port));
        assert!(messages
            .iter()
            .any(|message| message.contains(&format!("API 端口 {occupied_port} 被占用"))));
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
    fn node_version_gate_matches_vite_requirement() {
        assert!(!node_version_supported("20.18.1"));
        assert!(node_version_supported("20.19.0"));
        assert!(!node_version_supported("21.7.0"));
        assert!(!node_version_supported("22.11.0"));
        assert!(node_version_supported("22.12.0"));
        assert!(node_version_supported("23.0.0"));
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
    fn project_setup_commands_install_missing_python_and_node_dependencies() {
        let root = temp_project_dir("setup-missing");
        std::fs::write(root.join("package-lock.json"), "{}").expect("package lock");

        let commands = project_setup_commands(&root);

        assert_eq!(
            commands,
            vec![
                RuntimeCommand {
                    program: LOGIN_SHELL_PATH.into(),
                    args: vec!["-lic".into(), "uv sync".into()],
                },
                RuntimeCommand {
                    program: LOGIN_SHELL_PATH.into(),
                    args: vec![
                        "-lic".into(),
                        "if [ -f package-lock.json ]; then npm ci; else npm install; fi".into()
                    ],
                },
            ]
        );
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    #[cfg(windows)]
    fn windows_project_setup_commands_use_native_programs() {
        let root = temp_project_dir("setup-windows-missing");
        std::fs::write(root.join("package-lock.json"), "{}").expect("package lock");

        let commands = project_setup_commands(&root);

        assert_eq!(
            commands,
            vec![
                RuntimeCommand {
                    program: "uv".into(),
                    args: vec!["sync".into()],
                },
                RuntimeCommand {
                    program: "npm.cmd".into(),
                    args: vec!["ci".into()],
                },
            ]
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
        assert!(dependencies.iter().all(|dependency| !dependency.purpose.contains("启动")));
        assert!(dependencies.iter().all(|dependency| !dependency.purpose.contains("准备")));
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

        std::fs::write(root.join("uv.lock"), "uv-v2").expect("update uv lock");
        std::fs::write(root.join("package-lock.json"), "{\"version\":2}")
            .expect("update package lock");

        let commands = project_setup_commands(&root);

        assert_eq!(commands.len(), 2);
        let expected_uv_arg = if cfg!(windows) { "sync" } else { "uv sync" };
        let expected_npm_arg = if cfg!(windows) { "ci" } else { "npm ci" };
        assert!(commands[0].args.iter().any(|arg| arg == expected_uv_arg));
        assert!(commands[1]
            .args
            .iter()
            .any(|arg| arg.contains(expected_npm_arg)));
        let _ = std::fs::remove_dir_all(root);
    }

    fn temp_project_dir(label: &str) -> std::path::PathBuf {
        let root = std::env::temp_dir().join(format!(
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
