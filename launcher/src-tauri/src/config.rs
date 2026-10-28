use std::collections::BTreeMap;
use std::ffi::OsStr;
use std::fs;
use std::path::{Path, PathBuf};

use crate::models::LauncherConfig;
use tauri::{path::BaseDirectory, AppHandle, Manager};

const MANAGED_ENV_KEYS: &[&str] = &[
    "COURSE_NAVIGATOR_API_HOST",
    "COURSE_NAVIGATOR_API_PORT",
    "COURSE_NAVIGATOR_WEB_HOST",
    "COURSE_NAVIGATOR_WEB_PORT",
    "COURSE_NAVIGATOR_WORKSPACE_DIR",
];
const RUNTIME_RESOURCE_DIR: &str = "runtime-source";
const RUNTIME_MANIFEST_FILE: &str = ".course-navigator-runtime.json";
pub const DEFAULT_API_PORT: u16 = 18000;
pub const DEFAULT_WEB_PORT: u16 = 15173;
const LEGACY_DEFAULT_API_PORT: u16 = 8000;
const LEGACY_DEFAULT_WEB_PORT: u16 = 5173;
const PRESERVED_RUNTIME_ENTRIES: &[&str] = &[
    ".env",
    ".venv",
    ".course-navigator",
    "course-navigator-workspace",
    ".course-navigator-deps.json",
];

pub fn prepare_bundled_runtime(app: &AppHandle) -> Result<(), String> {
    if cfg!(dev) {
        return Ok(());
    }

    let resource_root = app
        .path()
        .resolve(RUNTIME_RESOURCE_DIR, BaseDirectory::Resource)
        .map_err(|error| format!("无法定位打包运行资源: {error}"))?;
    if !resource_root.exists() {
        return Ok(());
    }

    let support_dir = application_support_dir();
    let target_root = runtime_project_dir_for_support(&support_dir);
    let mut config = load_config();
    if !should_use_bundled_runtime(&config, &target_root) {
        return Ok(());
    }
    if runtime_source_needs_install(&resource_root, &target_root)? {
        // Older versions allowed a Workspace inside the runtime directory;
        // the upgrade must never treat it as a stale resource.
        let protected = [config.workspace_dir.trim()]
            .into_iter()
            .filter(|path| !path.is_empty())
            .map(|path| normalized_path(Path::new(path)))
            .collect::<Vec<_>>();
        install_runtime_source(&resource_root, &target_root, &protected)?;
    }

    if Path::new(&config.project_root) != target_root {
        config.project_root = target_root.display().to_string();
    }
    if config.workspace_dir.trim().is_empty()
        || Path::new(&config.workspace_dir).starts_with(default_project_root())
    {
        config.workspace_dir = default_workspace_dir_for_support(&support_dir)
            .display()
            .to_string();
    }
    if Path::new(&config.project_root) == target_root {
        save_config(&config)?;
    }

    Ok(())
}

fn should_use_bundled_runtime(config: &LauncherConfig, target_root: &Path) -> bool {
    let project_root = Path::new(&config.project_root);
    !project_root.exists() || project_root == target_root || project_root == default_project_root()
}

pub fn load_config() -> LauncherConfig {
    let path = launcher_config_path();
    if let Ok(raw) = fs::read_to_string(path) {
        if let Ok(config) = serde_json::from_str::<LauncherConfig>(&raw) {
            return reconcile_config(config);
        }
    }
    default_config()
}

pub fn save_config(config: &LauncherConfig) -> Result<(), String> {
    let path = launcher_config_path();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| format!("无法创建启动器配置目录: {error}"))?;
    }
    let raw = serde_json::to_string_pretty(config)
        .map_err(|error| format!("无法序列化启动器配置: {error}"))?;
    fs::write(path, format!("{raw}\n")).map_err(|error| format!("无法写入启动器配置: {error}"))?;
    write_project_env(config)?;
    Ok(())
}

pub fn default_config() -> LauncherConfig {
    let project_root = default_project_root();
    let support_dir = application_support_dir();
    LauncherConfig {
        workspace_dir: default_workspace_dir(&project_root, &support_dir)
            .display()
            .to_string(),
        project_root: project_root.display().to_string(),
        api_host: "127.0.0.1".to_string(),
        api_port: DEFAULT_API_PORT,
        web_host: "127.0.0.1".to_string(),
        web_port: DEFAULT_WEB_PORT,
        open_browser_on_start: true,
    }
}

