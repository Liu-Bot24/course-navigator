use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use crate::models::LauncherConfig;

const MANAGED_ENV_KEYS: &[&str] = &[
    "COURSE_NAVIGATOR_API_HOST",
    "COURSE_NAVIGATOR_API_PORT",
    "COURSE_NAVIGATOR_WEB_HOST",
    "COURSE_NAVIGATOR_WEB_PORT",
    "COURSE_NAVIGATOR_WORKSPACE_DIR",
];

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
    LauncherConfig {
        workspace_dir: project_root
            .join("course-navigator-workspace")
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
    std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
        .join("Library")
        .join("Application Support")
        .join("Course Navigator")
        .join("launcher-config.json")
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
}
