use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::io::{Read, Write};
use std::net::{TcpStream, ToSocketAddrs};
use std::path::Path;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::models::LauncherConfig;

const MODEL_ENV_KEYS: &[&str] = &[
    "COURSE_NAVIGATOR_LLM_BASE_URL",
    "COURSE_NAVIGATOR_LLM_API_KEY",
    "COURSE_NAVIGATOR_LLM_MODEL",
    "COURSE_NAVIGATOR_MODEL_PROFILES",
    "COURSE_NAVIGATOR_TRANSLATION_MODEL_ID",
    "COURSE_NAVIGATOR_LEARNING_MODEL_ID",
    "COURSE_NAVIGATOR_GLOBAL_MODEL_ID",
    "COURSE_NAVIGATOR_ASR_MODEL_ID",
    "COURSE_NAVIGATOR_ONLINE_ASR_PROVIDER",
    "COURSE_NAVIGATOR_OPENAI_ASR_API_KEY",
    "COURSE_NAVIGATOR_GROQ_ASR_API_KEY",
    "COURSE_NAVIGATOR_XAI_ASR_API_KEY",
    "COURSE_NAVIGATOR_XAI_ASR_MODEL",
    "COURSE_NAVIGATOR_CUSTOM_ASR_BASE_URL",
    "COURSE_NAVIGATOR_CUSTOM_ASR_MODEL",
    "COURSE_NAVIGATOR_CUSTOM_ASR_API_KEY",
];

const LLM_ROLE_KEYS: &[&str] = &[
    "translation_model_id",
    "learning_model_id",
    "global_model_id",
    "asr_model_id",
];