pub fn update_env_text(input: &str, config: &LauncherConfig) -> String {
    let updates = managed_env_values(config);
    let mut seen = BTreeMap::new();
    let mut lines = Vec::new();

    for line in input.lines() {
        let Some((key, _)) = line.split_once('=') else {
            lines.push(line.to_string());
            continue;
        };
        if let Some(value) = updates.get(key) {
            lines.push(format!("{key}={value}"));
            seen.insert(key.to_string(), true);
        } else {
            lines.push(line.to_string());
        }
    }

    for key in MANAGED_ENV_KEYS {
        if !seen.contains_key(*key) {
            if let Some(value) = updates.get(*key) {
                lines.push(format!("{key}={value}"));
            }
        }
    }

    format!("{}\n", lines.join("\n"))
}

fn write_project_env(config: &LauncherConfig) -> Result<(), String> {
    let env_path = Path::new(&config.project_root).join(".env");
    let input = fs::read_to_string(&env_path).unwrap_or_default();
    let updated = update_env_text(&input, config);
    fs::write(env_path, updated).map_err(|error| format!("无法写入项目 .env: {error}"))
}

fn managed_env_values(config: &LauncherConfig) -> BTreeMap<&'static str, String> {
    BTreeMap::from([
        (
            "COURSE_NAVIGATOR_API_HOST",
            quote_env_value(&config.api_host),
        ),
        ("COURSE_NAVIGATOR_API_PORT", config.api_port.to_string()),
        (
            "COURSE_NAVIGATOR_WEB_HOST",
            quote_env_value(&config.web_host),
        ),
        ("COURSE_NAVIGATOR_WEB_PORT", config.web_port.to_string()),
        (
            "COURSE_NAVIGATOR_WORKSPACE_DIR",
            quote_env_value(&config.workspace_dir),
        ),
    ])
}

fn quote_env_value(value: &str) -> String {
    if value
        .chars()
        .any(|char| char.is_whitespace() || char == '"' || char == '#')
    {
        format!("\"{}\"", value.replace('\\', "\\\\").replace('"', "\\\""))
    } else {
        value.to_string()
    }
}

fn default_project_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .map(Path::to_path_buf)
        .unwrap_or_else(|| PathBuf::from("."))
}

fn reconcile_config(mut config: LauncherConfig) -> LauncherConfig {
    config = migrate_legacy_default_ports(config);
    if !Path::new(&config.project_root).exists() {
        let project_root = default_project_root();
        if project_root.exists() {
            config.project_root = project_root.display().to_string();
        }
    }
    config
}

fn migrate_legacy_default_ports(mut config: LauncherConfig) -> LauncherConfig {
    if config.api_host == "127.0.0.1"
        && config.web_host == "127.0.0.1"
        && config.api_port == LEGACY_DEFAULT_API_PORT
        && config.web_port == LEGACY_DEFAULT_WEB_PORT
    {
        config.api_port = DEFAULT_API_PORT;
        config.web_port = DEFAULT_WEB_PORT;
    }
    config
}

fn launcher_config_path() -> PathBuf {
    application_support_dir().join("launcher-config.json")
}

pub(crate) fn application_support_dir() -> PathBuf {
    platform_application_support_dir()
}

#[cfg(target_os = "windows")]
fn platform_application_support_dir() -> PathBuf {
    std::env::var_os("APPDATA")
        .or_else(|| std::env::var_os("LOCALAPPDATA"))
        .map(PathBuf::from)
        .or_else(|| {
            std::env::var_os("USERPROFILE")
                .map(PathBuf::from)
                .map(|profile| profile.join("AppData").join("Roaming"))
        })
        .unwrap_or_else(|| PathBuf::from("."))
        .join("Course Navigator")
}

#[cfg(target_os = "macos")]
fn platform_application_support_dir() -> PathBuf {
    std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
        .join("Library")
        .join("Application Support")
        .join("Course Navigator")
}

