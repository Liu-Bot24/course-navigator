# Course Navigator Mac Launcher 设计

## 背景

Course Navigator 当前已经适合作为日常视频学习工作台使用，但启动和停止仍依赖终端：用户需要运行 `npm start`，再通过 `Ctrl+C` 停掉前后端进程。这个流程对开发者可以接受，对高频学习使用不够顺手。

本设计目标是增加一个 Mac 原生启动器，让用户可以像打开普通 Mac App 一样启动 Course Navigator，同时保留现有 Web 客户端体验。第一版优先服务当前用户自己的 Mac，不追求立即分发给其他机器；但架构必须能自然演进到第二版的独立 App，避免做一次性脚本壳。

## 目标

- 提供一个可双击启动的 Mac App。
- 打开 App 后可以自动启动后端和前端，并自动在默认浏览器打开 Course Navigator 页面。
- App 内提供启动、停止、重启、打开浏览器、查看运行状态和日志的操作。
- 关闭 App 时联动停止由 App 启动的前后端进程。
- 支持配置 API 端口、Web 端口和 Workspace 路径。
- 支持把 Workspace 迁移到外置 SSD 等新位置，并更新配置。
- 第一版依赖当前源码项目目录和本机已安装的 `node`、`npm`、`uv`、`ffmpeg`、`yt-dlp`。
- 第二版可以升级为轻量 App 本体 + 首次启动自动安装运行时依赖，而不是把所有依赖都打进巨大安装包。

## 非目标

- 第一版不做公开分发，不处理 Developer ID 签名、公证和自动更新。
- 第一版不把 Python、Node、ffmpeg、yt-dlp 全部内置进 `.app`。
- 不把下载缓存目录从 Workspace 中独立出来；视频缓存继续位于 Workspace 的 `downloads/`。
- 不把 Workspace 和运行时依赖混放。Workspace 只保存课程资料、学习材料和视频缓存；运行时依赖未来应放在 App Support。
- 不做 Mac App Store 版本。未来若公开分发，优先考虑 Developer ID 直接分发。

## 推荐路线

采用 Tauri 构建 Mac Launcher。第一版的 Tauri App 作为真实产品壳存在，不做 Automator、AppleScript 或只包装 `npm start` 的临时方案。

第一版运行模式：

- Tauri App 读取本地 Launcher 配置。
- 根据配置定位当前 Course Navigator 项目目录。
- 检查本机依赖是否存在。
- 写入或更新项目 `.env` 中的端口和 Workspace 路径。
- 启动后端和前端服务。
- 健康检查通过后打开默认浏览器。
- App 关闭或用户点击停止时，只停止由 Launcher 自己启动的进程。

第二版运行模式：

- Tauri App 本体基本保留。
- Runtime Manager 从“使用源码目录和本机工具”升级为“管理 App 私有运行时”。
- 依赖下载到 `~/Library/Application Support/Course Navigator/runtime/...`。
- 前端尽量使用 build 后静态资源，减少对 Vite dev server 的运行时依赖。
- 后端、Python 环境、ffmpeg、yt-dlp 按 manifest 管理版本、校验和修复。

这条路线中，第一版到第二版的主要变化是 Runtime Provider 的替换，不需要推倒 Launcher、配置和 Workspace 迁移逻辑。

## 架构

### Launcher Shell

Launcher Shell 是 Tauri App 的 UI 层，提供：

- 当前服务状态：未启动、启动中、运行中、停止中、失败。
- API 与 Web 地址。
- 启动、停止、重启、打开浏览器按钮。
- 端口配置。
- Workspace 路径选择。
- Workspace 迁移入口。
- 依赖检查状态。
- 简洁日志面板。

UI 不直接理解后端业务，只通过 Service Manager、Config Manager 和 Workspace Manager 执行动作。

### Service Manager

Service Manager 负责进程生命周期：

