mod asr_cache;
mod config;
#[cfg(windows)]
mod job;
mod model_config;
mod models;
mod runtime;
mod workspace;

use models::{LauncherConfig, LauncherStatus};
use tauri::{
    image::Image,
    menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem, Submenu},
    tray::TrayIconBuilder,
    Emitter, LogicalSize, Manager, Size,
};
use tauri::RunEvent;
#[cfg(target_os = "macos")]
use tauri::ActivationPolicy;

const TRAY_ID: &str = "course-navigator-tray";
const LAUNCHER_STATUS_EVENT: &str = "launcher-status-changed";
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

/// Runs slow work (process spawns, port probes, installs) off the main thread.
/// Synchronous Tauri commands run on the main thread and freeze the window.
async fn run_blocking<T: Send + 'static>(work: impl FnOnce() -> T + Send + 'static) -> Result<T, String> {
    tauri::async_runtime::spawn_blocking(work)
        .await
        .map_err(|error| format!("后台任务异常结束: {error}"))
}

fn status_for(config: &LauncherConfig, state: &str, message: impl Into<String>) -> LauncherStatus {
    LauncherStatus {
        state: state.to_string(),
        api_url: runtime::api_url(config),
        web_url: runtime::web_url(config),
        message: message.into(),
    }
}

#[tauri::command]
async fn get_status(app: tauri::AppHandle) -> Result<LauncherStatus, String> {
    run_blocking(move || current_status(&app)).await
}

fn current_status(app: &tauri::AppHandle) -> LauncherStatus {
    let config = get_config();
    if let Some(operation) = app
        .try_state::<runtime::ServiceState>()
        .and_then(|state| state.current_operation())
    {
        return status_for(&config, operation.state, operation.message);
    }
    if runtime::configured_services_listening(&config) {
        return status_for(&config, "running", "检测到本地服务已在运行。");
    }
    status_for(&config, "stopped", "尚未启动")
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
    let state = app.try_state::<runtime::ServiceState>();
    let model_config = model_config::save_model_config(state.as_deref(), &config, input)?;
    let _ = refresh_tray_menu(&app);
    let _ = app.emit("model-config-changed", ());
    Ok(model_config)
}

#[tauri::command]
async fn check_dependencies() -> Result<Vec<runtime::DependencyStatus>, String> {
    run_blocking(|| {
        let config = config::load_config();
        runtime::check_dependencies(std::path::Path::new(&config.project_root))
    })
    .await
}

#[tauri::command]
async fn start_services(app: tauri::AppHandle) -> LauncherStatus {
    let fallback = app.clone();
    run_blocking(move || start_services_from_app(&app))
        .await
        .unwrap_or_else(|error| status_for(&get_config(), "failed", error).with_emit(&fallback))
}

/// Reports every step as a "starting" status event and returns the final status.
fn start_services_from_app(app: &tauri::AppHandle) -> LauncherStatus {
    let Some(state) = app.try_state::<runtime::ServiceState>() else {
        return service_state_unavailable_status();
    };
    let state = state.inner();
    let initial_config = config::load_config();
    let Some(guard) = state.begin_operation("starting", "正在检查端口...") else {
        return busy_status(state, &initial_config);
    };
    emit_launcher_status(app, &status_for(&initial_config, "starting", "正在检查端口..."));

    let (config, port_messages) = start_config_with_available_ports(app);
    let report = |message: &str| {
        state.set_operation_message(message);
        emit_launcher_status(app, &status_for(&config, "starting", message));
    };
    let existing_services_ready = runtime::configured_services_listening(&config);
    let status = match runtime::start_project_services(state, &config, &report) {
        Ok(()) => {
            if config.open_browser_on_start {
                let _ = open::that(format!("http://{}:{}", config.web_host, config.web_port));
            }
            let message = if existing_services_ready {
                "检测到现有服务已可用，已复用并打开网页。".to_string()
            } else if !port_messages.is_empty() {
                format!("{}；服务已启动", port_messages.join("；"))
            } else {
                "服务已启动".to_string()
            };
            status_for(&config, "running", message)
        }
        Err(error) if error == runtime::START_CANCELLED => status_for(&config, "stopped", error),
        Err(error) => status_for(&config, "failed", error),
    };
    drop(guard);
    let _ = refresh_tray_menu(app);
    status.with_emit(app)
}

