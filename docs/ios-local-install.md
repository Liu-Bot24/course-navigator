# iPhone / iPad 真机安装说明

这个分支在 Course Navigator 主分支的基础上增加了一个原生 SwiftUI App。App 不内置 Python、Node、ffmpeg 或 yt-dlp；课程库、视频处理、字幕提取、ASR 和学习地图生成仍由电脑端后端完成。

## 最短路径

1. 安装完整 Xcode，第一次打开时完成许可、组件安装和 Apple Account 登录提示。
2. 连接你的 iPhone 或 iPad，解锁设备，并在设备上选择信任这台电脑。
3. 在设备上打开 Developer Mode。通常路径是：设置 -> 隐私与安全性 -> Developer Mode，然后按提示重启。
4. 在仓库根目录运行 `bash scripts/ios-device-preflight.sh`，检查 Xcode、iOS 工程配置、局域网地址和已连接设备。
5. 预检看到设备后，运行 `bash scripts/ios-install-device.sh` 构建并安装 App。
6. App 装好后，运行 `bash scripts/start-mobile-backend.sh` 启动电脑端后端，再在 App 里选择扫描到的后端，或填写脚本打印的局域网地址。

## 电脑端后端

手机访问电脑后端时，电脑端不能只监听 `127.0.0.1`。使用：

```bash
bash scripts/start-mobile-backend.sh
```

脚本会用 `0.0.0.0:18000` 启动 API，并打印当前可用的局域网地址。iOS App 里填写的地址格式类似：

```text
http://<脚本打印的局域网 IP>:18000
```

不要把 `0.0.0.0:18000` 填进 iOS App；它只是电脑后端的监听地址，不是手机能访问的目标地址。也不要使用 `169.254.*` 或 `fe80:*` 这类链路本地地址。

脚本也会用 Bonjour 广播 `_coursenav._tcp`。iOS App 会自动扫描同一局域网里的 Course Navigator 后端；如果扫描到了，直接点设备即可保存并连接。扫描不到时再手动填写脚本打印的 URL。

如果手滑粘贴成 `http://<局域网 IP>:18000/api`、`http://<局域网 IP>:18000/api/health` 或其它 `/api/...` 接口地址，App 会自动按后端根地址处理。非 `/api` 开头的路径会被拒绝，请改填电脑后端的根地址。

## 真机安装

打开工程：

```bash
open ios/CourseNavigatorMobile.xcodeproj
```

也可以直接用脚本安装：

```bash
bash scripts/ios-install-device.sh
```

脚本使用 Xcode 里的 Apple Account 做自动签名，并允许 Xcode 在需要时注册当前连接的调试设备。如果 Xcode 还没有登录账号或还没选 Personal Team，预检会显示 `Development team: not set`，安装可能在签名阶段失败。此时打开工程，在 Signing & Capabilities 里选择你的 Personal Team 后再运行脚本。

如果只连接了一台设备，脚本会自动选择它。如果同时连接了多台设备，脚本会先列出设备并退出，避免装错目标。此时可以指定其中一台：

```bash
COURSE_NAVIGATOR_IOS_DEVICE_ID=设备ID bash scripts/ios-install-device.sh
```

也可以明确要求安装到所有已连接设备：

```bash
COURSE_NAVIGATOR_IOS_INSTALL_ALL=1 bash scripts/ios-install-device.sh
```

如果 Xcode 的个人账号需要指定 Team ID 或 Bundle ID，可以这样传入：

```bash
COURSE_NAVIGATOR_IOS_TEAM_ID=你的TeamID \
COURSE_NAVIGATOR_IOS_BUNDLE_ID=com.yourname.coursenavigator.mobile \
bash scripts/ios-install-device.sh
```

在 Xcode 中手动运行时，选择 `CourseNavigatorMobile` target：

- Signing & Capabilities 里选择你的 Personal Team。
- Bundle Identifier 如果和个人账号冲突，可改成只属于你的值。
- 选择连接的 iPhone 或 iPad 作为运行目标。
- 点击 Run。

## 已知边界

- 这是本地调试安装，不是 App Store / TestFlight 发布版。
- 如果使用免费 Personal Team，安装有效期和设备信任会受 Apple 的个人调试限制影响。
- iOS App 访问局域网 HTTP 后端需要 Local Network 权限和 ATS 例外，工程里已经配置。
- iOS 端填写的电脑/NAS 文件路径，必须是电脑端后端能访问的路径，不是 iPhone/iPad 本机路径。