#[cfg(all(not(target_os = "windows"), not(target_os = "macos")))]
fn platform_application_support_dir() -> PathBuf {
    std::env::var_os("XDG_DATA_HOME")
        .map(PathBuf::from)
        .or_else(|| {
            std::env::var_os("HOME")
                .map(PathBuf::from)
                .map(|home| home.join(".local").join("share"))
        })
        .unwrap_or_else(|| PathBuf::from("."))
        .join("Course Navigator")
}

fn runtime_root_for_support(support_dir: &Path) -> PathBuf {
    support_dir.join("runtime")
}

fn runtime_project_dir_for_support(support_dir: &Path) -> PathBuf {
    runtime_root_for_support(support_dir).join("project")
}

/// The bundled runtime is replaced on upgrade, so user data must live elsewhere.
pub fn ensure_workspace_outside_runtime(target: &Path) -> Result<(), String> {
    workspace_outside_runtime(target, &runtime_root_for_support(&application_support_dir()))
}

fn workspace_outside_runtime(target: &Path, runtime_root: &Path) -> Result<(), String> {
    if normalized_path(target).starts_with(normalized_path(runtime_root)) {
        return Err("Workspace 不能放在启动器的运行目录中，升级时该目录会被替换。".into());
    }
    Ok(())
}

/// Resolves the existing part of `path`, so paths that do not exist yet still
/// compare with the same spelling, case and drive prefix as existing ones.
fn normalized_path(path: &Path) -> PathBuf {
    if let Ok(resolved) = path.canonicalize() {
        return resolved;
    }
    match (path.parent(), path.file_name()) {
        (Some(parent), Some(name)) if !parent.as_os_str().is_empty() => {
            normalized_path(parent).join(name)
        }
        _ => path.to_path_buf(),
    }
}

fn default_workspace_dir_for_support(support_dir: &Path) -> PathBuf {
    support_dir.join("Workspace")
}

fn runtime_source_needs_install(source: &Path, target: &Path) -> Result<bool, String> {
    if !target.exists() {
        return Ok(true);
    }
    let source_manifest = source.join(RUNTIME_MANIFEST_FILE);
    let target_manifest = target.join(RUNTIME_MANIFEST_FILE);
    if !source_manifest.exists() {
        return Ok(false);
    }
    if !target_manifest.exists() {
        return Ok(true);
    }
    let source_raw = fs::read_to_string(&source_manifest)
        .map_err(|error| format!("无法读取打包运行资源清单: {error}"))?;
    let target_raw = fs::read_to_string(&target_manifest)
        .map_err(|error| format!("无法读取运行资源清单: {error}"))?;
    Ok(source_raw != target_raw)
}

/// The manifest marks a complete install: it is removed before copying and
/// written last, so an interrupted upgrade is retried on the next start.
fn install_runtime_source(source: &Path, target: &Path, protected: &[PathBuf]) -> Result<(), String> {
    let target_manifest = target.join(RUNTIME_MANIFEST_FILE);
    if target_manifest.exists() {
        fs::remove_file(&target_manifest)
            .map_err(|error| format!("无法重置运行资源清单: {error}"))?;
    }
    copy_runtime_source(source, target, protected)?;
    let source_manifest = source.join(RUNTIME_MANIFEST_FILE);
    if source_manifest.exists() {
        fs::copy(&source_manifest, &target_manifest)
            .map_err(|error| format!("无法写入运行资源清单: {error}"))?;
    }
    Ok(())
}

fn copy_runtime_source(source: &Path, target: &Path, protected: &[PathBuf]) -> Result<(), String> {
    fs::create_dir_all(target).map_err(|error| format!("无法创建运行目录: {error}"))?;
    remove_stale_runtime_entries(source, target, protected)?;
    for entry in fs::read_dir(source).map_err(|error| format!("无法读取打包运行资源: {error}"))?
    {
        let entry = entry.map_err(|error| format!("无法读取打包运行资源条目: {error}"))?;
        if should_preserve_runtime_entry(&entry.file_name())
            || entry.file_name() == RUNTIME_MANIFEST_FILE
        {
            continue;
        }
        let source_path = entry.path();
        let target_path = target.join(entry.file_name());
        copy_runtime_entry(&source_path, &target_path, protected)?;
    }

    let env_path = target.join(".env");
    let env_example_path = target.join(".env.example");
    if !env_path.exists() && env_example_path.exists() {
        fs::copy(&env_example_path, &env_path)
            .map_err(|error| format!("无法初始化运行配置: {error}"))?;
    }
    Ok(())
}

