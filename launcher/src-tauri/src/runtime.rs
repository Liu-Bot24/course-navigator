use std::collections::HashSet;
use std::net::{TcpStream, ToSocketAddrs};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use serde::Serialize;

use crate::models::LauncherConfig;

const KILL_PATH: &str = "/bin/kill";
const LAUNCHCTL_PATH: &str = "/bin/launchctl";
const LSOF_PATH: &str = "/usr/sbin/lsof";
const LOGIN_SHELL_PATH: &str = "/bin/zsh";
const PS_PATH: &str = "/bin/ps";

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
    endpoint_listening(&config.api_host, config.api_port)
        && endpoint_listening(&config.web_host, config.web_port)
}

pub fn any_configured_service_listening(config: &LauncherConfig) -> bool {
    endpoint_listening(&config.api_host, config.api_port)
        || endpoint_listening(&config.web_host, config.web_port)
}

pub fn owns_services(state: &ServiceState) -> bool {
    let api_owned = state.api.lock().map(|api| api.is_some()).unwrap_or(false);
    let web_owned = state.web.lock().map(|web| web.is_some()).unwrap_or(false);
    api_owned || web_owned
}

pub fn api_command(config: &LauncherConfig) -> RuntimeCommand {
    RuntimeCommand {
        program: LOGIN_SHELL_PATH.into(),
        args: vec!["-lic".into(), format!("exec uv run uvicorn course_navigator.app:app --app-dir backend --host {} --port {}", shell_quote(&config.api_host), config.api_port)],
    }
}

pub fn web_command(config: &LauncherConfig) -> RuntimeCommand {
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

pub fn check_dependencies() -> Vec<DependencyStatus> {
    [
        ("node", "运行前端开发服务"),
        ("npm", "安装和启动前端依赖"),
        ("uv", "安装和启动 Python 后端"),
        ("ffmpeg", "本地视频缓存、音频提取和媒体转换"),
        ("yt-dlp", "在线课程字幕提取和视频缓存"),
    ]
    .into_iter()
    .map(|(name, purpose)| DependencyStatus {
        name: name.into(),
        available: command_exists(name),
        purpose: purpose.into(),
    })
    .collect()
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

    let api = api_command(config);
    let web = web_command(config);

    let api_child = service_command(&api.program)
        .args(&api.args)
        .current_dir(project_root)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|error| format!("API 启动失败: {error}"))?;

    let web_child = match service_command(&web.program)
        .args(&web.args)
        .current_dir(project_root)
        .env("COURSE_NAVIGATOR_API_HOST", &config.api_host)
        .env("COURSE_NAVIGATOR_API_PORT", config.api_port.to_string())
        .env("COURSE_NAVIGATOR_WEB_HOST", &config.web_host)
        .env("COURSE_NAVIGATOR_WEB_PORT", config.web_port.to_string())
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
            if is_project_service_command(&command, config, port) {
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

fn insert_service_group(groups: &mut HashSet<u32>, pgid: u32, current_pgid: Option<u32>) {
    if Some(pgid) != current_pgid {
        groups.insert(pgid);
    }
}

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

fn process_command(pid: u32) -> String {
    let Ok(output) = Command::new(PS_PATH)
        .args(["-p", &pid.to_string(), "-o", "command="])
        .output()
    else {
        return String::new();
    };
    String::from_utf8_lossy(&output.stdout).trim().to_string()
}

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

fn is_project_service_command(command: &str, config: &LauncherConfig, port: u16) -> bool {
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

fn command_contains_port(command: &str, port: u16) -> bool {
    let port = port.to_string();
    command.split_whitespace().any(|part| {
        part == port || part == format!("--port={port}") || part.ends_with(&format!(":{port}"))
    })
}

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

fn command_exists(name: &str) -> bool {
    Command::new(LOGIN_SHELL_PATH)
        .arg("-lic")
        .arg(format!("command -v {name} >/dev/null 2>&1"))
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
}

fn service_command(program: &str) -> Command {
    let mut command = Command::new(program);
    set_service_process_group(&mut command);
    command
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

    #[test]
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
    fn web_command_uses_configured_port() {
        let command = web_command(&config());
        assert_eq!(command.program, LOGIN_SHELL_PATH);
        assert!(command.args.iter().any(|arg| arg.contains("npm run dev")));
        assert!(command.args.iter().any(|arg| arg.contains("--port 5188")));
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
    fn project_service_command_matches_configured_api_port() {
        let command =
            "/repo/.venv/bin/python /repo/.venv/bin/uvicorn course_navigator.app:app --port 8100";

        assert!(is_project_service_command(command, &config(), 8100));
    }

    #[test]
    fn project_service_command_matches_configured_vite_port() {
        let command = "node /repo/node_modules/.bin/vite --host 127.0.0.1 --port 5188";

        assert!(is_project_service_command(command, &config(), 5188));
    }

    #[test]
    fn project_service_command_matches_npm_dev_parent() {
        let command = "npm run dev --port 5188 --host 127.0.0.1";

        assert!(is_project_service_command(command, &config(), 5188));
    }

    #[test]
    fn project_service_command_matches_uvicorn_parent() {
        let command = "uv run uvicorn course_navigator.app:app --app-dir backend --host 127.0.0.1 --port 8100";

        assert!(is_project_service_command(command, &config(), 8100));
    }

    #[test]
    fn project_service_command_rejects_unrelated_port_owner() {
        let command = "/usr/bin/python -m http.server 8100";

        assert!(!is_project_service_command(command, &config(), 8100));
    }

    #[test]
    fn project_service_command_rejects_unrelated_project_root_listener() {
        let command = "/repo/.venv/bin/python -m http.server 8100";

        assert!(!is_project_service_command(command, &config(), 8100));
    }

    #[test]
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
    fn service_group_target_skips_current_launcher_group() {
        let mut groups = HashSet::new();

        insert_service_group(&mut groups, 42, Some(42));

        assert!(groups.is_empty());

        insert_service_group(&mut groups, 43, Some(42));

        assert!(groups.contains(&43));
    }

    #[test]
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
}