- 根据当前配置启动 API 服务。
- 根据当前配置启动 Web 服务。
- 记录由 Launcher 启动的 PID。
- 捕获 stdout/stderr 并写入日志面板。
- 对 `/api/health` 和 Web 地址做 ready 检查。
- 停止时向自己启动的进程发送优雅终止信号。
- 端口占用时提示用户选择复用、换端口或查看占用信息，不按端口粗暴 kill。

第一版可以继续启动现有命令：

- API：`uv run uvicorn course_navigator.app:app --app-dir backend --host 127.0.0.1 --port <apiPort>`
- Web：`npm run dev -- --host 127.0.0.1 --port <webPort>`

但实现上不要把命令散落在 UI 中，应封装为 `ProjectRuntimeProvider`。

### Runtime Manager

Runtime Manager 是第一版和第二版衔接的核心边界。

第一版提供 `ProjectRuntimeProvider`：

- 依赖当前源码目录。
- 检查 `node`、`npm`、`uv`、`ffmpeg`、`yt-dlp`。
- 必要时提示用户在终端安装缺失依赖，但不自动修改系统环境。
- 使用项目已有依赖安装流程，如 `uv sync`、`npm install` 或 `npm ci`。

第二版新增 `ManagedRuntimeProvider`：

- 在 App Support 中管理运行时目录。
- 首次启动下载缺失依赖。
- 对下载文件做版本 pin 和 checksum 校验。
- 将 Python 环境、后端依赖、ffmpeg、yt-dlp 与 App 版本解耦。
- 支持一键修复运行时。

第二版不需要把所有依赖提前打包进 `.app`。更好的体验是 App 本体轻量，首次启动或升级时按需安装受控运行时。

### Config Manager

Config Manager 负责 Launcher 配置和项目配置之间的边界。

Launcher 私有配置建议放在：

`~/Library/Application Support/Course Navigator/launcher-config.json`

内容包括：

- 项目目录。
- API 端口。
- Web 端口。
- Workspace 路径。
- 是否启动后自动打开浏览器。
- 最近一次运行状态和日志位置。

项目 `.env` 仍保存 Course Navigator 服务实际读取的配置：

- `COURSE_NAVIGATOR_API_HOST`
- `COURSE_NAVIGATOR_API_PORT`
- `COURSE_NAVIGATOR_WEB_HOST`
- `COURSE_NAVIGATOR_WEB_PORT`
- `COURSE_NAVIGATOR_WORKSPACE_DIR`
- `COURSE_NAVIGATOR_DATA_DIR`
- 模型和 ASR 相关 key 与设置。

Launcher 不应读取、展示或复制 API Key 明文。更新 `.env` 时要保留现有 key，只改端口和 Workspace 等非敏感配置项。

### Workspace Manager

Workspace Manager 负责 Workspace 选择和迁移。

Workspace 继续是用户可理解的课程资料目录，包含：

- `items/` 课程记录。
- `downloads/` 本地导入视频和下载缓存。
- 生成的学习材料。

迁移流程：

1. 用户选择新 Workspace 位置。
2. App 检查目标路径是否可写、是否已有 Course Navigator Workspace、剩余空间是否足够。
3. App 暂停或要求停止运行中的服务。
4. App 复制旧 Workspace 到新位置，保留目录结构。
5. App 校验关键文件数量、总大小和基础可读性。
6. App 更新 Launcher 配置和项目 `.env`。
7. App 重新启动服务并加载新 Workspace。
8. 旧 Workspace 默认保留，用户确认后再删除。

迁移不应移动 `.env`、过程数据目录 `.course-navigator` 或运行时依赖目录。

## 当前代码需要配合的调整

### 动态端口

当前 `scripts/start.sh` 已支持端口环境变量，这是好基础。

需要补齐：

- Vite proxy 目前固定到 `http://127.0.0.1:8000`，需要支持动态 API 端口。
- 后端 CORS 当前固定放行 `5173`，需要支持动态 Web 端口，或改成生产路径中由后端托管前端静态资源以避免 CORS。

### 生产式 Web 服务

第一版可以继续使用 Vite dev server，但应把“生产式 Web 服务”作为早期改造目标：

