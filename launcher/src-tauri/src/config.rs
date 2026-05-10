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
const PRESERVED_RUNTIME_ENTRIES: &[&str] = &[
    ".env",
    ".venv",
    "node_modules",
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
    if runtime_source_needs_install(&resource_root, &target_root)? {
        copy_runtime_source(&resource_root, &target_root)?;
    }

    let mut config = load_config();
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

pub fn load_config() -> LauncherConfig {
    let path = launcher_config_path();
    if let Ok(raw) = fs::read_to_string(path) {
        if let Ok(config) = serde_json::from_str::<LauncherConfig>(&raw) {
            return reconcile_project_root(config);
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
        api_port: 8000,
        web_host: "127.0.0.1".to_string(),
        web_port: 5173,
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

fn reconcile_project_root(mut config: LauncherConfig) -> LauncherConfig {
    if !Path::new(&config.project_root).exists() {
        let project_root = default_project_root();
        if project_root.exists() {
            config.project_root = project_root.display().to_string();
        }
    }
    config
}

fn launcher_config_path() -> PathBuf {
    application_support_dir().join("launcher-config.json")
}

fn application_support_dir() -> PathBuf {
    std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
        .join("Library")
        .join("Application Support")
        .join("Course Navigator")
}

fn runtime_project_dir_for_support(support_dir: &Path) -> PathBuf {
    support_dir.join("runtime").join("project")
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

fn copy_runtime_source(source: &Path, target: &Path) -> Result<(), String> {
    fs::create_dir_all(target).map_err(|error| format!("无法创建运行目录: {error}"))?;
    remove_stale_runtime_entries(source, target)?;
    for entry in fs::read_dir(source).map_err(|error| format!("无法读取打包运行资源: {error}"))?
    {
        let entry = entry.map_err(|error| format!("无法读取打包运行资源条目: {error}"))?;
        if should_preserve_runtime_entry(&entry.file_name()) {
            continue;
        }
        let source_path = entry.path();
        let target_path = target.join(entry.file_name());
        copy_runtime_entry(&source_path, &target_path)?;
    }

    let env_path = target.join(".env");
    let env_example_path = target.join(".env.example");
    if !env_path.exists() && env_example_path.exists() {
        fs::copy(&env_example_path, &env_path)
            .map_err(|error| format!("无法初始化运行配置: {error}"))?;
    }
    Ok(())
}

fn remove_stale_runtime_entries(source: &Path, target: &Path) -> Result<(), String> {
    for entry in fs::read_dir(target).map_err(|error| format!("无法读取运行目录: {error}"))?
    {
        let entry = entry.map_err(|error| format!("无法读取运行目录条目: {error}"))?;
        if should_preserve_runtime_entry(&entry.file_name()) {
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

fn copy_runtime_entry(source: &Path, target: &Path) -> Result<(), String> {
    let metadata =
        fs::symlink_metadata(source).map_err(|error| format!("无法读取运行资源文件: {error}"))?;
    if metadata.is_dir() {
        if target.exists() && !target.is_dir() {
            fs::remove_file(target).map_err(|error| format!("无法替换运行资源文件: {error}"))?;
        }
        fs::create_dir_all(target).map_err(|error| format!("无法创建运行资源目录: {error}"))?;
        copy_runtime_source(source, target)
    } else {
        if target.is_dir() {
            fs::remove_dir_all(target).map_err(|error| format!("无法替换运行资源目录: {error}"))?;
        }
        fs::copy(source, target).map_err(|error| format!("无法复制运行资源文件: {error}"))?;
        Ok(())
    }
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
            api_port: 8000,
            web_host: "127.0.0.1".into(),
            web_port: 5173,
            workspace_dir: "/Volumes/Learning SSD/Course Workspace".into(),
            open_browser_on_start: true,
        };

        let updated = update_env_text("", &config);

        assert!(updated.contains(
            "COURSE_NAVIGATOR_WORKSPACE_DIR=\"/Volumes/Learning SSD/Course Workspace\"\n"
        ));
    }

    #[test]
    fn reconcile_project_root_repairs_missing_saved_project_path() {
        let config = LauncherConfig {
            project_root: "/definitely/missing/course-navigator".into(),
            api_host: "127.0.0.1".into(),
            api_port: 8000,
            web_host: "127.0.0.1".into(),
            web_port: 5173,
            workspace_dir: "/tmp/workspace".into(),
            open_browser_on_start: true,
        };

        let repaired = reconcile_project_root(config);

        assert!(Path::new(&repaired.project_root).exists());
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

        copy_runtime_source(&source, &target).expect("copy runtime source");

        assert_eq!(
            fs::read_to_string(target.join(".env")).expect("read target env"),
            "COURSE_NAVIGATOR_LLM_API_KEY=secret\n"
        );
        assert_eq!(
            fs::read_to_string(target.join("backend/app.py")).expect("read copied source"),
            "app"
        );
        assert_eq!(
            fs::read_to_string(target.join("node_modules/pkg/index.js")).expect("read module"),
            "module"
        );
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

        copy_runtime_source(&source, &target).expect("copy runtime source");

        assert!(!target.join("backend/old.py").exists());
        assert_eq!(
            fs::read_to_string(target.join("backend/app.py")).expect("new app"),
            "new"
        );
        assert!(target.join("node_modules/pkg/index.js").exists());
        let _ = fs::remove_dir_all(root);
    }
}