fn busy_status(state: &runtime::ServiceState, config: &LauncherConfig) -> LauncherStatus {
    match state.current_operation() {
        Some(operation) => status_for(config, operation.state, operation.message),
        None => status_for(config, "failed", "操作冲突，请稍后重试。"),
    }
}

#[tauri::command]
async fn stop_services(app: tauri::AppHandle) -> LauncherStatus {
    let fallback = app.clone();
    run_blocking(move || stop_services_from_app(&app))
        .await
        .unwrap_or_else(|error| status_for(&get_config(), "failed", error).with_emit(&fallback))
}

/// Stopping during a start cancels it; the start then reports its own final status.
fn stop_services_from_app(app: &tauri::AppHandle) -> LauncherStatus {
    let Some(state) = app.try_state::<runtime::ServiceState>() else {
        return service_state_unavailable_status();
    };
    let state = state.inner();
    let config = get_config();
    if state.request_start_cancel() {
        return status_for(&config, "stopping", "正在取消启动...").with_emit(app);
    }
    let Some(guard) = state.begin_operation("stopping", "正在停止本地服务...") else {
        return busy_status(state, &config);
    };
    emit_launcher_status(app, &status_for(&config, "stopping", "正在停止本地服务..."));
    let status = match runtime::stop_configured_services(state, &config) {
        Ok(true) => status_for(&config, "stopped", "服务已停止"),
        Ok(false) => status_for(&config, "stopped", "没有检测到需要停止的服务。"),
        Err(error) => status_for(&config, "failed", error),
    };
    drop(guard);
    let _ = refresh_tray_menu(app);
    status.with_emit(app)
}

fn service_state_unavailable_status() -> LauncherStatus {
    status_for(
        &get_config(),
        "failed",
        "无法读取启动器服务状态，请打开主窗口重试。",
    )
}

fn emit_launcher_status(app: &tauri::AppHandle, status: &LauncherStatus) {
    let _ = app.emit(LAUNCHER_STATUS_EVENT, status);
}

trait EmitStatus {
    fn with_emit(self, app: &tauri::AppHandle) -> Self;
}

impl EmitStatus for LauncherStatus {
    /// Tray actions have no caller to return to; the window learns through the event.
    fn with_emit(self, app: &tauri::AppHandle) -> Self {
        emit_launcher_status(app, &self);
        self
    }
}

#[tauri::command]
async fn plan_workspace_migration(
    source: String,
    target: String,
) -> Result<workspace::WorkspaceMigrationPlan, String> {
    run_blocking(move || {
        config::ensure_workspace_outside_runtime(std::path::Path::new(&target))?;
        workspace::migration_plan(&source, &target)
    })
    .await?
}

#[tauri::command]
fn choose_workspace_directory(app: tauri::AppHandle) -> Result<Option<String>, String> {
    let mut dialog = rfd::FileDialog::new().set_title("选择 Course Navigator Workspace");
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
        dialog = dialog.set_parent(&window);
    }
    Ok(dialog.pick_folder().map(|path| path.display().to_string()))
}

