use std::fs;
use std::path::{Path, PathBuf};

use serde::Serialize;

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WorkspaceMigrationPlan {
    pub source: String,
    pub target: String,
    pub requires_migration: bool,
    pub message: String,
}

#[derive(Clone, Debug)]
pub struct PreparedWorkspaceChange {
    pub target: String,
    pub migrated: bool,
    pub should_remove_source: bool,
}

pub fn migration_plan(source: &str, target: &str) -> Result<WorkspaceMigrationPlan, String> {
    let source_path = Path::new(source);
    let target_path = Path::new(target);
    validate_workspace_target(source_path, target_path)?;
    let requires_migration = dir_has_entries(source_path)?;

    Ok(WorkspaceMigrationPlan {
        source: source.into(),
        target: target.into(),
        requires_migration,
        message: if requires_migration {
            "检测到当前 Workspace 已有数据，切换前需要迁移。".into()
        } else {
            "当前 Workspace 没有需要迁移的数据，可以直接切换。".into()
        },
    })
}

pub fn prepare_workspace_change(
    source: &str,
    target: &str,
    migrate_existing: bool,
) -> Result<PreparedWorkspaceChange, String> {
    let source_path = Path::new(source);
    let target_path = Path::new(target);
    validate_workspace_target(source_path, target_path)?;

    let requires_migration = dir_has_entries(source_path)?;
    if requires_migration && !migrate_existing {
        return Err("当前 Workspace 已有数据，请确认迁移后再切换。".into());
    }

    fs::create_dir_all(target_path).map_err(|error| format!("无法创建新 Workspace: {error}"))?;
    if requires_migration {
        copy_dir_contents(source_path, target_path)?;
        verify_dir_contents(source_path, target_path)?;
    }

    Ok(PreparedWorkspaceChange {
        target: target_path.display().to_string(),
        migrated: requires_migration,
        should_remove_source: source_path.exists(),
    })
}

pub fn remove_old_workspace(source: &str) -> Result<bool, String> {
    let source_path = Path::new(source);
    if !source_path.exists() {
        return Ok(false);
    }
    guard_removable_workspace(source_path)?;
    fs::remove_dir_all(source_path).map_err(|error| format!("无法清理旧 Workspace: {error}"))?;
    Ok(true)
}

fn validate_workspace_target(source: &Path, target: &Path) -> Result<(), String> {
    if target.as_os_str().is_empty() {
        return Err("请选择新的 Workspace 目录。".into());
    }
    if !target.is_absolute() {
        return Err("Workspace 目录必须是绝对路径。".into());
    }
    if target.exists() && !target.is_dir() {
        return Err("选择的位置不是文件夹。".into());
    }
    if paths_refer_to_same_location(source, target) {
        return Err("新 Workspace 位置和当前位置相同".into());
    }
    if source.exists() {
        let source_abs = absolute_path(source)?;
        let target_abs = absolute_path(target)?;
        if target_abs.starts_with(&source_abs) || source_abs.starts_with(&target_abs) {
            return Err("新旧 Workspace 不能互为上级或下级目录。".into());
        }
    }
    Ok(())
}

fn copy_dir_contents(source: &Path, target: &Path) -> Result<(), String> {
    for entry in fs::read_dir(source).map_err(|error| format!("无法读取当前 Workspace: {error}"))?
    {
        let entry = entry.map_err(|error| format!("无法读取 Workspace 条目: {error}"))?;
        let source_child = entry.path();
        let target_child = target.join(entry.file_name());
        copy_entry(&source_child, &target_child)?;
    }
    Ok(())
}

fn copy_entry(source: &Path, target: &Path) -> Result<(), String> {
    let metadata = fs::symlink_metadata(source)
        .map_err(|error| format!("无法读取 Workspace 文件: {error}"))?;
    if metadata.is_dir() {
        fs::create_dir_all(target)
            .map_err(|error| format!("无法创建 Workspace 子目录: {error}"))?;
        copy_dir_contents(source, target)
    } else if metadata.file_type().is_symlink() {
        copy_symlink(source, target)
    } else {
        if target.exists() && !same_file_contents(source, target)? {
            return Err(format!(
                "目标 Workspace 已存在不同文件: {}",
                target.display()
            ));
        }
        fs::copy(source, target).map_err(|error| format!("无法复制 Workspace 文件: {error}"))?;
        Ok(())
    }
}

#[cfg(unix)]
fn copy_symlink(source: &Path, target: &Path) -> Result<(), String> {
    use std::os::unix::fs::symlink;

    if target.exists() {
        return Ok(());
    }
    let link_target = fs::read_link(source).map_err(|error| format!("无法读取软链接: {error}"))?;
    symlink(link_target, target).map_err(|error| format!("无法复制软链接: {error}"))
}

#[cfg(not(unix))]
fn copy_symlink(source: &Path, target: &Path) -> Result<(), String> {
    let resolved = fs::read_link(source).map_err(|error| format!("无法读取软链接: {error}"))?;
    copy_entry(&resolved, target)
}

fn verify_dir_contents(source: &Path, target: &Path) -> Result<(), String> {
    for entry in fs::read_dir(source).map_err(|error| format!("无法校验 Workspace: {error}"))? {
        let entry = entry.map_err(|error| format!("无法校验 Workspace 条目: {error}"))?;
        let source_child = entry.path();
        let target_child = target.join(entry.file_name());
        verify_entry(&source_child, &target_child)?;
    }
    Ok(())
}

