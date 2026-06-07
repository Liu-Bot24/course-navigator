# Course Navigator iOS / iPadOS 本地安装

这个版本是本机自用的原生 SwiftUI App，不内嵌网页，也不打包 Python、Node、ffmpeg 或 yt-dlp。iPhone / iPad 只负责轻量前端，课程库、视频路径、字幕提取、ASR、学习地图生成仍由电脑上的 Course Navigator 后端完成。

## 需要你亲自准备

- 在这台 Mac 安装完整 Xcode。当前机器已检测到 Xcode 26.5 和 iOS 26.5 runtime。
- 第一次打开 Xcode，登录 Apple Account，并同意 Xcode 许可。没有付费开发者账号也可以用 Personal Team 调试安装到自己的设备。
- 把 iPhone 16 Pro 和 iPad mini 连接到 Mac，解锁设备，在设备上点“信任此电脑”。
- 在设备上打开 Developer Mode。通常路径是：设置 -> 隐私与安全性 -> Developer Mode，然后按提示重启。
- 本机硬盘空间紧张时，在 Xcode 的 Settings -> Locations 里把 Derived Data 设到外置 SSD，例如 `/Volumes/Acer SSD N5000/CodexBuilds/XcodeDerivedData`。
- 如果只是检查准备状态，先运行 `bash scripts/ios-device-preflight.sh`。它会打印当前磁盘、Xcode、局域网地址和真机连接状态；没有检测到设备时不会开始构建。
  预检脚本也会默认拒绝把推荐 DerivedData 路径设成本机磁盘，避免检查阶段误创建本机缓存目录。
  预检会显示 Xcode first launch status；如果不是 ready，先打开 Xcode 并处理许可、登录或组件安装提示。

## 电脑端后端

手机访问电脑后端时，电脑端不能只监听 `127.0.0.1`。使用：

```bash
bash scripts/start-mobile-backend.sh
```

脚本会用 `0.0.0.0:18000` 启动 API，并打印当前 Mac 的局域网地址。iOS App 里填写的地址格式类似：

```text
http://<脚本打印的局域网 IP>:18000
```

如果环境变量把 `COURSE_NAVIGATOR_API_HOST` 设成 `127.0.0.1` 或 `localhost`，移动端启动脚本会直接退出；iPhone/iPad 只能连接 `0.0.0.0` 或局域网地址监听的电脑后端。

如果手滑粘贴成 `http://<局域网 IP>:18000/api`、`http://<局域网 IP>:18000/api/health` 或其它 `/api/...` 接口地址，App 会自动按后端根地址处理。非 `/api` 开头的路径会被拒绝，请改填脚本打印的电脑根地址。

局域网 IP 可能会随 Wi-Fi、路由器或重启变化。iOS App 里的“后端设备”应以 `scripts/start-mobile-backend.sh` 或 `scripts/ios-device-preflight.sh` 当次打印的 URL 为准。
如果脚本打印多个地址，优先选和 iPhone/iPad 在同一 Wi-Fi 或同一局域网网段的地址；括号里的 `en0`、`en5` 等是 Mac 网络接口名。
不要把 `0.0.0.0:18000` 填进 iOS App；它只是电脑后端的监听地址，不是手机能访问的目标地址。也不要使用 `169.254.*` 或 `fe80:*` 这类链路本地地址，通常说明当前网络没有拿到可用局域网地址。

脚本也会用 macOS 自带 Bonjour 广播 `_coursenav._tcp`。iOS App 的“后端设备”会自动扫描同一局域网里的 Course Navigator 后端；如果扫描到了，直接点设备即可保存并连接。扫描不到时再手动填写脚本打印的 URL。

## 构建工程

安装 Xcode 后，在仓库根目录运行：

```bash
open ios/CourseNavigatorMobile.xcodeproj
```

也可以先跑一次轻量检查，它只打印磁盘、Xcode、后端地址和已连接设备状态，不会启动模拟器或写入大构建缓存：

```bash
bash scripts/ios-device-preflight.sh
```

如果设备已经连接、已解锁并信任这台 Mac，可以直接用脚本构建并安装到真机。脚本会先检测设备；没有检测到 iPhone/iPad 时会在构建前退出，不会写入大 DerivedData 缓存：

```bash
bash scripts/ios-install-device.sh
```

脚本使用 Xcode 里的 Apple Account 做自动签名，并允许 Xcode 在需要时注册当前连接的调试设备；如果 Xcode 还没有登录账号或还没选 Personal Team，脚本会在签名阶段失败，此时打开工程在 Signing & Capabilities 里选择你的 Personal Team 后再运行。
如果 Xcode 还没完成首次启动任务，安装脚本会在构建前退出；先打开 Xcode，完成许可、登录或组件安装提示后再重试。
如果签名或 provisioning 失败，脚本会在 `xcodebuild` 原始错误后打印排查提示。优先检查 Apple Account、Personal Team、Bundle Identifier 是否冲突，以及设备是否已解锁、信任此 Mac 并开启 Developer Mode。

如果只连接了一台设备，脚本会自动选择它。如果 iPhone 16 Pro 和 iPad mini 同时连接，脚本会先列出设备并退出，避免装错目标。此时可以指定其中一台：

```bash
COURSE_NAVIGATOR_IOS_DEVICE_ID=设备ID bash scripts/ios-install-device.sh
```

也可以明确要求安装到所有已连接设备：

```bash
COURSE_NAVIGATOR_IOS_INSTALL_ALL=1 bash scripts/ios-install-device.sh
```

默认 DerivedData 会写到外置 SSD：

```text
/Volumes/Acer SSD N5000/CodexBuilds/course-navigator-ios-device-install
```

安装脚本会在构建前检查这个目录所在磁盘的剩余空间，默认要求至少 8GiB 可用。如果 `COURSE_NAVIGATOR_IOS_DERIVED_DATA` 被误设成本机路径，脚本会直接退出，避免把大构建缓存写进本机硬盘。只有在你明确接受这个风险时，才用：

```bash
COURSE_NAVIGATOR_ALLOW_LOCAL_DERIVED_DATA=1 \
COURSE_NAVIGATOR_IOS_DERIVED_DATA=/你确认有足够空间的路径 \
bash scripts/ios-install-device.sh
```

如果 Xcode 的个人账号需要指定 Team ID 或 Bundle ID，可以这样传入：

```bash
COURSE_NAVIGATOR_IOS_TEAM_ID=你的TeamID \
COURSE_NAVIGATOR_IOS_BUNDLE_ID=com.yourname.coursenavigator.mobile \
bash scripts/ios-install-device.sh
```

在 Xcode 中选择 `CourseNavigatorMobile` target：

- Signing & Capabilities 里选择你的 Personal Team。
- Bundle Identifier 如果和个人账号冲突，可改成只属于你的值。
- 选择连接的 iPhone 或 iPad mini 作为运行目标。
- 点击 Run。

## 已知边界

- 这是本地调试安装，不是 App Store / TestFlight 发布版。
- 如果使用免费 Personal Team，安装有效期和设备信任会受 Apple 的个人调试限制影响。
- iOS App 访问局域网 HTTP 后端需要 Local Network 权限和 ATS 例外，工程里已经配置。
- iOS 端填写的电脑/NAS 文件路径，必须是电脑后端能访问的路径，不是 iPhone/iPad 本机路径。
