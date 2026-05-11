mod asr_cache;
mod config;
mod model_config;
mod models;
mod runtime;
mod workspace;

use std::process::Command;

use models::{LauncherConfig, LauncherStatus};
use tauri::{
    image::Image,
    menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem, Submenu},
    tray::TrayIconBuilder,
    ActivationPolicy, Emitter, LogicalSize, Manager, RunEvent, Size,
};

const TRAY_ID: &str = "course-navigator-tray";
const MAIN_WINDOW_WIDTH: f64 = 1000.0;
const MAIN_WINDOW_HEIGHT: f64 = 800.0;
const MAIN_WINDOW_MIN_WIDTH: f64 = 900.0;
const MAIN_WINDOW_MIN_HEIGHT: f64 = 740.0;

#[tauri::command]
fn get_config() -> LauncherConfig {
    config::load_config()
}

#[tauri::command]
fn save_config(app: tauri::AppHandle, config: LauncherConfig) -> Result<LauncherConfig, String> {
    crate::config::save_config(&config)?;
    let _ = refresh_tray_menu(&app);
    Ok(config)
}

#[tauri::command]
fn get_status() -> LauncherStatus {
    let config = get_config();
    let api_url = format!("http://{}:{}", config.api_host, config.api_port);
    let web_url = format!("http://{}:{}", config.web_host, config.web_port);
    if runtime::configured_services_listening(&config) {
        return LauncherStatus {
            state: "running".to_string(),
            api_url,
            web_url,
            message: "检测到本地服务已在运行。".to_string(),
        };
    }
    LauncherStatus {
        state: "stopped".to_string(),
        api_url,
        web_url,
        message: "尚未启动".to_string(),
    }
}

#[tauri::command]
fn get_model_config() -> Result<model_config::LauncherModelConfig, String> {
    let config = get_config();
    model_config::load_model_config(&config)
}

#[tauri::command]
fn save_model_config(
    app: tauri::AppHandle,
    input: model_config::LauncherModelConfigInput,
) -> Result<model_config::LauncherModelConfig, String> {
    let config = get_config();
    let model_config = model_config::save_model_config(&config, input)?;
    let _ = refresh_tray_menu(&app);
    let _ = app.emit("model-config-changed", ());
    Ok(model_config)
}

#[tauri::command]
fn check_dependencies() -> Vec<runtime::DependencyStatus> {
    runtime::check_dependencies()
}

#[tauri::command]
fn start_services(
    app: tauri::AppHandle,
    state: tauri::State<'_, runtime::ServiceState>,
) -> LauncherStatus {
    let config = get_config();
    let api_url = format!("http://{}:{}", config.api_host, config.api_port);
    let web_url = format!("http://{}:{}", config.web_host, config.web_port);
    let existing_services_ready = runtime::configured_services_listening(&config);
    let status = match runtime::start_project_services(state.inner(), &config) {
        Ok(()) => {
            if config.open_browser_on_start {
                let _ = open::that(&web_url);
            }
            LauncherStatus {
                state: "running".to_string(),
                api_url,
                web_url,
                message: if existing_services_ready {
                    "检测到现有服务已可用，已复用并打开网页。".to_string()
                } else {
                    "服务已启动".to_string()
                },
            }
        }
        Err(error) => LauncherStatus {
            state: "failed".to_string(),
            api_url,
            web_url,
            message: error,
        },
    };
    let _ = refresh_tray_menu(&app);
    status
}

#[tauri::command]
fn stop_services(
    app: tauri::AppHandle,
    state: tauri::State<'_, runtime::ServiceState>,
) -> LauncherStatus {
    let config = get_config();
    let api_url = format!("http://{}:{}", config.api_host, config.api_port);
    let web_url = format!("http://{}:{}", config.web_host, config.web_port);
    let status = match runtime::stop_configured_services(state.inner(), &config) {
        Ok(stopped_any) => LauncherStatus {
            state: "stopped".to_string(),
            api_url,
            web_url,
            message: if stopped_any {
                "服务已停止".to_string()
            } else {
                "没有检测到需要停止的服务。".to_string()
            },
        },
        Err(error) => LauncherStatus {
            state: "failed".to_string(),
            api_url,
            web_url,
            message: error,
        },
    };
    let _ = refresh_tray_menu(&app);
    status
}

#[tauri::command]
fn plan_workspace_migration(
    source: String,
    target: String,
) -> Result<workspace::WorkspaceMigrationPlan, String> {
    workspace::migration_plan(&source, &target)
}

