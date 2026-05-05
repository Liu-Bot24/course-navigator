# Course Navigator

[English README](README.en.md)

![Course Navigator 项目横幅](docs/images/course-navigator-banner.jpg)

Course Navigator 是一个视频课程学习工作台。你可以粘贴支持的视频链接，提取字幕，在视频旁边校阅逐字稿，把课程整理成专辑，并用 AI 完成字幕翻译、课程分析和 ASR 字幕校正。

它适合学习者、研究者和需要处理大量课程内容的团队：快速看懂长视频讲了什么，把课程资料管理起来，并在复习时准确跳回对应片段。

## 界面预览

![Course Navigator 视频课程工作台](docs/images/course-navigator-workspace.jpg)

## 主要功能

- 建立课程库，支持专辑分组、课程标题、排序和本地视频缓存管理。
- 导入和导出轻量课程包，用于分享已整理好的课程、校正后的字幕、翻译字幕和 AI 学习材料。
- 通过 `yt-dlp` 从支持的视频页面提取字幕。
- 对需要登录的视频，可使用直接访问、浏览器登录状态或 cookies 文件。
- 在支持的视频源上边看视频边点击字幕跳转，支持双语字幕视图和时间戳导航。
- 生成 AI 学习材料，包括导览、大纲、解读和详解。
- 导览、大纲、解读、详解可以单独重新生成，不必每次全量重跑。
- 翻译字幕和标题。
- 在专门的 ASR 校正工作台里修正自动语音识别字幕，支持可编辑的修改前/修改后视图、鼠标悬停审阅卡片、置信度、接受/拒绝、按置信度排序、一键接受高置信度建议、可选自动保存和再次校正。
- 在 ASR 校正前补充你已确认的术语、人名、产品名和常见误识别。
- 可选使用 Tavily 或 Firecrawl 对 ASR 校正候选项做搜索校验。
- 翻译、课程分析和 ASR 校正共用同一套模型档案库，支持 OpenAI 兼容格式和 Anthropic 格式。

## 最近更新

- 课程包分享：可以从课程库选择单个课程或完整专辑导出分享包。分享包包含视频链接、校正后的字幕、翻译字幕、AI 学习材料和可选留言，不包含本地视频缓存或模型档案。导入完整专辑时会保留专辑名称和课程顺序。
- ASR 搜索校验升级：搜索结果会先归纳成背景信息，再和视频元数据、附加参考信息一起参与最终校正，减少因为模型知识过时造成的误改。
- ASR 校正体验优化：支持修改建议导航、修改前/修改后同步滚动、悬停审阅、置信度排序、一键接受高置信度建议和接受后自动保存。
- 课程库细节优化：支持专辑排序和删除专辑；删除课程时会同步清理相关本地缓存。

## 运行要求

- Node.js 20 或更新版本，并包含 npm。
- Python 3.11 或更新版本。
- `uv`，用于管理 Python 依赖。
- `ffmpeg`，启动时不是必须，但本地视频缓存、音频提取和媒体转换需要它。
- `curl`，启动脚本会用它检查服务是否就绪。

`yt-dlp` 会随 Python 项目依赖安装。

应用可以在缺少 `ffmpeg` 时正常启动。如果你要使用视频缓存或本地音频相关流程，可以用系统包管理器安装它，例如：

```bash
# macOS
brew install ffmpeg

# Ubuntu 或 Debian
sudo apt install ffmpeg

# Windows
winget install Gyan.FFmpeg
```

## 快速开始

```bash
git clone https://github.com/Liu-Bot24/course-navigator.git
cd course-navigator
npm start
```

启动命令会安装依赖、在需要时创建本地设置文件、启动 API 和网页应用。如果缺少 `ffmpeg`，启动时会显示警告但继续运行。

打开：

```text
http://127.0.0.1:5173
```

在终端按 `Ctrl+C` 可以同时停止两个服务。

## AI 配置

不配置 AI 模型时，Course Navigator 仍然可以提取、浏览和手动编辑字幕。AI 翻译、课程分析和 ASR 校正需要至少一个模型档案。

在应用设置里新建模型档案，选择服务格式，填写 API 地址、模型名称和 API Key，然后把模型档案分配给需要使用的任务：

| 任务 | 用途 |
| --- | --- |
| 字幕模型 | 字幕翻译和标题翻译。 |
| 学习模型 | 解读和详解文本。 |
| 结构模型 | 上下文摘要、语义分块、导览和大纲。 |
| ASR 校正模型 | ASR 校正工作台里的修改建议。 |

模型档案支持：

| 服务格式 | 常见 API 地址 |
| --- | --- |
| OpenAI 兼容格式 | `https://api.openai.com/v1` 或其他兼容端点 |
| Anthropic 格式 | `https://api.anthropic.com/v1` 或兼容 Anthropic 的端点 |

应用也会读取可选环境配置：