fn remove_stale_runtime_entries(source: &Path, target: &Path, protected: &[PathBuf]) -> Result<(), String> {
    for entry in fs::read_dir(target).map_err(|error| format!("无法读取运行目录: {error}"))?
    {
        let entry = entry.map_err(|error| format!("无法读取运行目录条目: {error}"))?;
        if should_preserve_runtime_entry(&entry.file_name()) {
            continue;
        }
        // Keep the Workspace, everything in it and every directory that contains it.
        if overlaps_protected(&entry.path(), protected) {
            continue;
        }
        if !source.join(entry.file_name()).exists() {
            remove_runtime_entry(&entry.path())?;
        }
    }
    Ok(())
}

fn remove_runtime_entry(path: &Path) -> Result<(), String> {
    if path.is_dir() {
        fs::remove_dir_all(path).map_err(|error| format!("无法清理过期运行目录: {error}"))
    } else {
        fs::remove_file(path).map_err(|error| format!("无法清理过期运行文件: {error}"))
    }
}

fn copy_runtime_entry(source: &Path, target: &Path, protected: &[PathBuf]) -> Result<(), String> {
    let metadata =
        fs::symlink_metadata(source).map_err(|error| format!("无法读取运行资源文件: {error}"))?;
    if metadata.is_dir() {
        if target.exists() && !target.is_dir() {
            fs::remove_file(target).map_err(|error| format!("无法替换运行资源文件: {error}"))?;
        }
        fs::create_dir_all(target).map_err(|error| format!("无法创建运行资源目录: {error}"))?;
        copy_runtime_source(source, target, protected)
    } else {
        if target.is_dir() {
            if overlaps_protected(target, protected) {
                return Err(format!(
                    "运行资源 {} 与 Workspace 位置冲突，请先把 Workspace 移出运行目录。",
                    target.display()
                ));
            }
            fs::remove_dir_all(target).map_err(|error| format!("无法替换运行资源目录: {error}"))?;
        }
        fs::copy(source, target).map_err(|error| format!("无法复制运行资源文件: {error}"))?;
        Ok(())
    }
}

fn overlaps_protected(path: &Path, protected: &[PathBuf]) -> bool {
    let path = normalized_path(path);
    protected
        .iter()
        .any(|protected| protected.starts_with(&path) || path.starts_with(protected))
}

fn should_preserve_runtime_entry(name: &OsStr) -> bool {
    PRESERVED_RUNTIME_ENTRIES
        .iter()
        .any(|preserved| name == OsStr::new(preserved))
}