#[tauri::command]
fn choose_workspace_directory() -> Result<Option<String>, String> {
    let output = Command::new("/usr/bin/osascript")
        .args([
            "-e",
            r#"POSIX path of (choose folder with prompt "选择 Course Navigator Workspace")"#,
        ])
        .output()
        .map_err(|error| format!("无法打开文件夹选择器: {error}"))?;

    if output.status.success() {
        let selected = String::from_utf8_lossy(&output.stdout)
            .trim()
            .trim_end_matches('/')
            .to_string();
        if selected.is_empty() {
            Ok(None)
        } else {
            Ok(Some(selected))
        }
    } else {
        let error = String::from_utf8_lossy(&output.stderr);
        if error.contains("User canceled") || error.contains("-128") {
            Ok(None)
        } else {
            Err(format!("选择 Workspace 失败: {}", error.trim()))
        }
    }
}

#[tauri::command]
fn set_workspace_directory(
    app: tauri::AppHandle,
    target: String,
    migrate_existing: bool,
) -> Result<LauncherConfig, String> {
    let mut config = config::load_config();
    let source = config.workspace_dir.clone();
    let prepared = workspace::prepare_workspace_change(&source, &target, migrate_existing)?;
    let _migrated = prepared.migrated;
    config.workspace_dir = prepared.target;
    crate::config::save_config(&config)?;
    if prepared.should_remove_source {
        workspace::remove_old_workspace(&source)?;
    }
    let _ = refresh_tray_menu(&app);
    Ok(config)
}

#[tauri::command]
fn show_main_panel(app: tauri::AppHandle) {
    show_main_window(&app);
}

#[tauri::command]
fn open_web_page() -> Result<(), String> {
    let config = config::load_config();
    open::that(format!("http://{}:{}", config.web_host, config.web_port))
        .map_err(|error| format!("打开网页失败: {error}"))
}

pub fn run() {
    let app = tauri::Builder::default()
        .manage(runtime::ServiceState::new())
        .setup(|app| {
            #[cfg(target_os = "macos")]
            app.set_activation_policy(ActivationPolicy::Regular);

            config::prepare_bundled_runtime(app.handle()).map_err(std::io::Error::other)?;
            let menu = build_tray_menu(app.handle())?;
            let tray_icon = template_tray_icon();
            configure_main_window(app.handle());
            TrayIconBuilder::with_id(TRAY_ID)
                .icon(tray_icon)
                .icon_as_template(true)
                .tooltip("Course Navigator")
                .menu(&menu)
                .show_menu_on_left_click(true)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "open_panel" => show_main_window(app),
                    "open_web" => {
                        let config = config::load_config();
                        let _ =
                            open::that(format!("http://{}:{}", config.web_host, config.web_port));
                    }
                    "start" => {
                        let config = config::load_config();
                        if let Some(state) = app.try_state::<runtime::ServiceState>() {
                            let started = runtime::start_project_services(state.inner(), &config);
                            if started.is_ok() && config.open_browser_on_start {
                                let _ = open::that(format!(
                                    "http://{}:{}",
                                    config.web_host, config.web_port
                                ));
                            }
                        }
                        let _ = refresh_tray_menu(app);
                    }
                    "stop" => {
                        let config = config::load_config();
                        if let Some(state) = app.try_state::<runtime::ServiceState>() {
                            let _ = runtime::stop_configured_services(state.inner(), &config);
                        }
                        let _ = refresh_tray_menu(app);
                    }
                    "quit" => {
                        stop_configured_from_app(app);
                        app.exit(0);
                    }
                    id if id.starts_with("model:") => {
                        handle_model_menu_event(app, id);
                    }
                    id if id.starts_with("online_asr:") => {
                        handle_model_menu_event(app, id);
                    }
                    "asr_cache:cleanup" => {
                        let config = config::load_config();
                        let _ = asr_cache::cleanup(&config);
                        let _ = refresh_tray_menu(app);
                    }
                    "asr_cache:auto_cleanup" => {
                        let config = config::load_config();
                        let status = asr_cache::load_status(&config);
                        let _ = asr_cache::set_auto_cleanup(
                            &config,
                            !status.auto_cleanup_enabled,
                        );
                        let _ = refresh_tray_menu(app);
                    }
                    _ => {}
                })
                .build(app)?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_config,
            save_config,
            get_status,
            check_dependencies,
            get_model_config,
            save_model_config,
            start_services,
            stop_services,
            plan_workspace_migration,
            choose_workspace_directory,
            set_workspace_directory,
            show_main_panel,
            open_web_page
        ])
        .on_window_event(|window, event| match event {
            tauri::WindowEvent::CloseRequested { api, .. } if window.label() == "main" => {
                api.prevent_close();
                let _ = window.hide();
            }
            _ => {}
        })
        .build(tauri::generate_context!())
        .expect("failed to build Course Navigator");

    app.run(|app, event| {
        #[cfg(target_os = "macos")]
        if let RunEvent::Reopen {
            has_visible_windows,
            ..
        } = event
        {
            if !has_visible_windows {
                show_main_window(app);
            }
        }
    });
}

