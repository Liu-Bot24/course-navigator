use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};

use serde_json::json;

use crate::models::LauncherConfig;
use crate::runtime::{self, ServiceState};

const AUTO_CLEANUP_ENV_KEY: &str = "COURSE_NAVIGATOR_ASR_CACHE_AUTO_CLEANUP_ENABLED";
const DATA_DIR_ENV_KEY: &str = "COURSE_NAVIGATOR_DATA_DIR";
const THRESHOLD_BYTES: u64 = 500 * 1024 * 1024;
const AUDIO_SUFFIXES: &[&str] = &["aac", "flac", "m4a", "mp3", "opus", "wav", "webm"];

#[derive(Clone, Debug)]
pub struct AsrCacheStatus {
    pub size_bytes: u64,
    pub auto_cleanup_enabled: bool,
}

pub fn load_status(config: &LauncherConfig) -> AsrCacheStatus {
    let env = read_project_env(config);
    AsrCacheStatus {
        size_bytes: cache_size_bytes(config, &env),
        auto_cleanup_enabled: env
            .get(AUTO_CLEANUP_ENV_KEY)
            .map(|value| env_bool(value))
            .unwrap_or(true),
    }
}

pub fn set_auto_cleanup(
    state: Option<&ServiceState>,
    config: &LauncherConfig,
    enabled: bool,
) -> Result<AsrCacheStatus, String> {
    write_auto_cleanup_env(config, enabled)?;
    if runtime::configured_services_listening(config) {
        runtime::send_service_json(
            config,
            "PUT",
            "/api/settings/asr-cache",
            Some(&json!({"auto_cleanup_enabled": enabled})),
        )?;
    }
    if enabled {
        let env = read_project_env(config);
        if cache_size_bytes(config, &env) > THRESHOLD_BYTES {
            let _ = cleanup(state, config);
        }
    }
    Ok(load_status(config))
}

pub fn cleanup(state: Option<&ServiceState>, config: &LauncherConfig) -> Result<AsrCacheStatus, String> {
    // A running service may be transcribing from these files; it knows which
    // ones are in use, so the cleanup goes through it.
    if runtime::configured_services_listening(config) {
        runtime::send_service_json(config, "POST", "/api/settings/asr-cache/cleanup", None)?;
        return Ok(load_status(config));
    }
    if runtime::service_may_be_running(state, config) {
        return Err("服务没有响应，无法确认哪些音频正在使用，请稍后再试或先停止服务。".to_string());
    }
    let env = read_project_env(config);
    let root = cache_root(config, &env);
    if root.exists() {
        for path in cache_files(&root) {
            let _ = fs::remove_file(path);
        }
        prune_empty_dirs(&root);
    }
    Ok(load_status(config))
}

pub fn format_cache_size(bytes: u64) -> String {
    const KB: f64 = 1024.0;
    const MB: f64 = 1024.0 * 1024.0;
    const GB: f64 = 1024.0 * 1024.0 * 1024.0;
    if bytes < 1024 {
        return format!("{bytes} B");
    }
    if bytes < 1024 * 1024 {
        return format!("{:.1} KB", bytes as f64 / KB);
    }
    if bytes < 1024 * 1024 * 1024 {
        return format!("{:.1} MB", bytes as f64 / MB);
    }
    format!("{:.1} GB", bytes as f64 / GB)
}

fn cache_size_bytes(config: &LauncherConfig, env: &BTreeMap<String, String>) -> u64 {
    let root = cache_root(config, env);
    cache_files(&root)
        .filter_map(|path| path.metadata().ok().map(|metadata| metadata.len()))
        .sum()
}

fn cache_files(root: &Path) -> impl Iterator<Item = PathBuf> {
    let mut files = Vec::new();
    collect_cache_files(root, &mut files);
    files.into_iter()
}