| 配置项 | 作用 | 默认值 |
| --- | --- | --- |
| `COURSE_NAVIGATOR_DATA_DIR` | 本地应用数据目录 | `.course-navigator` |
| `COURSE_NAVIGATOR_LLM_BASE_URL` | 可选的单模型 API 地址 | 空 |
| `COURSE_NAVIGATOR_LLM_API_KEY` | 可选的单模型 API Key | 空 |
| `COURSE_NAVIGATOR_LLM_MODEL` | 可选的单模型名称 | 空 |
| `COURSE_NAVIGATOR_ASR_SEARCH_ENABLED` | 是否启用搜索辅助 ASR 校正 | `false` |
| `COURSE_NAVIGATOR_ASR_SEARCH_PROVIDER` | ASR 搜索校验服务 | `tavily` |
| `COURSE_NAVIGATOR_ASR_SEARCH_RESULT_LIMIT` | 每次查询返回的搜索结果数 | `5` |
| `COURSE_NAVIGATOR_TAVILY_API_KEY` | Tavily API Key | 空 |
| `COURSE_NAVIGATOR_FIRECRAWL_BASE_URL` | Firecrawl API 地址 | 空 |
| `COURSE_NAVIGATOR_FIRECRAWL_API_KEY` | Firecrawl API Key | 空 |

Firecrawl 可以使用官方服务或自托管服务：

| 使用方式 | Firecrawl 地址 | API Key |
| --- | --- | --- |
| 官方服务 | `https://api.firecrawl.dev` | 填写 Firecrawl 官方后台生成的 API Key |
| 自托管服务 | 你的 Firecrawl 服务地址，例如 `http://192.168.1.10:3002` | 如果你的自托管服务开启了鉴权就填写；没有开启可留空 |

填写地址时可以只填服务根地址。Course Navigator 会在请求搜索时自动使用 `/v1/search` 接口；例如 `https://api.firecrawl.dev` 会请求到 `https://api.firecrawl.dev/v1/search`。

一键启动脚本支持自定义本地端口：

| 配置项 | 作用 | 默认值 |
| --- | --- | --- |
| `COURSE_NAVIGATOR_API_HOST` | API 监听地址 | `127.0.0.1` |
| `COURSE_NAVIGATOR_API_PORT` | API 端口 | `8000` |
| `COURSE_NAVIGATOR_WEB_HOST` | 网页应用监听地址 | `127.0.0.1` |
| `COURSE_NAVIGATOR_WEB_PORT` | 网页应用端口 | `5173` |

## 视频访问模式

Course Navigator 支持三种提取模式：

| 模式 | 适用场景 |
| --- | --- |
| 普通模式 | 视频公开，可直接访问。 |
| 浏览器登录状态 | 视频在浏览器里可以观看，需要复用你的登录状态。 |
| Cookies 文件 | 你已经为目标网站导出了 cookies 文件。 |

支持的网站、字幕语言和自动字幕可用性取决于 `yt-dlp` 和视频平台本身。

## 课程管理

课程库可以按专辑管理视频，编辑课程和专辑名称，调整课程顺序，复制来源链接，删除课程记录，并管理本地视频缓存。专辑可以用于课程列表、讲座系列、访谈合集，或者任何长期学习项目。

## AI 学习材料

字幕可用后，Course Navigator 可以按选择的输出语言生成学习材料：

- 导览：前置知识、思考提示、复习建议和快速导读。
- 大纲：带时间戳的可导航结构。
- 解读：按主要学习块展开的解释性笔记。
- 详解：更完整、更适合细读的文本版本。

每个部分都可以单独重新生成，所以只需要刷新效果不满意的部分。

## ASR 校正

ASR 校正工作台用于处理自动语音识别生成的字幕。它使用和主工作台相同的模型档案库。

![ASR 校正工作台](docs/images/course-navigator-asr-correction.jpg)

你可以：

- 直接编辑字幕文本，
- 添加术语、人名、产品名和常见 ASR 错误作为附加参考信息，
- 生成定点 AI 校正建议，
- 并排查看原文和修改后预览，
- 在高亮修改上悬停查看理由、证据，并直接接受或拒绝，
- 在右侧建议区集中审阅所有建议，
- 按置信度排序，
- 一键接受高于指定置信度的建议，
- 在开启选项后自动保存已接受的修改，
- 在手动编辑或接受一轮建议后再次执行 AI 校正，
- 在需要外部证据时开启 Tavily、官方 Firecrawl 或自托管 Firecrawl 搜索校验。

接受后的修改可以保存回视频工作台，主字幕列表会使用校正后的字幕。

## 手动启动

推荐使用一键启动。如果你希望分开启动服务：

```bash
uv sync
npm install
npm run dev:api
```

再打开另一个终端运行：

```bash
npm run dev
```

## 隐私与数据

Course Navigator 会把课程记录、学习材料、本地设置和缓存媒体保存在你的电脑上。

当你使用 AI 翻译、课程分析或 ASR 校正时，相关字幕文本和上下文会发送给你配置的模型服务。开启搜索辅助 ASR 校正后，搜索查询会发送给你配置的搜索服务。请把 API Key 保存在自己的电脑上，并选择你信任的服务提供方。
