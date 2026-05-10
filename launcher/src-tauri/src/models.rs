use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LauncherConfig {
    pub project_root: String,
    pub api_host: String,
    pub api_port: u16,
    pub web_host: String,
    pub web_port: u16,
    pub workspace_dir: String,
    pub open_browser_on_start: bool,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LauncherStatus {
    pub state: String,
    pub api_url: String,
    pub web_url: String,
    pub message: String,
}