- `npm run build` 生成前端静态资源。
- 后端 FastAPI 可选挂载前端静态目录。
- 日常 Launcher 启动时尽量只启动一个后端服务。

这样第二版不需要携带 Node runtime 作为日常运行依赖，Node 只保留给开发构建。

### 设置写入

后端已有模型、ASR 设置写入 `.env` 的逻辑。Launcher 更新 `.env` 时要使用同样谨慎的策略：

- 保留未知键。
- 保留密钥值。
- 只更新 Launcher 负责的非敏感键。
- 写入前后使用原子写，避免中断造成 `.env` 损坏。

## 错误处理

- 缺少依赖：展示缺失项、用途和修复建议；第一版不自动安装。
- 端口占用：展示占用端口，提供换端口或复用现有服务选项；不直接 kill 非 Launcher 进程。
- API 启动失败：展示后端日志尾部，保留重试按钮。
- Web 启动失败：展示前端日志尾部，允许只打开 API 健康状态。
- Workspace 不可写：阻止启动并提示选择其他路径。
- Workspace 迁移失败：保留旧 Workspace 配置，不切换到不完整目标。
- 关闭 App：只停止 Launcher 启动的进程；如果停止超时，再提示用户是否强制结束。

## 安全与隐私

- App 默认只监听 `127.0.0.1`。
- 不在 Launcher UI 中显示 API Key、cookie 或其他密钥明文。
- Workspace 迁移不复制 `.env` 到外置盘，除非用户未来明确选择配置迁移功能。
- 运行时依赖未来自动下载时必须使用 HTTPS、固定版本和 checksum。
- 用户自己使用时可以先跳过签名和公证；公开分发前再引入 Developer ID 签名和 notarization。

## 测试策略

### 单元测试

- Config Manager 保留未知 `.env` 键。
- Config Manager 更新端口和 Workspace 时不清空密钥。
- Workspace Manager 正确计算目录大小和迁移计划。
- Service Manager 不会停止非自己启动的进程。

### 集成测试

- 使用临时项目目录启动 API 和 Web。
- 修改端口后能通过健康检查。
- 切换 Workspace 后能读取新 Workspace 中的课程。
- 迁移失败时配置保持旧路径。

### 手动验收

- 双击 App 后自动启动服务并打开默认浏览器。
- 点击停止后端口释放。
- 关闭 App 后前后端停止。
- 外置 SSD Workspace 可选、可迁移、可重新打开。
- 端口占用时提示清楚，不误杀其他服务。

## 分阶段计划

### 阶段 1：个人可用 Launcher

- 新增 Tauri App。
- 实现项目目录配置。
- 实现依赖检查。
- 实现启动、停止、重启、打开浏览器。
- 实现端口配置。
- 实现 Workspace 路径选择。
- 展示基础日志。

### 阶段 2：Workspace 迁移

- 加入迁移向导。
- 支持复制到新位置并校验。
- 成功后更新配置并重启服务。
- 旧 Workspace 默认保留。

### 阶段 3：生产式启动路径

- 支持前端 build 后由后端托管。
- Launcher 默认启动单一后端服务。
- 保留开发模式作为开发者选项。

### 阶段 4：托管运行时

- 加入 `ManagedRuntimeProvider`。
- 下载和校验 Python runtime、后端依赖、ffmpeg、yt-dlp。
- 运行时放在 App Support，不进入 Workspace。
- 支持运行时修复和升级。

### 阶段 5：分发准备

- 添加 App 图标和版本信息。
- 加入签名配置。
- 准备 Developer ID 和 notarization 流程。
- 设计更新机制和 release manifest。

## 关键决策

- 第一版做真正 Tauri Launcher，不做临时脚本壳。
- 第一版依赖当前项目目录和本机工具，但通过 Runtime Manager 隔离这件事。
- 第二版优先采用按需安装受控运行时，不默认塞进巨大离线包。
- Workspace 可选且可迁移，视频缓存仍属于 Workspace。
- Launcher 不管理密钥明文，只管理启动、端口和 Workspace。
- 默认打开系统浏览器，而不是强制内嵌 WebView。