const ONLINE_ASR_PROVIDERS: &[&str] = &["none", "openai", "groq", "xai", "custom"];

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub struct StoredModelProfile {
    pub id: String,
    pub name: String,
    #[serde(default = "default_provider_type")]
    pub provider_type: String,
    pub base_url: String,
    pub model: String,
    pub context_window: Option<u32>,
    pub max_tokens: Option<u32>,
    pub api_key: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ModelProfileView {
    pub id: String,
    pub name: String,
    pub provider_type: String,
    pub base_url: String,
    pub model: String,
    pub context_window: Option<u32>,
    pub max_tokens: Option<u32>,
    pub has_api_key: bool,
    pub api_key_preview: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ModelProfileInput {
    pub id: String,
    pub name: String,
    pub provider_type: String,
    pub base_url: String,
    pub model: String,
    pub context_window: Option<u32>,
    pub max_tokens: Option<u32>,
    pub api_key: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct OnlineAsrServiceView {
    pub base_url: Option<String>,
    pub model: Option<String>,
    pub has_api_key: bool,
    pub api_key_preview: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct OnlineAsrServiceInput {
    pub base_url: Option<String>,
    pub model: Option<String>,
    pub api_key: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct OnlineAsrConfigView {
    pub provider: String,
    pub openai: OnlineAsrServiceView,
    pub groq: OnlineAsrServiceView,
    pub xai: OnlineAsrServiceView,
    pub custom: OnlineAsrServiceView,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct OnlineAsrConfigInput {
    pub provider: String,
    pub openai: OnlineAsrServiceInput,
    pub groq: OnlineAsrServiceInput,
    pub xai: OnlineAsrServiceInput,
    pub custom: OnlineAsrServiceInput,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LauncherModelConfig {
    pub profiles: Vec<ModelProfileView>,
    pub translation_model_id: String,
    pub learning_model_id: String,
    pub global_model_id: String,
    pub asr_model_id: String,
    pub study_detail_level: String,
    pub task_parameters: Value,
    pub online_asr: OnlineAsrConfigView,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LauncherModelConfigInput {
    pub profiles: Vec<ModelProfileInput>,
    pub translation_model_id: String,
    pub learning_model_id: String,
    pub global_model_id: String,
    pub asr_model_id: String,
    pub study_detail_level: String,
    #[serde(default)]
    pub task_parameters: Value,
    pub online_asr: OnlineAsrConfigInput,
}

#[derive(Clone, Debug)]
struct StoredOnlineAsrService {
    base_url: Option<String>,
    model: Option<String>,
    api_key: Option<String>,
}

#[derive(Clone, Debug)]
struct StoredOnlineAsr {
    provider: String,
    openai: StoredOnlineAsrService,
    groq: StoredOnlineAsrService,
    xai: StoredOnlineAsrService,
    custom: StoredOnlineAsrService,
}

#[derive(Clone, Debug)]
struct StoredModelSettings {
    profiles: Vec<StoredModelProfile>,
    translation_model_id: String,
    learning_model_id: String,
    global_model_id: String,
    asr_model_id: String,
    study_detail_level: String,
    task_parameters: Value,
    online_asr: StoredOnlineAsr,
}

pub fn load_model_config(config: &LauncherConfig) -> Result<LauncherModelConfig, String> {
    let settings = load_stored_settings(config)?;
    Ok(public_model_config(settings))
}

pub fn save_model_config(
    config: &LauncherConfig,
    input: LauncherModelConfigInput,
) -> Result<LauncherModelConfig, String> {
    let current = load_stored_settings(config)?;
    let settings = input_to_stored_settings(input, current)?;
    write_model_env(config, &settings)?;
    sync_backend_settings(config, &settings);
    Ok(public_model_config(settings))
}

pub fn set_model_role(
    config: &LauncherConfig,
    role: &str,
    profile_id: &str,
) -> Result<LauncherModelConfig, String> {
    if !LLM_ROLE_KEYS.contains(&role) {
        return Err("未知模型槽位".to_string());
    }
    let current = load_stored_settings(config)?;
    let mut input = stored_to_input(&current);
    match role {
        "translation_model_id" => input.translation_model_id = profile_id.to_string(),
        "learning_model_id" => input.learning_model_id = profile_id.to_string(),
        "global_model_id" => input.global_model_id = profile_id.to_string(),
        "asr_model_id" => input.asr_model_id = profile_id.to_string(),
        _ => {}
    }
    save_model_config(config, input)
}

pub fn set_online_asr_provider(
    config: &LauncherConfig,
    provider: &str,
) -> Result<LauncherModelConfig, String> {
    if !ONLINE_ASR_PROVIDERS.contains(&provider) {
        return Err("未知在线 ASR 模型".to_string());
    }
    let current = load_stored_settings(config)?;
    let mut input = stored_to_input(&current);
    input.online_asr.provider = provider.to_string();
    save_model_config(config, input)
}

pub fn profile_label(profile: &ModelProfileView) -> String {
    if profile.name.trim().is_empty() {
        profile.model.clone()
    } else {
        profile.name.clone()
    }
}

fn load_stored_settings(config: &LauncherConfig) -> Result<StoredModelSettings, String> {
    let env = read_project_env(config);
    let profiles = load_profiles_from_env(&env);
    let first_id = profiles
        .first()
        .map(|profile| profile.id.clone())
        .unwrap_or_default();

    let translation_model_id = role_id_or_first(
        env.get("COURSE_NAVIGATOR_TRANSLATION_MODEL_ID"),
        &profiles,
        &first_id,
    );
    let learning_model_id = role_id_or_first(
        env.get("COURSE_NAVIGATOR_LEARNING_MODEL_ID"),
        &profiles,
        &first_id,
    );
    let global_model_id = role_id_or_first(
        env.get("COURSE_NAVIGATOR_GLOBAL_MODEL_ID"),
        &profiles,
        &first_id,
    );
    let asr_model_id = role_id_or_first(
        env.get("COURSE_NAVIGATOR_ASR_MODEL_ID"),
        &profiles,
        &first_id,
    );

    let task_parameters = env
        .get("COURSE_NAVIGATOR_TASK_PARAMETERS")
        .and_then(|raw| serde_json::from_str::<Value>(raw).ok())
        .unwrap_or_else(|| json!({}));

    Ok(StoredModelSettings {
        profiles,
        translation_model_id,
        learning_model_id,
        global_model_id,
        asr_model_id,
        study_detail_level: env
            .get("COURSE_NAVIGATOR_STUDY_DETAIL_LEVEL")
            .cloned()
            .unwrap_or_else(|| "faithful".to_string()),
        task_parameters,
        online_asr: load_online_asr_from_env(&env),
    })
}

fn load_profiles_from_env(env: &BTreeMap<String, String>) -> Vec<StoredModelProfile> {
    if let Some(raw) = env.get("COURSE_NAVIGATOR_MODEL_PROFILES") {
        if let Ok(profiles) = serde_json::from_str::<Vec<StoredModelProfile>>(raw) {
            let profiles = profiles
                .into_iter()
                .filter(|profile| {
                    !profile.id.trim().is_empty()
                        && !profile.base_url.trim().is_empty()
                        && !profile.model.trim().is_empty()
                })
                .collect::<Vec<_>>();
            if !profiles.is_empty() {
                return profiles;
            }
        }
    }

    let Some(model) = env.get("COURSE_NAVIGATOR_LLM_MODEL") else {
        return Vec::new();
    };
    if model.trim().is_empty() {
        return Vec::new();
    }
    vec![StoredModelProfile {
        id: "default".to_string(),
        name: profile_name_from_model(model),
        provider_type: "openai".to_string(),
        base_url: env
            .get("COURSE_NAVIGATOR_LLM_BASE_URL")
            .cloned()
            .unwrap_or_default(),
        model: model.clone(),
        context_window: None,
        max_tokens: None,
        api_key: env.get("COURSE_NAVIGATOR_LLM_API_KEY").cloned(),
    }]
}

fn load_online_asr_from_env(env: &BTreeMap<String, String>) -> StoredOnlineAsr {
    let openai = StoredOnlineAsrService {
        base_url: Some("https://api.openai.com/v1".to_string()),
        model: Some("whisper-1".to_string()),
        api_key: env.get("COURSE_NAVIGATOR_OPENAI_ASR_API_KEY").cloned(),
    };
    let groq = StoredOnlineAsrService {
        base_url: Some("https://api.groq.com/openai/v1".to_string()),
        model: Some("whisper-large-v3-turbo".to_string()),
        api_key: env.get("COURSE_NAVIGATOR_GROQ_ASR_API_KEY").cloned(),
    };
    let xai = StoredOnlineAsrService {
        base_url: Some("https://api.x.ai/v1".to_string()),
        model: Some(
            env.get("COURSE_NAVIGATOR_XAI_ASR_MODEL")
                .filter(|value| !value.trim().is_empty())
                .cloned()
                .unwrap_or_else(|| "grok-2-voice-1212".to_string()),
        ),
        api_key: env.get("COURSE_NAVIGATOR_XAI_ASR_API_KEY").cloned(),
    };
    let custom = StoredOnlineAsrService {
        base_url: env.get("COURSE_NAVIGATOR_CUSTOM_ASR_BASE_URL").cloned(),
        model: env.get("COURSE_NAVIGATOR_CUSTOM_ASR_MODEL").cloned(),
        api_key: env.get("COURSE_NAVIGATOR_CUSTOM_ASR_API_KEY").cloned(),
    };

    let explicit_provider = env
        .get("COURSE_NAVIGATOR_ONLINE_ASR_PROVIDER")
        .filter(|provider| ONLINE_ASR_PROVIDERS.contains(&provider.as_str()))
        .cloned();
    let provider = explicit_provider.unwrap_or_else(|| {
        if has_key(&xai) {
            "xai".to_string()
        } else if has_key(&openai) {
            "openai".to_string()
        } else if has_key(&groq) {
            "groq".to_string()
        } else if has_key(&custom) {
            "custom".to_string()
        } else {
            "none".to_string()
        }
    });

    StoredOnlineAsr {
        provider,
        openai,
        groq,
        xai,
        custom,
    }
}

fn input_to_stored_settings(
    input: LauncherModelConfigInput,
    current: StoredModelSettings,
) -> Result<StoredModelSettings, String> {
    if input.profiles.is_empty() {
        return Err("至少需要一个 LLM 模型档案。".to_string());
    }
    let current_by_id = current
        .profiles
        .iter()
        .map(|profile| (profile.id.clone(), profile))
        .collect::<BTreeMap<_, _>>();
    let mut seen_ids = BTreeSet::new();
    let mut profiles = Vec::new();
    for profile in input.profiles {
        let id = profile.id.trim().to_string();
        let base_url = profile.base_url.trim().to_string();
        let model = profile.model.trim().to_string();
        if id.is_empty() || base_url.is_empty() || model.is_empty() {
            return Err("模型档案需要 ID、Base URL 和模型名称。".to_string());
        }
        if !seen_ids.insert(id.clone()) {
            return Err(format!("模型档案 ID 重复: {id}"));
        }
        let api_key = match profile.api_key {
            Some(value) if !value.trim().is_empty() => Some(value.trim().to_string()),
            _ => current_by_id
                .get(&id)
                .and_then(|profile| profile.api_key.clone()),
        };
        profiles.push(StoredModelProfile {
            id: id.clone(),
            name: if profile.name.trim().is_empty() {
                profile_name_from_model(&model)
            } else {
                profile.name.trim().to_string()
            },
            provider_type: normalized_provider_type(&profile.provider_type),
            base_url,
            model,
            context_window: profile.context_window,
            max_tokens: profile.max_tokens,
            api_key,
        });
    }

    let profile_ids = profiles
        .iter()
        .map(|profile| profile.id.clone())
        .collect::<BTreeSet<_>>();
    let roles = [
        input.translation_model_id.trim(),
        input.learning_model_id.trim(),
        input.global_model_id.trim(),
        input.asr_model_id.trim(),
    ];
    if roles.iter().any(|role| !profile_ids.contains(*role)) {
        return Err("每个模型选择都必须指向现有 LLM 档案。".to_string());
    }

    Ok(StoredModelSettings {
        profiles,
        translation_model_id: input.translation_model_id.trim().to_string(),
        learning_model_id: input.learning_model_id.trim().to_string(),
        global_model_id: input.global_model_id.trim().to_string(),
        asr_model_id: input.asr_model_id.trim().to_string(),
        study_detail_level: if input.study_detail_level.trim().is_empty() {
            current.study_detail_level
        } else {
            input.study_detail_level.trim().to_string()
        },
        task_parameters: if input.task_parameters.is_object() {
            input.task_parameters
        } else {
            current.task_parameters
        },
        online_asr: merge_online_asr(input.online_asr, current.online_asr),
    })
}

fn merge_online_asr(input: OnlineAsrConfigInput, current: StoredOnlineAsr) -> StoredOnlineAsr {
    StoredOnlineAsr {
        provider: if ONLINE_ASR_PROVIDERS.contains(&input.provider.as_str()) {
            input.provider
        } else {
            current.provider
        },
        openai: merge_online_service(
            input.openai,
            current.openai,
            "https://api.openai.com/v1",
            "whisper-1",
        ),
        groq: merge_online_service(
            input.groq,
            current.groq,
            "https://api.groq.com/openai/v1",
            "whisper-large-v3-turbo",
        ),
        xai: merge_online_service(
            input.xai,
            current.xai,
            "https://api.x.ai/v1",
            "grok-2-voice-1212",
        ),
        custom: merge_custom_online_service(input.custom, current.custom),
    }
}

fn merge_online_service(
    input: OnlineAsrServiceInput,
    current: StoredOnlineAsrService,
    base_url: &str,
    model: &str,
) -> StoredOnlineAsrService {
    StoredOnlineAsrService {
        base_url: Some(base_url.to_string()),
        model: Some(
            input
                .model
                .filter(|value| !value.trim().is_empty())
                .unwrap_or_else(|| current.model.unwrap_or_else(|| model.to_string())),
        ),
        api_key: secret_or_current(input.api_key, current.api_key),
    }
}

fn merge_custom_online_service(
    input: OnlineAsrServiceInput,
    current: StoredOnlineAsrService,
) -> StoredOnlineAsrService {
    StoredOnlineAsrService {
        base_url: input
            .base_url
            .filter(|value| !value.trim().is_empty())
            .or(current.base_url),
        model: input
            .model
            .filter(|value| !value.trim().is_empty())
            .or(current.model),
        api_key: secret_or_current(input.api_key, current.api_key),
    }
}

fn secret_or_current(input: Option<String>, current: Option<String>) -> Option<String> {
    match input {
        Some(value) if !value.trim().is_empty() => Some(value.trim().to_string()),
        _ => current,
    }
}

fn stored_to_input(settings: &StoredModelSettings) -> LauncherModelConfigInput {
    LauncherModelConfigInput {
        profiles: settings
            .profiles
            .iter()
            .map(|profile| ModelProfileInput {
                id: profile.id.clone(),
                name: profile.name.clone(),
                provider_type: profile.provider_type.clone(),
                base_url: profile.base_url.clone(),
                model: profile.model.clone(),
                context_window: profile.context_window,
                max_tokens: profile.max_tokens,
                api_key: profile.api_key.clone(),
            })
            .collect(),
        translation_model_id: settings.translation_model_id.clone(),
        learning_model_id: settings.learning_model_id.clone(),
        global_model_id: settings.global_model_id.clone(),
        asr_model_id: settings.asr_model_id.clone(),
        study_detail_level: settings.study_detail_level.clone(),
        task_parameters: settings.task_parameters.clone(),
        online_asr: OnlineAsrConfigInput {
            provider: settings.online_asr.provider.clone(),
            openai: online_service_to_input(&settings.online_asr.openai),
            groq: online_service_to_input(&settings.online_asr.groq),
            xai: online_service_to_input(&settings.online_asr.xai),
            custom: online_service_to_input(&settings.online_asr.custom),
        },
    }
}

fn online_service_to_input(service: &StoredOnlineAsrService) -> OnlineAsrServiceInput {
    OnlineAsrServiceInput {
        base_url: service.base_url.clone(),
        model: service.model.clone(),
        api_key: service.api_key.clone(),
    }
}

fn public_model_config(settings: StoredModelSettings) -> LauncherModelConfig {
    LauncherModelConfig {
        profiles: settings
            .profiles
            .iter()
            .map(|profile| ModelProfileView {
                id: profile.id.clone(),
                name: profile.name.clone(),
                provider_type: profile.provider_type.clone(),
                base_url: profile.base_url.clone(),
                model: profile.model.clone(),
                context_window: profile.context_window,
                max_tokens: profile.max_tokens,
                has_api_key: profile
                    .api_key
                    .as_ref()
                    .is_some_and(|value| !value.is_empty()),
                api_key_preview: preview_key(profile.api_key.as_deref()),
            })
            .collect(),
        translation_model_id: settings.translation_model_id,
        learning_model_id: settings.learning_model_id,
        global_model_id: settings.global_model_id,
        asr_model_id: settings.asr_model_id,
        study_detail_level: settings.study_detail_level,
        task_parameters: settings.task_parameters,
        online_asr: OnlineAsrConfigView {
            provider: settings.online_asr.provider,
            openai: public_online_service(settings.online_asr.openai),
            groq: public_online_service(settings.online_asr.groq),
            xai: public_online_service(settings.online_asr.xai),
            custom: public_online_service(settings.online_asr.custom),
        },
    }
}

fn public_online_service(service: StoredOnlineAsrService) -> OnlineAsrServiceView {
    OnlineAsrServiceView {
        base_url: service.base_url,
        model: service.model,
        has_api_key: service
            .api_key
            .as_ref()
            .is_some_and(|value| !value.is_empty()),
        api_key_preview: preview_key(service.api_key.as_deref()),
    }
}

fn write_model_env(config: &LauncherConfig, settings: &StoredModelSettings) -> Result<(), String> {
    let env_path = Path::new(&config.project_root).join(".env");
    let input = fs::read_to_string(&env_path).unwrap_or_default();
    let updated = update_model_env_text(&input, settings)?;
    fs::write(&env_path, updated).map_err(|error| format!("无法写入项目 .env: {error}"))
}

fn update_model_env_text(input: &str, settings: &StoredModelSettings) -> Result<String, String> {
    let updates = model_env_values(settings)?;
    Ok(update_env_text_with_values(input, MODEL_ENV_KEYS, &updates))
}

fn model_env_values(
    settings: &StoredModelSettings,
) -> Result<BTreeMap<&'static str, String>, String> {
    let default_profile = settings
        .profiles
        .iter()
        .find(|profile| profile.id == settings.learning_model_id)
        .or_else(|| settings.profiles.first())
        .ok_or_else(|| "至少需要一个 LLM 模型档案。".to_string())?;
    let profile_payload = settings
        .profiles
        .iter()
        .map(|profile| {
            json!({
                "id": profile.id,
                "name": profile.name,
                "provider_type": profile.provider_type,
                "base_url": profile.base_url,
                "model": profile.model,
                "context_window": profile.context_window,
                "max_tokens": profile.max_tokens,
                "api_key": profile.api_key.clone().unwrap_or_default(),
            })
        })
        .collect::<Vec<_>>();

    Ok(BTreeMap::from([
        (
            "COURSE_NAVIGATOR_LLM_BASE_URL",
            quote_env_value(&default_profile.base_url),
        ),
        (
            "COURSE_NAVIGATOR_LLM_API_KEY",
            quote_env_value(default_profile.api_key.as_deref().unwrap_or("")),
        ),
        (
            "COURSE_NAVIGATOR_LLM_MODEL",
            quote_env_value(&default_profile.model),
        ),
        (
            "COURSE_NAVIGATOR_MODEL_PROFILES",
            quote_env_value(
                &serde_json::to_string(&profile_payload).unwrap_or_else(|_| "[]".to_string()),
            ),
        ),
        (
            "COURSE_NAVIGATOR_TRANSLATION_MODEL_ID",
            quote_env_value(&settings.translation_model_id),
        ),
        (
            "COURSE_NAVIGATOR_LEARNING_MODEL_ID",
            quote_env_value(&settings.learning_model_id),
        ),
        (
            "COURSE_NAVIGATOR_GLOBAL_MODEL_ID",
            quote_env_value(&settings.global_model_id),
        ),
        (
            "COURSE_NAVIGATOR_ASR_MODEL_ID",
            quote_env_value(&settings.asr_model_id),
        ),
        (
            "COURSE_NAVIGATOR_ONLINE_ASR_PROVIDER",
            quote_env_value(&settings.online_asr.provider),
        ),
        (
            "COURSE_NAVIGATOR_OPENAI_ASR_API_KEY",
            quote_env_value(settings.online_asr.openai.api_key.as_deref().unwrap_or("")),
        ),
        (
            "COURSE_NAVIGATOR_GROQ_ASR_API_KEY",
            quote_env_value(settings.online_asr.groq.api_key.as_deref().unwrap_or("")),
        ),
        (
            "COURSE_NAVIGATOR_XAI_ASR_API_KEY",
            quote_env_value(settings.online_asr.xai.api_key.as_deref().unwrap_or("")),
        ),
        (
            "COURSE_NAVIGATOR_XAI_ASR_MODEL",
            quote_env_value(
                settings
                    .online_asr
                    .xai
                    .model
                    .as_deref()
                    .unwrap_or("grok-2-voice-1212"),
            ),
        ),
        (
            "COURSE_NAVIGATOR_CUSTOM_ASR_BASE_URL",
            quote_env_value(settings.online_asr.custom.base_url.as_deref().unwrap_or("")),
        ),
        (
            "COURSE_NAVIGATOR_CUSTOM_ASR_MODEL",
            quote_env_value(settings.online_asr.custom.model.as_deref().unwrap_or("")),
        ),
        (
            "COURSE_NAVIGATOR_CUSTOM_ASR_API_KEY",
            quote_env_value(settings.online_asr.custom.api_key.as_deref().unwrap_or("")),
        ),
    ]))
}

fn update_env_text_with_values(
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
            lines.push(format!("{key}={value}"));
            seen.insert(key.to_string());
        } else {
            lines.push(line.to_string());
        }
    }

    for key in managed_keys {
        if !seen.contains(*key) {
            if let Some(value) = updates.get(*key) {
                lines.push(format!("{key}={value}"));
            }
        }
    }

    format!("{}\n", lines.join("\n"))
}

fn sync_backend_settings(config: &LauncherConfig, settings: &StoredModelSettings) {
    let model_body = json!({
        "profiles": settings.profiles.iter().map(|profile| json!({
            "id": profile.id,
            "name": profile.name,
            "provider_type": profile.provider_type,
            "base_url": profile.base_url,
            "model": profile.model,
            "context_window": profile.context_window,
            "max_tokens": profile.max_tokens,
            "api_key": profile.api_key.clone().unwrap_or_default(),
        })).collect::<Vec<_>>(),
        "translation_model_id": settings.translation_model_id,
        "learning_model_id": settings.learning_model_id,
        "global_model_id": settings.global_model_id,
        "asr_model_id": settings.asr_model_id,
        "study_detail_level": settings.study_detail_level,
        "task_parameters": settings.task_parameters,
    });
    let online_body = json!({
        "provider": settings.online_asr.provider,
        "openai": {"api_key": settings.online_asr.openai.api_key.clone().unwrap_or_default()},
        "groq": {"api_key": settings.online_asr.groq.api_key.clone().unwrap_or_default()},
        "xai": {"api_key": settings.online_asr.xai.api_key.clone().unwrap_or_default()},
        "custom": {
            "base_url": settings.online_asr.custom.base_url,
            "model": settings.online_asr.custom.model,
            "api_key": settings.online_asr.custom.api_key.clone().unwrap_or_default(),
        },
    });
    let _ = put_backend_json(config, "/api/settings/model", &model_body);
    let _ = put_backend_json(config, "/api/settings/online-asr", &online_body);
}

fn put_backend_json(config: &LauncherConfig, path: &str, body: &Value) -> Result<(), String> {
    let address = format!("{}:{}", config.api_host, config.api_port);
    let mut addrs = address
        .to_socket_addrs()
        .map_err(|error| format!("无法解析 API 地址: {error}"))?;
    let Some(addr) = addrs.next() else {
        return Err("无法解析 API 地址".to_string());
    };
    let mut stream = TcpStream::connect_timeout(&addr, Duration::from_millis(500))
        .map_err(|error| format!("无法连接 API: {error}"))?;
    let _ = stream.set_read_timeout(Some(Duration::from_millis(1200)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(1200)));

    let raw =
        serde_json::to_string(body).map_err(|error| format!("无法序列化 API 请求: {error}"))?;
    let request = format!(
        "PUT {path} HTTP/1.1\r\nHost: {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        config.api_host,
        raw.as_bytes().len(),
        raw
    );
    stream
        .write_all(request.as_bytes())
        .map_err(|error| format!("无法写入 API 请求: {error}"))?;
    let mut response = String::new();
    let _ = stream.read_to_string(&mut response);
    if response.starts_with("HTTP/1.1 2") || response.starts_with("HTTP/1.0 2") {
        Ok(())
    } else {
        Err("API 设置同步失败".to_string())
    }
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

fn preview_key(api_key: Option<&str>) -> Option<String> {
    let api_key = api_key?.trim();
    if api_key.is_empty() {
        return None;
    }
    if api_key.len() <= 10 {
        return Some("*".repeat(api_key.len()));
    }
    Some(format!(
        "{}{}{}",
        &api_key[..4],
        "*".repeat(8),
        &api_key[api_key.len() - 4..]
    ))
}

fn role_id_or_first(
    role_id: Option<&String>,
    profiles: &[StoredModelProfile],
    first_id: &str,
) -> String {
    let Some(role_id) = role_id else {
        return first_id.to_string();
    };
    if profiles.iter().any(|profile| profile.id == *role_id) {
        role_id.clone()
    } else {
        first_id.to_string()
    }
}

fn profile_name_from_model(model: &str) -> String {
    let name = model
        .rsplit('/')
        .next()
        .unwrap_or(model)
        .replace(['-', '_'], " ")
        .trim()
        .to_string();
    if name.is_empty() {
        "Default Model".to_string()
    } else {
        name
    }
}

fn normalized_provider_type(value: &str) -> String {
    if value == "anthropic" {
        "anthropic".to_string()
    } else {
        "openai".to_string()
    }
}

fn default_provider_type() -> String {
    "openai".to_string()
}

fn has_key(service: &StoredOnlineAsrService) -> bool {
    service
        .api_key
        .as_ref()
        .is_some_and(|value| !value.trim().is_empty())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_config() -> LauncherConfig {
        LauncherConfig {
            project_root: "/app".into(),
            api_host: "127.0.0.1".into(),
            api_port: 8000,
            web_host: "127.0.0.1".into(),
            web_port: 5173,
            workspace_dir: "/workspace".into(),
            open_browser_on_start: true,
        }
    }

    #[test]
    fn parses_quoted_model_profiles_without_losing_secret_values() {
        let raw = r#"COURSE_NAVIGATOR_MODEL_PROFILES="[{\"id\":\"default\",\"name\":\"DeepSeek\",\"provider_type\":\"openai\",\"base_url\":\"https://api.example.com/v1\",\"model\":\"deepseek\",\"api_key\":\"sk-secret\"}]"
COURSE_NAVIGATOR_TRANSLATION_MODEL_ID="default"
COURSE_NAVIGATOR_ONLINE_ASR_PROVIDER="openai"
COURSE_NAVIGATOR_OPENAI_ASR_API_KEY="sk-asr"
"#;
        let env = parse_env_text(raw);
        let profiles = load_profiles_from_env(&env);

        assert_eq!(profiles[0].api_key.as_deref(), Some("sk-secret"));
        assert_eq!(
            load_online_asr_from_env(&env).openai.api_key.as_deref(),
            Some("sk-asr")
        );
    }

    #[test]
    fn model_env_update_preserves_unmanaged_lines_and_quotes_json() {
        let settings = StoredModelSettings {
            profiles: vec![StoredModelProfile {
                id: "default".into(),
                name: "DeepSeek".into(),
                provider_type: "openai".into(),
                base_url: "https://api.example.com/v1".into(),
                model: "deepseek-chat".into(),
                context_window: None,
                max_tokens: None,
                api_key: Some("sk-secret".into()),
            }],
            translation_model_id: "default".into(),
            learning_model_id: "default".into(),
            global_model_id: "default".into(),
            asr_model_id: "default".into(),
            study_detail_level: "faithful".into(),
            task_parameters: json!({}),
            online_asr: load_online_asr_from_env(&BTreeMap::new()),
        };

        let updated = update_model_env_text(
            "CUSTOM_FLAG=yes\nCOURSE_NAVIGATOR_LLM_MODEL=old\n",
            &settings,
        )
        .unwrap();

        assert!(updated.contains("CUSTOM_FLAG=yes\n"));
        assert!(updated.contains("COURSE_NAVIGATOR_LLM_MODEL=deepseek-chat\n"));
        assert!(updated.contains("COURSE_NAVIGATOR_MODEL_PROFILES=\"["));
        assert!(updated.contains("\\\"api_key\\\":\\\"sk-secret\\\""));
    }

    #[test]
    fn role_updates_reject_unknown_profile_ids() {
        let current = StoredModelSettings {
            profiles: vec![StoredModelProfile {
                id: "default".into(),
                name: "Default".into(),
                provider_type: "openai".into(),
                base_url: "https://api.example.com/v1".into(),
                model: "model".into(),
                context_window: None,
                max_tokens: None,
                api_key: None,
            }],
            translation_model_id: "default".into(),
            learning_model_id: "default".into(),
            global_model_id: "default".into(),
            asr_model_id: "default".into(),
            study_detail_level: "faithful".into(),
            task_parameters: json!({}),
            online_asr: load_online_asr_from_env(&BTreeMap::new()),
        };
        let mut input = stored_to_input(&current);
        input.translation_model_id = "missing".into();

        assert!(input_to_stored_settings(input, current).is_err());
    }

    #[test]
    fn model_config_public_response_masks_keys() {
        let mut env = BTreeMap::new();
        env.insert(
            "COURSE_NAVIGATOR_LLM_MODEL".to_string(),
            "model".to_string(),
        );
        env.insert(
            "COURSE_NAVIGATOR_LLM_BASE_URL".to_string(),
            "https://api.example.com/v1".to_string(),
        );
        env.insert(
            "COURSE_NAVIGATOR_LLM_API_KEY".to_string(),
            "sk-1234567890".to_string(),
        );
        let settings = StoredModelSettings {
            profiles: load_profiles_from_env(&env),
            translation_model_id: "default".into(),
            learning_model_id: "default".into(),
            global_model_id: "default".into(),
            asr_model_id: "default".into(),
            study_detail_level: "faithful".into(),
            task_parameters: json!({}),
            online_asr: load_online_asr_from_env(&env),
        };
        let public = public_model_config(settings);

        assert!(public.profiles[0].has_api_key);
        assert_eq!(
            public.profiles[0].api_key_preview.as_deref(),
            Some("sk-1********7890")
        );
    }

    #[test]
    fn sample_config_keeps_model_module_test_fixture_valid() {
        let config = sample_config();
        assert_eq!(config.api_port, 8000);
    }
}