#[tauri::command]
async fn set_workspace_directory(
    app: tauri::AppHandle,
    target: String,
    migrate_existing: bool,
) -> Result<LauncherConfig, String> {
    // Migration copies the whole Workspace; keep the window responsive.
    run_blocking(move || {
        let Some(state) = app.try_state::<runtime::ServiceState>() else {
            return Err("无法读取启动器服务状态，请重试。".to_string());
        };
        // Switching shares the start/stop slot, so the service can neither be
        // running nor start while the Workspace is copied and removed.
        let Some(_guard) = state
            .inner()
            .begin_operation("migrating", "正在切换 Workspace...")
        else {
            return Err("服务正在启动或停止，请稍后再切换 Workspace。".to_string());
        };
        let mut config = config::load_config();
        if runtime::service_may_be_running(Some(state.inner()), &config) {
            return Err("请先停止服务，再切换 Workspace。".to_string());
        }
        config::ensure_workspace_outside_runtime(std::path::Path::new(&target))?;
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
    })
    .await?
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
            tauri::async_runtime::spawn_blocking(runtime::remove_legacy_tool_files);
            let menu = build_tray_menu(app.handle())?;
            let tray_icon = platform_tray_icon();
            configure_main_window(app.handle());
            TrayIconBuilder::with_id(TRAY_ID)
                .icon(tray_icon)
                .icon_as_template(cfg!(target_os = "macos"))
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
                    // Tray handlers run on the main thread; long work goes to the background.
                    "start" => {
                        let app = app.clone();
                        tauri::async_runtime::spawn_blocking(move || {
                            start_services_from_app(&app);
                        });
                    }
                    "stop" => {
                        let app = app.clone();
                        tauri::async_runtime::spawn_blocking(move || {
                            stop_services_from_app(&app);
                        });
                    }
                    "quit" => {
                        let app = app.clone();
                        tauri::async_runtime::spawn_blocking(move || {
                            stop_configured_from_app(&app);
                            app.exit(0);
                        });
                    }
                    id if id.starts_with("model:") => {
                        handle_model_menu_event(app, id);
                    }
                    id if id.starts_with("online_asr:") => {
                        handle_model_menu_event(app, id);
                    }
                    "asr_cache:cleanup" => {
                        let app = app.clone();
                        tauri::async_runtime::spawn_blocking(move || {
                            let config = config::load_config();
                            let state = app.try_state::<runtime::ServiceState>();
                            let _ = asr_cache::cleanup(state.as_deref(), &config);
                            let _ = refresh_tray_menu(&app);
                        });
                    }
                    "asr_cache:auto_cleanup" => {
                        let config = config::load_config();
                        let status = asr_cache::load_status(&config);
                        let state = app.try_state::<runtime::ServiceState>();
                        let _ = asr_cache::set_auto_cleanup(
                            state.as_deref(),
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

    app.run(|app, event| match event {
        // Quitting from the Dock, the app menu or a logout skips the tray's
        // quit item, and outside Windows no job object stops the services.
        RunEvent::Exit => stop_configured_from_app(app),
        #[cfg(target_os = "macos")]
        RunEvent::Reopen {
            has_visible_windows,
            ..
        } => {
            if !has_visible_windows {
                show_main_window(app);
            }
        }
        _ => {}
    });
}

fn start_config_with_available_ports(app: &tauri::AppHandle) -> (LauncherConfig, Vec<String>) {
    let config = config::load_config();
    let (resolved, messages) = runtime::resolve_available_ports(&config);
    if config::save_config(&resolved).is_ok() && resolved != config {
        let _ = refresh_tray_menu(app);
    }
    (resolved, messages)
}

#[cfg(target_os = "macos")]
fn platform_tray_icon() -> Image<'static> {
    Image::from_bytes(include_bytes!("../icons/tray-book.png"))
        .expect("embedded macOS tray icon should be a valid PNG")
        .to_owned()
}

#[cfg(not(target_os = "macos"))]
fn platform_tray_icon() -> Image<'static> {
    Image::from_bytes(include_bytes!("../icons/icon.png"))
        .expect("embedded product tray icon should be a valid PNG")
        .to_owned()
}

/// Used on quit: abort a running start, give it time to clean up, then stop services.
/// Runs once, whether the tray's quit item or the app's exit gets there first.
fn stop_configured_from_app(app: &tauri::AppHandle) {
    static STOPPED_FOR_QUIT: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);
    if STOPPED_FOR_QUIT.swap(true, std::sync::atomic::Ordering::SeqCst) {
        return;
    }
    let Some(state) = app.try_state::<runtime::ServiceState>() else {
        return;
    };
    let state = state.inner();
    state.request_start_cancel();
    // A cancelled start kills its install step and services within a few seconds.
    state.wait_for_idle(std::time::Duration::from_secs(15));
    let _ = runtime::stop_configured_services(state, &config::load_config());
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
    let web_url = runtime::web_url(&config);
    let api_url = runtime::api_url(&config);
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
    let cleanup_now = MenuItem::with_id(app, "asr_cache:cleanup", "立即清理", true, None::<&str>)?;
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
    let state = app.try_state::<runtime::ServiceState>();
    let state = state.as_deref();
    let result = if let Some(rest) = id.strip_prefix("model:") {
        if let Some((role, profile_id)) = rest.split_once(':') {
            model_config::set_model_role(state, &config, role, profile_id).map(|_| ())
        } else {
            Err("模型菜单事件格式错误".to_string())
        }
    } else if let Some(provider) = id.strip_prefix("online_asr:") {
        model_config::set_online_asr_provider(state, &config, provider).map(|_| ())
    } else {
        Ok(())
    };
    if result.is_ok() {
        let _ = app.emit("model-config-changed", ());
    }
    let _ = refresh_tray_menu(app);
}