fn verify_entry(source: &Path, target: &Path) -> Result<(), String> {
    if !target.exists() {
        return Err(format!("迁移校验失败，目标缺少文件: {}", target.display()));
    }
    let source_metadata =
        fs::symlink_metadata(source).map_err(|error| format!("无法读取源文件元数据: {error}"))?;
    let target_metadata =
        fs::symlink_metadata(target).map_err(|error| format!("无法读取目标文件元数据: {error}"))?;
    if source_metadata.is_dir() {
        if !target_metadata.is_dir() {
            return Err(format!("迁移校验失败，目标不是目录: {}", target.display()));
        }
        verify_dir_contents(source, target)
    } else if source_metadata.file_type().is_symlink() {
        let source_link =
            fs::read_link(source).map_err(|error| format!("无法校验软链接: {error}"))?;
        let target_link =
            fs::read_link(target).map_err(|error| format!("无法校验软链接: {error}"))?;
        if source_link == target_link {
            Ok(())
        } else {
            Err(format!("迁移校验失败，软链接不一致: {}", target.display()))
        }
    } else if same_file_contents(source, target)? {
        Ok(())
    } else {
        Err(format!(
            "迁移校验失败，文件内容不一致: {}",
            target.display()
        ))
    }
}

fn same_file_contents(left: &Path, right: &Path) -> Result<bool, String> {
    if !right.exists() {
        return Ok(false);
    }
    let left_bytes = fs::read(left).map_err(|error| format!("无法读取源文件: {error}"))?;
    let right_bytes = fs::read(right).map_err(|error| format!("无法读取目标文件: {error}"))?;
    Ok(left_bytes == right_bytes)
}

fn dir_has_entries(path: &Path) -> Result<bool, String> {
    if !path.exists() {
        return Ok(false);
    }
    if !path.is_dir() {
        return Err("当前 Workspace 不是文件夹。".into());
    }
    Ok(path
        .read_dir()
        .map_err(|error| format!("无法读取当前 Workspace: {error}"))?
        .next()
        .is_some())
}

fn guard_removable_workspace(path: &Path) -> Result<(), String> {
    if !path.is_absolute() {
        return Err("拒绝清理非绝对路径 Workspace。".into());
    }
    if path.parent().is_none() || path.file_name().is_none() {
        return Err("拒绝清理根目录。".into());
    }
    if let Some(home) = std::env::var_os("HOME").map(PathBuf::from) {
        if paths_refer_to_same_location(path, &home) {
            return Err("拒绝清理用户主目录。".into());
        }
    }
    Ok(())
}

fn paths_refer_to_same_location(left: &Path, right: &Path) -> bool {
    match (left.canonicalize(), right.canonicalize()) {
        (Ok(left), Ok(right)) => left == right,
        _ => left == right,
    }
}

fn absolute_path(path: &Path) -> Result<PathBuf, String> {
    if path.exists() {
        path.canonicalize()
            .map_err(|error| format!("无法解析 Workspace 路径: {error}"))
    } else if let Some(parent) = path.parent() {
        let parent = parent
            .canonicalize()
            .map_err(|error| format!("无法解析 Workspace 上级目录: {error}"))?;
        Ok(parent.join(path.file_name().unwrap_or_default()))
    } else {
        Err("无法解析 Workspace 路径。".into())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn migration_plan_rejects_same_path() {
        let result = migration_plan("/tmp/workspace", "/tmp/workspace");

        assert!(result.is_err());
    }

    #[test]
    fn migration_plan_marks_existing_workspace_for_migration() {
        let root = test_dir("plan");
        let source = root.join("old");
        let target = root.join("new");
        fs::create_dir_all(&source).expect("source");
        fs::write(source.join("item.json"), "{}").expect("file");

        let plan = migration_plan(&source.display().to_string(), &target.display().to_string())
            .expect("plan");

        assert!(plan.requires_migration);
        cleanup(&root);
    }

    #[test]
    fn prepare_workspace_change_copies_verifies_and_allows_old_workspace_cleanup() {
        let root = test_dir("copy");
        let source = root.join("old-workspace");
        let target = root.join("new-workspace");
        fs::create_dir_all(source.join("downloads")).expect("source");
        fs::write(source.join("downloads/video.mp4"), "video").expect("file");

        let prepared = prepare_workspace_change(
            &source.display().to_string(),
            &target.display().to_string(),
            true,
        )
        .expect("prepare");

        assert!(prepared.migrated);
        assert!(prepared.should_remove_source);
        assert_eq!(
            fs::read_to_string(target.join("downloads/video.mp4")).expect("copied"),
            "video"
        );
        assert!(remove_old_workspace(&source.display().to_string()).expect("remove"));
        assert!(!source.exists());
        assert!(root.exists());
        cleanup(&root);
    }

    #[test]
    fn prepare_workspace_change_rejects_nested_targets() {
        let root = test_dir("nested");
        let source = root.join("old");
        let target = source.join("nested");
        fs::create_dir_all(&source).expect("source");

        let result = prepare_workspace_change(
            &source.display().to_string(),
            &target.display().to_string(),
            false,
        );

        assert!(result.is_err());
        cleanup(&root);
    }

    fn test_dir(label: &str) -> PathBuf {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("time")
            .as_nanos();
        std::env::temp_dir().join(format!("course-navigator-workspace-{label}-{stamp}"))
    }

    fn cleanup(path: &Path) {
        let _ = fs::remove_dir_all(path);
    }
}
