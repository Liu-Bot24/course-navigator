# Privacy

[中文](#隐私说明) | [English](#privacy-notes)

## 隐私说明

Course Navigator 是本地运行的学习工具。默认情况下，网页应用和 API 都监听在 `127.0.0.1`，项目不包含由维护者运营的云端服务，也不包含产品分析或遥测上报。

### 本地保存的数据

Course Navigator 会在你的电脑上保存：

- 课程资料 Workspace：课程记录、字幕、AI 学习材料、导入的视频文件和下载的视频缓存。
- 本地运行数据目录：字幕提取文件、ASR 中间文件、本地设置和任务过程文件。
- 你配置的 API Key、模型地址、搜索服务地址、在线 ASR 服务地址等本地配置。

这些文件由你本机管理。请不要把包含 API Key、cookies、私有视频或课程资料的目录分享给不可信的人。

### 发送到外部服务的数据

只有在你启用对应功能时，Course Navigator 才会把数据发送到外部服务：

- 视频提取和下载会访问你输入的视频页面，并可能按你的选择使用浏览器登录状态或 cookies 文件。
- AI 翻译、学习材料生成和 ASR 校正会把相关字幕文本、课程标题、视频元数据和你提供的参考信息发送给你配置的模型服务。
- 在线 ASR 会把从视频中提取的音频片段发送给你配置的语音识别服务。
- 搜索辅助 ASR 校正会把搜索查询发送给你配置的 Tavily 或 Firecrawl 服务。

请只处理你有权使用的视频、字幕和课程资料，并选择你信任的模型、ASR 和搜索服务提供方。

### 删除数据

你可以在课程库里删除课程。删除课程会移除该课程记录和相关视频缓存。本地运行数据目录中的过程文件也可以由你在本机删除；删除后，相关过程缓存会丢失，但应用可以继续启动并重新生成需要的文件。

## Privacy Notes

Course Navigator is a locally run study tool. By default, the web app and API listen on `127.0.0.1`. The project does not include a hosted service operated by the maintainer, product analytics, or telemetry reporting.

### Data Stored Locally

Course Navigator stores these files on your machine:

- Course workspace: course records, subtitles, AI study material, imported video files, and downloaded video caches.
- Local runtime data directory: subtitle extraction files, ASR work files, local settings, and task work files.
- Local configuration such as API keys, model endpoints, search endpoints, and online ASR endpoints.

You control these files on your own machine. Do not share directories that contain API keys, cookies, private videos, or course material with people you do not trust.

### Data Sent To External Services

Course Navigator sends data to external services only when you enable the related feature:

- Video extraction and download access the video page you entered and may use browser login state or a cookies file when you choose that mode.
- AI translation, study generation, and ASR correction send relevant transcript text, course titles, video metadata, and your reference notes to the model provider you configured.
- Online ASR sends extracted audio segments to the speech-to-text provider you configured.
- Search-assisted ASR correction sends search queries to the Tavily or Firecrawl service you configured.

Only process videos, subtitles, and course material you have the right to use, and choose model, ASR, and search providers you trust.

### Deleting Data

You can delete a course from the course library. Deleting a course removes the course record and related video cache. You can also delete the local runtime data directory on your machine; process caches will be lost, but the app can start again and recreate needed files.