fn template_tray_icon() -> Image<'static> {
    Image::from_bytes(include_bytes!("../icons/tray-book.png"))
        .expect("embedded tray icon should be a valid PNG")
        .to_owned()
}

fn stop_configured_from_app(app: &tauri::AppHandle) {
    let config = config::load_config();
    if let Some(state) = app.try_state::<runtime::ServiceState>() {
        let _ = runtime::stop_configured_services(state.inner(), &config);
    }
}

fn configure_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.set_min_size(Some(Size::Logical(LogicalSize {
            width: MAIN_WINDOW_MIN_WIDTH,
            height: MAIN_WINDOW_MIN_HEIGHT,
        })));
        let _ = window.set_size(Size::Logical(LogicalSize {
            width: MAIN_WINDOW_WIDTH,
            height: MAIN_WINDOW_HEIGHT,
        }));
        let _ = window.center();
    }
}

fn show_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn build_tray_menu(app: &tauri::AppHandle) -> tauri::Result<Menu<tauri::Wry>> {
    let config = config::load_config();
    let status_label = tray_status_label(&config);
    let web_url = format!("http://{}:{}", config.web_host, config.web_port);
    let api_url = format!("http://{}:{}", config.api_host, config.api_port);
    let model_menu = build_model_submenu(app, &config)?;
    let asr_cache_status = build_asr_cache_status_item(app, &config)?;
    let asr_auto_cleanup_menu = build_asr_auto_cleanup_submenu(app, &config)?;

    let product = MenuItem::with_id(app, "product", "Course Navigator", false, None::<&str>)?;
    let subtitle = MenuItem::with_id(app, "subtitle", "视频学习工作台", false, None::<&str>)?;
    let status = MenuItem::with_id(app, "status", status_label, false, None::<&str>)?;
    let separator_one = PredefinedMenuItem::separator(app)?;
    let open_web = MenuItem::with_id(app, "open_web", "打开网页", true, None::<&str>)?;
    let open_panel = MenuItem::with_id(app, "open_panel", "打开主窗口", true, None::<&str>)?;
    let separator_two = PredefinedMenuItem::separator(app)?;
    let start = MenuItem::with_id(app, "start", "启动服务", true, None::<&str>)?;
    let stop = MenuItem::with_id(app, "stop", "停止服务", true, None::<&str>)?;
    let separator_three = PredefinedMenuItem::separator(app)?;
    let web = MenuItem::with_id(app, "web", format!("Web: {web_url}"), false, None::<&str>)?;
    let api = MenuItem::with_id(app, "api", format!("API: {api_url}"), false, None::<&str>)?;
    let separator_four = PredefinedMenuItem::separator(app)?;
    let separator_five = PredefinedMenuItem::separator(app)?;
    let quit = MenuItem::with_id(app, "quit", "退出 Course Navigator", true, None::<&str>)?;

    Menu::with_items(
        app,
        &[
            &product,
            &subtitle,
            &status,
            &separator_one,
            &open_web,
            &open_panel,
            &separator_two,
            &start,
            &stop,
            &model_menu,
            &separator_three,
            &asr_cache_status,
            &asr_auto_cleanup_menu,
            &separator_four,
            &web,
            &api,
            &separator_five,
            &quit,
        ],
    )
}

fn build_asr_cache_status_item(
    app: &tauri::AppHandle,
    config: &LauncherConfig,
) -> tauri::Result<MenuItem<tauri::Wry>> {
    let status = asr_cache::load_status(config);
    MenuItem::with_id(
        app,
        "asr_cache:size",
        format!(
            "ASR 缓存: {}",
            asr_cache::format_cache_size(status.size_bytes)
        ),
        false,
        None::<&str>,
    )
}

fn build_asr_auto_cleanup_submenu(
    app: &tauri::AppHandle,
    config: &LauncherConfig,
) -> tauri::Result<Submenu<tauri::Wry>> {
    let status = asr_cache::load_status(config);
    let cleanup_menu = Submenu::with_id(app, "asr_cache:auto", "自动清理", true)?;
    let cleanup_now =
        MenuItem::with_id(app, "asr_cache:cleanup", "立即清理", true, None::<&str>)?;
    let auto_cleanup = CheckMenuItem::with_id(
        app,
        "asr_cache:auto_cleanup",
        "超过 500M 自动清理",
        true,
        status.auto_cleanup_enabled,
        None::<&str>,
    )?;
    cleanup_menu.append(&cleanup_now)?;
    cleanup_menu.append(&auto_cleanup)?;
    Ok(cleanup_menu)
}

