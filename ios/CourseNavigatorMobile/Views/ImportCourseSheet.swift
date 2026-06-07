import SwiftUI
import UniformTypeIdentifiers

struct ImportCourseSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @State private var url = ""
    @State private var mode: ExtractMode = .browser
    @State private var subtitleSource: TranscriptSource = .subtitles
    @State private var showingPackageImporter = false
    @State private var showingCookieTextSheet = false
    @State private var cookiesPath = ""
    @State private var cookieSaveMessage: String?
    private static let maxCoursePackageBytes = 20 * 1024 * 1024

    var body: some View {
        NavigationStack {
            Form {
                Section("视频链接") {
                    TextField("YouTube、Bilibili 或课程页面 URL", text: $url, axis: .vertical)
                        .urlInputHints()
                        .lineLimit(2...4)
                }

                Section("电脑上的视频") {
                    ForEach(LocalVideoImportMode.allCases) { importMode in
                        Button {
                            Task {
                                let importedCount = await model.importComputerVideos(mode: importMode)
                                if importedCount > 0 { dismiss() }
                            }
                        } label: {
                            Label(importMode.label, systemImage: importMode.systemImage)
                        }
                        .disabled(model.isLoading)
                        Text(importMode.help)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }

                Section("课程包") {
                    Button {
                        showingPackageImporter = true
                    } label: {
                        Label("导入课程包", systemImage: "doc.badge.plus")
                    }
                    .disabled(model.isLoading)
                    Text("从 Files 选择 Course Navigator 课程包 JSON，手机只读取包内容，导入仍由电脑后端完成。")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Section("提取方式") {
                    Picker("登录", selection: $mode) {
                        ForEach(ExtractMode.mobileChoices) { mode in
                            Text(mode.label).tag(mode)
                        }
                    }
                    .adaptiveSegmentedPickerStyle()
                    if mode == .cookies {
                        TextField("电脑后端 cookies.txt 路径", text: $cookiesPath, axis: .vertical)
                            .lineLimit(1...3)
                        Button {
                            cookieSaveMessage = nil
                            showingCookieTextSheet = true
                        } label: {
                            Label("填写 Cookie", systemImage: "key")
                        }
                        Text("Cookie 会保存到电脑后端的数据目录，手机只负责提交文本。")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        if let cookieSaveMessage {
                            Text(cookieSaveMessage)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    Picker("字幕", selection: $subtitleSource) {
                        ForEach([TranscriptSource.subtitles, .onlineASR, .asr]) { source in
                            Text(source.label).tag(source)
                        }
                    }
                    .adaptiveSegmentedPickerStyle()
                    if let onlineASRReadinessMessage {
                        Label(onlineASRReadinessMessage, systemImage: "exclamationmark.triangle")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }

                if let job = model.activeJob {
                    Section("任务") {
                        ProgressView(value: Double(job.progress), total: 100) {
                            Text(job.message)
                        }
                    }
                }
            }
            .navigationTitle("导入课程")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("关闭") { dismiss() }
                }
                ToolbarItemGroup(placement: .confirmationAction) {
                    if usesCompactToolbarActions {
                        Menu {
                            Button {
                                previewCourse()
                            } label: {
                                Label("预览", systemImage: "eye")
                            }
                            Button {
                                extractCourse()
                            } label: {
                                Label("提取", systemImage: "tray.and.arrow.down")
                            }
                        } label: {
                            Label("操作", systemImage: "ellipsis.circle")
                        }
                        .disabled(!canSubmit)
                    } else {
                        Button("预览") {
                            previewCourse()
                        }
                        .disabled(!canSubmit)
                        Button("提取") {
                            extractCourse()
                        }
                        .disabled(!canSubmit)
                    }
                }
            }
        }
        .fileImporter(
            isPresented: $showingPackageImporter,
            allowedContentTypes: [.json],
            allowsMultipleSelection: false
        ) { result in
            handlePackageImport(result)
        }
        .sheet(isPresented: $showingCookieTextSheet) {
            CookieTextSheet(cookiesPath: $cookiesPath, message: $cookieSaveMessage)
        }
    }

    private var canSubmit: Bool {
        !model.isLoading
            && normalizedVideoURL != nil
            && (mode != .cookies || activeCookiesPath != nil)
            && isSubtitleSourceReady
    }

    private var usesCompactToolbarActions: Bool {
        horizontalSizeClass == .compact
    }

    private var activeCookiesPath: String? {
        let trimmed = cookiesPath.trimmingCharacters(in: .whitespacesAndNewlines)
        return mode == .cookies && !trimmed.isEmpty ? trimmed : nil
    }

    private var normalizedVideoURL: String? {
        MobileURLNormalizer.normalizedHTTPURLString(url)
    }

    private var isSubtitleSourceReady: Bool {
        subtitleSource != .onlineASR || isOnlineASRReady
    }

    private var isOnlineASRReady: Bool {
        guard let onlineASRSettings = model.onlineASRSettings else { return true }
        return onlineASRSettings.isReady
    }

    private var onlineASRReadinessMessage: String? {
        guard subtitleSource == .onlineASR, !isOnlineASRReady else { return nil }
        return "在线 ASR 还未配置，请在后端设备中查看。"
    }

    private func previewCourse() {
        Task {
            guard let requestURL = normalizedVideoURL else { return }
            await model.previewCourse(
                url: requestURL,
                mode: mode,
                subtitleSource: subtitleSource,
                cookiesPath: activeCookiesPath
            )
        }
    }

    private func extractCourse() {
        Task {
            guard let requestURL = normalizedVideoURL else { return }
            await model.extractCourse(
                url: requestURL,
                mode: mode,
                subtitleSource: subtitleSource,
                cookiesPath: activeCookiesPath
            )
            if model.errorMessage == nil { dismiss() }
        }
    }

    private func handlePackageImport(_ result: Result<[URL], Error>) {
        do {
            guard let url = try result.get().first else { return }
            let shouldStopAccessing = url.startAccessingSecurityScopedResource()
            defer {
                if shouldStopAccessing {
                    url.stopAccessingSecurityScopedResource()
                }
            }
            let values = try url.resourceValues(forKeys: [.fileSizeKey])
            if let fileSize = values.fileSize, fileSize > Self.maxCoursePackageBytes {
                model.errorMessage = "课程包超过 20MB，请先在电脑端导入。"
                return
            }
            guard let data = try readBoundedPackageData(from: url) else { return }
            Task {
                let importedCount = await model.importCoursePackage(data: data)
                if importedCount > 0 { dismiss() }
            }
        } catch {
            model.errorMessage = error.localizedDescription
        }
    }

    private func readBoundedPackageData(from url: URL) throws -> Data? {
        let file = try FileHandle(forReadingFrom: url)
        defer { try? file.close() }
        let data = try file.read(upToCount: Self.maxCoursePackageBytes + 1) ?? Data()
        guard data.count <= Self.maxCoursePackageBytes else {
            model.errorMessage = "课程包超过 20MB，请先在电脑端导入。"
            return nil
        }
        return data
    }
}

struct CookieTextSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @Binding var cookiesPath: String
    @Binding var message: String?
    @State private var cookieText = ""

    var body: some View {
        NavigationStack {
            Form {
                Section("Cookie 内容") {
                    TextEditor(text: $cookieText)
                        .frame(minHeight: 180)
                        .plainTextInputHints()
                    Text("可粘贴 cookies.txt、浏览器插件导出的 JSON，或请求头里的 Cookie 内容。")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("填写 Cookie")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("保存") {
                        Task {
                            if let path = await model.saveCookieText(cookieText) {
                                cookiesPath = path
                                message = "Cookie 已保存"
                                dismiss()
                            }
                        }
                    }
                    .disabled(cookieText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.isLoading)
                }
            }
        }
    }
}
