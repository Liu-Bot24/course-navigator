# Security

[中文](#安全说明) | [English](#security-notes)

## 安全说明

Course Navigator 是本地运行的应用，会处理 API Key、cookies、视频文件、字幕和学习材料。请只在你信任的电脑和网络环境中运行它。

### 报告安全问题

如果你发现安全漏洞，请不要在公开 Issue 中贴出可利用细节。优先使用 GitHub 的私有漏洞报告功能；如果仓库没有开启该功能，请通过维护者的 GitHub 资料页联系维护者，并只提供必要的复现摘要，等确认安全渠道后再发送完整细节。

报告时请尽量包含：

- 受影响的功能或接口。
- 复现步骤。
- 可能造成的影响。
- 你已经确认的版本或提交。

### 使用建议

- 不要把 API Key、cookies 文件、私有视频或课程 Workspace 分享给不可信的人。
- 如果你怀疑 API Key、cookies 或本地设置文件已经泄露，请立即在对应服务中轮换密钥或退出相关登录状态。
- 只导入和处理你有权访问的视频、字幕和课程资料。
- 浏览器登录状态和 cookies 文件可能让 `yt-dlp` 访问你的私有课程页面；只在可信环境中使用这些模式。

## Security Notes

Course Navigator is a local app that can handle API keys, cookies, video files, subtitles, and study material. Run it only on machines and networks you trust.

### Reporting A Vulnerability

If you find a vulnerability, please do not post exploitable details in a public issue. Prefer GitHub private vulnerability reporting. If it is not enabled for this repository, contact the maintainer through the maintainer's GitHub profile with a short summary, then share full details after a safe reporting channel is confirmed.

Please include:

- The affected feature or endpoint.
- Reproduction steps.
- Potential impact.
- The version or commit you tested.

### Safe Use

- Do not share API keys, cookies files, private videos, or course workspaces with people you do not trust.
- If you suspect an API key, cookies file, or local settings file was exposed, rotate the affected secret or sign out of the related service.
- Only import and process videos, subtitles, and course material you have the right to access.
- Browser login and cookies-file modes may let `yt-dlp` access private course pages; use those modes only in trusted environments.