fn collect_cache_files(path: &Path, files: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(path) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            collect_cache_files(&path, files);
            continue;
        }
        let suffix = path
            .extension()
            .and_then(|extension| extension.to_str())
            .map(|extension| extension.to_ascii_lowercase());
        if suffix
            .as_deref()
            .is_some_and(|extension| AUDIO_SUFFIXES.contains(&extension))
        {
            files.push(path);
        }
    }
}

fn cache_root(config: &LauncherConfig, env: &BTreeMap<String, String>) -> PathBuf {
    let project_root = Path::new(&config.project_root);
    let data_dir = env
        .get(DATA_DIR_ENV_KEY)
        .filter(|value| !value.trim().is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| project_root.join(".course-navigator"));
    let data_dir = if data_dir.is_absolute() {
        data_dir
    } else {
        project_root.join(data_dir)
    };
    data_dir.join("subtitles")
}

fn prune_empty_dirs(root: &Path) {
    let mut directories = Vec::new();
    collect_dirs(root, &mut directories);
    directories.sort_by_key(|path| std::cmp::Reverse(path.components().count()));
    for directory in directories {
        let _ = fs::remove_dir(directory);
    }
    let _ = fs::remove_dir(root);
}

fn collect_dirs(path: &Path, directories: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(path) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            collect_dirs(&path, directories);
            directories.push(path);
        }
    }
}

fn write_auto_cleanup_env(config: &LauncherConfig, enabled: bool) -> Result<(), String> {
    let env_path = Path::new(&config.project_root).join(".env");
    let input = fs::read_to_string(&env_path).unwrap_or_default();
    let mut updates = BTreeMap::new();
    updates.insert(
        AUTO_CLEANUP_ENV_KEY,
        if enabled {
            "true".to_string()
        } else {
            "false".to_string()
        },
    );
    let updated = update_env_text(input.as_str(), &[AUTO_CLEANUP_ENV_KEY], &updates);
    fs::write(&env_path, updated).map_err(|error| format!("无法写入项目 .env: {error}"))
}

fn update_env_text(
    input: &str,
    managed_keys: &[&str],
    updates: &BTreeMap<&'static str, String>,
) -> String {
    let mut seen = BTreeSet::new();
    let mut lines = Vec::new();
    for line in input.lines() {
        let Some((key, _)) = line.split_once('=') else {
            lines.push(line.to_string());
            continue;
        };
        let key = key.trim();
        if let Some(value) = updates.get(key) {
            lines.push(format!("{key}={}", quote_env_value(value)));
            seen.insert(key.to_string());
        } else {
            lines.push(line.to_string());
        }
    }
    for key in managed_keys {
        if !seen.contains(*key) {
            if let Some(value) = updates.get(*key) {
                lines.push(format!("{key}={}", quote_env_value(value)));
            }
        }
    }
    format!("{}\n", lines.join("\n"))
}

fn read_project_env(config: &LauncherConfig) -> BTreeMap<String, String> {
    let env_path = Path::new(&config.project_root).join(".env");
    let input = fs::read_to_string(env_path).unwrap_or_default();
    parse_env_text(&input)
}

fn parse_env_text(input: &str) -> BTreeMap<String, String> {
    let mut values = BTreeMap::new();
    for line in input.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') {
            continue;
        }
        let Some((key, value)) = trimmed.split_once('=') else {
            continue;
        };
        values.insert(key.trim().to_string(), unquote_env_value(value.trim()));
    }
    values
}

fn unquote_env_value(value: &str) -> String {
    let trimmed = value.trim();
    if trimmed.len() < 2 || !trimmed.starts_with('"') || !trimmed.ends_with('"') {
        return trimmed.to_string();
    }
    let mut output = String::new();
    let mut escaped = false;
    for char in trimmed[1..trimmed.len() - 1].chars() {
        if escaped {
            output.push(char);
            escaped = false;
        } else if char == '\\' {
            escaped = true;
        } else {
            output.push(char);
        }
    }
    output
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

fn env_bool(value: &str) -> bool {
    matches!(
        value.trim().to_ascii_lowercase().as_str(),
        "1" | "true" | "yes" | "on"
    )
}