fn default_workspace_dir(project_root: &Path, support_dir: &Path) -> PathBuf {
    if cfg!(dev) {
        project_root.join("course-navigator-workspace")
    } else {
        default_workspace_dir_for_support(support_dir)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn env_update_preserves_secret_values_and_unknown_keys() {
        let input = "COURSE_NAVIGATOR_LLM_API_KEY=secret\nCUSTOM_FLAG=yes\nCOURSE_NAVIGATOR_WEB_PORT=5173\n";
        let config = LauncherConfig {
            project_root: "/app".into(),
            api_host: "127.0.0.1".into(),
            api_port: 8100,
            web_host: "127.0.0.1".into(),
            web_port: 5188,
            workspace_dir: "/Volumes/Learning/CourseWorkspace".into(),
            open_browser_on_start: true,
        };

        let updated = update_env_text(input, &config);

        assert!(updated.contains("COURSE_NAVIGATOR_LLM_API_KEY=secret\n"));
        assert!(updated.contains("CUSTOM_FLAG=yes\n"));
        assert!(updated.contains("COURSE_NAVIGATOR_API_PORT=8100\n"));
        assert!(updated.contains("COURSE_NAVIGATOR_WEB_PORT=5188\n"));
        assert!(
            updated.contains("COURSE_NAVIGATOR_WORKSPACE_DIR=/Volumes/Learning/CourseWorkspace\n")
        );
    }

    #[test]
    fn env_update_quotes_workspace_paths_with_spaces() {
        let config = LauncherConfig {
            project_root: "/app".into(),
            api_host: "127.0.0.1".into(),
            api_port: 18000,
            web_host: "127.0.0.1".into(),
            web_port: 15173,
            workspace_dir: "/Volumes/Learning SSD/Course Workspace".into(),
            open_browser_on_start: true,
        };

        let updated = update_env_text("", &config);

        assert!(updated.contains(
            "COURSE_NAVIGATOR_WORKSPACE_DIR=\"/Volumes/Learning SSD/Course Workspace\"\n"
        ));
    }

    #[test]
    fn default_config_uses_non_common_launcher_ports() {
        let config = default_config();

        assert_eq!(config.api_port, DEFAULT_API_PORT);
        assert_eq!(config.web_port, DEFAULT_WEB_PORT);
        assert_ne!(config.api_port, LEGACY_DEFAULT_API_PORT);
        assert_ne!(config.web_port, LEGACY_DEFAULT_WEB_PORT);
    }

    #[test]
    fn reconcile_config_migrates_legacy_default_ports() {
        let config = LauncherConfig {
            project_root: "/app".into(),
            api_host: "127.0.0.1".into(),
            api_port: 8000,
            web_host: "127.0.0.1".into(),
            web_port: 5173,
            workspace_dir: "/tmp/workspace".into(),
            open_browser_on_start: true,
        };

        let reconciled = reconcile_config(config);

        assert_eq!(reconciled.api_port, DEFAULT_API_PORT);
        assert_eq!(reconciled.web_port, DEFAULT_WEB_PORT);
    }

    #[test]
    fn reconcile_config_keeps_custom_ports() {
        let config = LauncherConfig {
            project_root: "/app".into(),
            api_host: "127.0.0.1".into(),
            api_port: 8100,
            web_host: "127.0.0.1".into(),
            web_port: 5188,
            workspace_dir: "/tmp/workspace".into(),
            open_browser_on_start: true,
        };

        let reconciled = reconcile_config(config);

        assert_eq!(reconciled.api_port, 8100);
        assert_eq!(reconciled.web_port, 5188);
    }

    #[test]
    fn reconcile_config_repairs_missing_saved_project_path() {
        let config = LauncherConfig {
            project_root: "/definitely/missing/course-navigator".into(),
            api_host: "127.0.0.1".into(),
            api_port: 8100,
            web_host: "127.0.0.1".into(),
            web_port: 5188,
            workspace_dir: "/tmp/workspace".into(),
            open_browser_on_start: true,
        };

        let repaired = reconcile_config(config);

        assert!(Path::new(&repaired.project_root).exists());
        assert_eq!(repaired.api_port, 8100);
        assert_eq!(repaired.web_port, 5188);
    }

    #[test]
    fn installed_runtime_and_default_workspace_use_separate_app_support_paths() {
        let support_dir = Path::new("/Users/example/Library/Application Support/Course Navigator");

        assert_eq!(
            runtime_project_dir_for_support(support_dir),
            support_dir.join("runtime").join("project")
        );
        assert_eq!(
            default_workspace_dir_for_support(support_dir),
            support_dir.join("Workspace")
        );
        assert!(!default_workspace_dir_for_support(support_dir)
            .starts_with(runtime_project_dir_for_support(support_dir)));
    }

    #[test]
    fn dev_default_workspace_stays_inside_project_root() {
        let project_root = Path::new("/Users/example/course-navigator");
        let support_dir = Path::new("/Users/example/Library/Application Support/Course Navigator");

        assert_eq!(
            default_workspace_dir(project_root, support_dir),
            project_root.join("course-navigator-workspace")
        );
    }

    #[test]
    #[cfg(windows)]
    fn windows_application_support_dir_uses_windows_profile_location() {
        let support_dir = application_support_dir();
        let support = support_dir.to_string_lossy();

        assert!(support.ends_with(r"Course Navigator"));
        assert!(!support.contains("Library"));
        assert!(!support.contains("Application Support"));
    }

    #[test]
    fn bundled_runtime_keeps_an_existing_custom_project_root() {
        let root = std::env::temp_dir().join(format!(
            "course-navigator-project-root-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("time")
                .as_nanos()
        ));
        let project_root = root.join("project");
        let target_root = root.join("support/runtime/project");
        fs::create_dir_all(&project_root).expect("project root");
        fs::create_dir_all(&target_root).expect("target root");
        let config = LauncherConfig {
            project_root: project_root.display().to_string(),
            api_host: "127.0.0.1".into(),
            api_port: 18000,
            web_host: "127.0.0.1".into(),
            web_port: 15173,
            workspace_dir: "/tmp/workspace".into(),
            open_browser_on_start: true,
        };

        assert!(!should_use_bundled_runtime(&config, &target_root));

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn bundled_runtime_replaces_build_time_default_project_root_even_when_it_exists() {
        let target_root = std::env::temp_dir().join("course-navigator-runtime/project");
        let config = LauncherConfig {
            project_root: default_project_root().display().to_string(),
            api_host: "127.0.0.1".into(),
            api_port: 18000,
            web_host: "127.0.0.1".into(),
            web_port: 15173,
            workspace_dir: "/tmp/workspace".into(),
            open_browser_on_start: true,
        };

        assert!(Path::new(&config.project_root).exists());
        assert!(should_use_bundled_runtime(&config, &target_root));
    }

    #[test]
    fn bundled_runtime_is_used_when_project_root_is_missing_or_already_runtime() {
        let root = std::env::temp_dir().join(format!(
            "course-navigator-runtime-choice-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("time")
                .as_nanos()
        ));
        let target_root = root.join("support/runtime/project");
        fs::create_dir_all(&target_root).expect("target root");
        let base = LauncherConfig {
            project_root: root.join("missing").display().to_string(),
            api_host: "127.0.0.1".into(),
            api_port: 18000,
            web_host: "127.0.0.1".into(),
            web_port: 15173,
            workspace_dir: "/tmp/workspace".into(),
            open_browser_on_start: true,
        };

        assert!(should_use_bundled_runtime(&base, &target_root));
        assert!(should_use_bundled_runtime(
            &LauncherConfig {
                project_root: target_root.display().to_string(),
                ..base
            },
            &target_root
        ));

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn copy_runtime_source_preserves_env_and_dependency_state() {
        let root = std::env::temp_dir().join(format!(
            "course-navigator-runtime-copy-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("time")
                .as_nanos()
        ));
        let source = root.join("source");
        let target = root.join("target");
        fs::create_dir_all(source.join("backend")).expect("source backend");
        fs::write(source.join("package.json"), "{}").expect("source package");
        fs::write(source.join("backend/app.py"), "app").expect("source app");
        fs::write(
            source.join(".env.example"),
            "COURSE_NAVIGATOR_WEB_PORT=5173\n",
        )
        .expect("source env example");
        fs::create_dir_all(target.join("node_modules/pkg")).expect("target node_modules");
        fs::create_dir_all(target.join(".venv")).expect("target venv");
        fs::write(target.join(".env"), "COURSE_NAVIGATOR_LLM_API_KEY=secret\n")
            .expect("target env");
        fs::write(target.join("node_modules/pkg/index.js"), "module").expect("target module");
        fs::write(target.join(".venv/pyvenv.cfg"), "venv").expect("target venv cfg");

        copy_runtime_source(&source, &target, &[]).expect("copy runtime source");

        assert_eq!(
            fs::read_to_string(target.join(".env")).expect("read target env"),
            "COURSE_NAVIGATOR_LLM_API_KEY=secret\n"
        );
        assert_eq!(
            fs::read_to_string(target.join("backend/app.py")).expect("read copied source"),
            "app"
        );
        // Web dependencies are no longer used at runtime; upgrades drop them.
        assert!(!target.join("node_modules").exists());
        assert_eq!(
            fs::read_to_string(target.join(".venv/pyvenv.cfg")).expect("read venv"),
            "venv"
        );
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn copy_runtime_source_removes_stale_runtime_files_without_removing_preserved_state() {
        let root = std::env::temp_dir().join(format!(
            "course-navigator-runtime-stale-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("time")
                .as_nanos()
        ));
        let source = root.join("source");
        let target = root.join("target");
        fs::create_dir_all(source.join("backend")).expect("source backend");
        fs::write(source.join("backend/app.py"), "new").expect("source app");
        fs::create_dir_all(target.join("backend")).expect("target backend");
        fs::write(target.join("backend/old.py"), "old").expect("old file");
        fs::create_dir_all(target.join("node_modules/pkg")).expect("node modules");
        fs::write(target.join("node_modules/pkg/index.js"), "module").expect("module");

        copy_runtime_source(&source, &target, &[]).expect("copy runtime source");

        assert!(!target.join("backend/old.py").exists());
        assert_eq!(
            fs::read_to_string(target.join("backend/app.py")).expect("new app"),
            "new"
        );
        assert!(!target.join("node_modules").exists());
        let _ = fs::remove_dir_all(root);
    }

    fn unique_temp_root(label: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "course-navigator-{label}-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("time")
                .as_nanos()
        ))
    }

    #[test]
    fn runtime_upgrade_keeps_a_workspace_inside_the_runtime_directory() {
        let root = unique_temp_root("runtime-protected");
        let source = root.join("source");
        let target = root.join("target");
        fs::create_dir_all(source.join("backend")).expect("source backend");
        fs::write(source.join("backend/app.py"), "new").expect("source app");
        fs::create_dir_all(target.join("data/Workspace/courses")).expect("workspace");
        fs::write(target.join("data/Workspace/courses/a.json"), "{}").expect("course");
        fs::write(target.join("stale.txt"), "old").expect("stale");
        let protected = vec![normalized_path(&target.join("data/Workspace"))];

        install_runtime_source(&source, &target, &protected).expect("install runtime");

        assert!(target.join("data/Workspace/courses/a.json").exists());
        assert!(!target.join("stale.txt").exists());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn runtime_upgrade_keeps_files_inside_a_workspace_that_overlaps_resources() {
        let root = unique_temp_root("runtime-overlap");
        let source = root.join("source");
        let target = root.join("target");
        fs::create_dir_all(source.join("frontend")).expect("source frontend");
        fs::write(source.join("frontend/index.html"), "new").expect("source page");
        fs::create_dir_all(target.join("frontend/courses")).expect("workspace courses");
        fs::write(target.join("frontend/courses/a.json"), "{}").expect("course");
        fs::write(target.join("frontend/old.js"), "old").expect("old file");
        let protected = vec![normalized_path(&target.join("frontend"))];

        install_runtime_source(&source, &target, &protected).expect("install runtime");

        assert!(target.join("frontend/courses/a.json").exists());
        assert!(target.join("frontend/old.js").exists());
        assert_eq!(fs::read_to_string(target.join("frontend/index.html")).expect("page"), "new");
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn runtime_manifest_is_written_after_the_copy_completes() {
        let root = unique_temp_root("runtime-manifest");
        let source = root.join("source");
        let target = root.join("target");
        fs::create_dir_all(&source).expect("source");
        fs::write(source.join(RUNTIME_MANIFEST_FILE), "v2").expect("source manifest");
        // A file replacing a protected directory makes the copy fail midway.
        fs::write(source.join("data"), "file").expect("conflicting file");
        fs::create_dir_all(target.join("data/Workspace")).expect("workspace");
        fs::write(target.join(RUNTIME_MANIFEST_FILE), "v1").expect("target manifest");
        let protected = vec![normalized_path(&target.join("data/Workspace"))];

        assert!(install_runtime_source(&source, &target, &protected).is_err());
        assert!(!target.join(RUNTIME_MANIFEST_FILE).exists());
        assert!(target.join("data/Workspace").is_dir());
        assert!(runtime_source_needs_install(&source, &target).expect("needs install"));

        fs::remove_file(source.join("data")).expect("remove conflict");
        install_runtime_source(&source, &target, &protected).expect("install runtime");
        assert_eq!(
            fs::read_to_string(target.join(RUNTIME_MANIFEST_FILE)).expect("manifest"),
            "v2"
        );
        assert!(!runtime_source_needs_install(&source, &target).expect("installed"));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn workspace_must_stay_outside_the_runtime_directory() {
        let root = unique_temp_root("runtime-guard");
        let runtime = root.join("support/runtime");
        fs::create_dir_all(runtime.join("project")).expect("runtime");

        assert!(workspace_outside_runtime(&runtime.join("project/Workspace"), &runtime).is_err());
        assert!(workspace_outside_runtime(&runtime, &runtime).is_err());
        assert!(workspace_outside_runtime(&root.join("support/Workspace"), &runtime).is_ok());
        assert!(workspace_outside_runtime(&root.join("support/runtime-data"), &runtime).is_ok());
        let _ = fs::remove_dir_all(root);
    }
}