fn build_model_submenu(
    app: &tauri::AppHandle,
    config: &LauncherConfig,
) -> tauri::Result<Submenu<tauri::Wry>> {
    let model_config = model_config::load_model_config(config).ok();
    let enabled = model_config
        .as_ref()
        .is_some_and(|settings| !settings.profiles.is_empty());
    let root = Submenu::with_id(app, "models", "模型选择", enabled)?;
    let Some(model_config) = model_config else {
        let empty =
            MenuItem::with_id(app, "models_empty", "未读取到模型档案", false, None::<&str>)?;
        root.append(&empty)?;
        return Ok(root);
    };

    let llm = Submenu::with_id(app, "models_llm", "LLM 模型", enabled)?;
    append_role_menu(
        app,
        &llm,
        "字幕模型",
        "translation_model_id",
        &model_config.translation_model_id,
        &model_config.profiles,
    )?;
    append_role_menu(
        app,
        &llm,
        "详解模型",
        "learning_model_id",
        &model_config.learning_model_id,
        &model_config.profiles,
    )?;
    append_role_menu(
        app,
        &llm,
        "结构模型",
        "global_model_id",
        &model_config.global_model_id,
        &model_config.profiles,
    )?;
    append_role_menu(
        app,
        &llm,
        "ASR 校正模型",
        "asr_model_id",
        &model_config.asr_model_id,
        &model_config.profiles,
    )?;

    let asr = Submenu::with_id(app, "models_asr", "ASR 模型", true)?;
    append_online_asr_menu(app, &asr, &model_config.online_asr)?;

    root.append(&llm)?;
    root.append(&asr)?;
    Ok(root)
}

fn append_role_menu(
    app: &tauri::AppHandle,
    parent: &Submenu<tauri::Wry>,
    label: &str,
    role: &str,
    active_id: &str,
    profiles: &[model_config::ModelProfileView],
) -> tauri::Result<()> {
    let submenu = Submenu::with_id(app, format!("models_{role}"), label, !profiles.is_empty())?;
    for profile in profiles {
        let item = CheckMenuItem::with_id(
            app,
            format!("model:{role}:{}", profile.id),
            model_config::profile_label(profile),
            true,
            profile.id == active_id,
            None::<&str>,
        )?;
        submenu.append(&item)?;
    }
    parent.append(&submenu)
}

fn append_online_asr_menu(
    app: &tauri::AppHandle,
    parent: &Submenu<tauri::Wry>,
    online_asr: &model_config::OnlineAsrConfigView,
) -> tauri::Result<()> {
    let providers = [
        ("none", "不启用".to_string()),
        (
            "openai",
            format!(
                "OpenAI Whisper · {}",
                online_asr.openai.model.as_deref().unwrap_or("whisper-1")
            ),
        ),
        (
            "groq",
            format!(
                "Groq Whisper · {}",
                online_asr
                    .groq
                    .model
                    .as_deref()
                    .unwrap_or("whisper-large-v3-turbo")
            ),
        ),
        (
            "xai",
            format!(
                "xAI · {}",
                online_asr
                    .xai
                    .model
                    .as_deref()
                    .unwrap_or("grok-2-voice-1212")
            ),
        ),
        (
            "custom",
            format!(
                "自定义 · {}",
                online_asr.custom.model.as_deref().unwrap_or("未设置模型")
            ),
        ),
    ];
    for (provider, label) in providers {
        let item = CheckMenuItem::with_id(
            app,
            format!("online_asr:{provider}"),
            label,
            true,
            online_asr.provider == provider,
            None::<&str>,
        )?;
        parent.append(&item)?;
    }
    Ok(())
}

fn refresh_tray_menu(app: &tauri::AppHandle) -> tauri::Result<()> {
    if let Some(tray) = app.tray_by_id(TRAY_ID) {
        let menu = build_tray_menu(app)?;
        tray.set_menu(Some(menu))?;
    }
    Ok(())
}

fn tray_status_label(config: &LauncherConfig) -> &'static str {
    if runtime::configured_services_listening(config) {
        "状态: 运行中"
    } else if runtime::any_configured_service_listening(config) {
        "状态: 端口部分占用"
    } else {
        "状态: 未运行"
    }
}

fn handle_model_menu_event(app: &tauri::AppHandle, id: &str) {
    let config = config::load_config();
    let result = if let Some(rest) = id.strip_prefix("model:") {
        if let Some((role, profile_id)) = rest.split_once(':') {
            model_config::set_model_role(&config, role, profile_id).map(|_| ())
        } else {
            Err("模型菜单事件格式错误".to_string())
        }
    } else if let Some(provider) = id.strip_prefix("online_asr:") {
        model_config::set_online_asr_provider(&config, provider).map(|_| ())
    } else {
        Ok(())
    };
    if result.is_ok() {
        let _ = app.emit("model-config-changed", ());
    }
    let _ = refresh_tray_menu(app);
}
