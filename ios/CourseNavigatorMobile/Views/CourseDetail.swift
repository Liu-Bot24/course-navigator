import AVKit
import SwiftUI
import UniformTypeIdentifiers

struct CourseDetail: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openURL) private var openURL
    @State private var showingVideoSource = false
    @State private var showingRename = false
    @State private var showingDeleteConfirmation = false
    @State private var showingRemoveCacheConfirmation = false
    @State private var showingCoursePackageExporter = false
    @State private var coursePackageDocument = CoursePackageDocument()
    @State private var coursePackageFilename = "course-navigator.course-nav.json"
    @State private var outputLanguage: OutputLanguage = .zhCN
    @State private var studySection: StudySection = .all
    @State private var detailLevel: StudyDetailLevel = .faithful
    @State private var player: AVPlayer?
    @State private var currentPlaybackTime: Double = 0
    @State private var playbackPositionStore = PlaybackPositionStore()

    var body: some View {
        Group {
            if let item = model.selectedCourse {
                ScrollView(.vertical) {
                    VStack(alignment: .leading, spacing: 18) {
                        CourseVideoPanel(
                            item: item,
                            playbackURL: model.playbackURL(for: item),
                            resumeTime: playbackPositionStore.position(for: item.id),
                            player: $player,
                            currentTime: $currentPlaybackTime,
                            onPlaybackTimeChange: { seconds, force in
                                savePlaybackTime(seconds, for: item.id, force: force)
                            }
                        )
                        CourseHeader(
                            item: item,
                            showingVideoSource: $showingVideoSource,
                            showingRename: $showingRename,
                            showingDeleteConfirmation: $showingDeleteConfirmation,
                            showingRemoveCacheConfirmation: $showingRemoveCacheConfirmation,
                            cacheVideo: cacheVideo,
                            openSource: openSource,
                            exportCourse: exportCoursePackage
                        )

                        if let job = model.activeJob {
                            JobProgressView(job: job)
                        }

                        StudyActionPanel(
                            outputLanguage: $outputLanguage,
                            studySection: $studySection,
                            detailLevel: $detailLevel
                        )

                        StudyContentView(
                            item: item,
                            outputLanguage: outputLanguage,
                            currentTime: activePlaybackTime,
                            seekTo: activeSeekAction
                        )
                    }
                    .padding()
                }
                .navigationTitle(item.displayTitle)
                .inlineNavigationTitle()
                .sheet(isPresented: $showingVideoSource) {
                    VideoSourceSheet(item: item)
                }
                .sheet(isPresented: $showingRename) {
                    RenameCourseSheet(item: item)
                }
                .confirmationDialog("删除这门课程？", isPresented: $showingDeleteConfirmation, titleVisibility: .visible) {
                    Button("删除课程", role: .destructive) {
                        Task { await model.deleteCourse(item) }
                    }
                    Button("取消", role: .cancel) {}
                } message: {
                    Text("会删除电脑后端课程记录和已缓存的课程文件，外部/NAS 原始文件不会被删除。")
                }
                .confirmationDialog("移除电脑缓存？", isPresented: $showingRemoveCacheConfirmation, titleVisibility: .visible) {
                    Button("移除缓存", role: .destructive) {
                        removeComputerCache(item)
                    }
                    Button("取消", role: .cancel) {}
                } message: {
                    Text("只删除电脑 Workspace 中这个课程的本地视频副本，字幕和学习地图会保留。")
                }
                .fileExporter(
                    isPresented: $showingCoursePackageExporter,
                    document: coursePackageDocument,
                    contentType: .json,
                    defaultFilename: coursePackageFilename
                ) { result in
                    if case let .failure(error) = result {
                        model.errorMessage = error.localizedDescription
                    }
                }
            } else {
                ContentUnavailableView(
                    "选择一门课程",
                    systemImage: "play.rectangle",
                    description: Text("在左侧课程库中选择，或导入新的视频链接。")
                )
            }
        }
    }

    private func seekTo(_ seconds: Double) {
        guard let player else { return }
        let clampedSeconds = max(0, seconds)
        let time = CMTime(seconds: clampedSeconds, preferredTimescale: 600)
        currentPlaybackTime = clampedSeconds
        if let item = model.selectedCourse {
            savePlaybackTime(clampedSeconds, for: item.id, force: true)
        }
        player.seek(to: time, toleranceBefore: .zero, toleranceAfter: .zero)
        player.play()
    }

    private var activeSeekAction: ((Double) -> Void)? {
        guard player != nil else { return nil }
        return { seconds in
            seekTo(seconds)
        }
    }

    private var activePlaybackTime: Double? {
        player == nil ? nil : currentPlaybackTime
    }

    private func cacheVideo(_ item: CourseItem) {
        Task {
            await model.cacheVideo(item)
        }
    }

    private func removeComputerCache(_ item: CourseItem) {
        player?.pause()
        player = nil
        currentPlaybackTime = 0
        Task {
            await model.removeComputerCache(item)
        }
    }

    private func openSource(_ item: CourseItem) {
        guard
            let urlString = MobileURLNormalizer.normalizedHTTPURLString(item.sourceURL),
            let url = URL(string: urlString)
        else { return }
        openURL(url)
    }

    private func exportCoursePackage(_ item: CourseItem) {
        guard !item.transcript.isEmpty else {
            model.errorMessage = "这门课程还没有字幕，不能导出课程包。"
            return
        }
        do {
            let package = CourseSharePackage(exporting: item)
            let data = try JSONEncoder.courseNavigator.encode(package)
            coursePackageDocument = CoursePackageDocument(data: data)
            coursePackageFilename = coursePackageFilename(for: item)
            showingCoursePackageExporter = true
        } catch {
            model.errorMessage = error.localizedDescription
        }
    }

    private func coursePackageFilename(for item: CourseItem) -> String {
        let title = item.displayTitle.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        var scalars = String.UnicodeScalarView()
        var previousWasSeparator = false
        for scalar in title.unicodeScalars {
            if CharacterSet.alphanumerics.contains(scalar) {
                scalars.append(scalar)
                previousWasSeparator = false
            } else if !previousWasSeparator {
                scalars.append("-")
                previousWasSeparator = true
            }
            if scalars.count >= 60 { break }
        }
        let slug = String(scalars).trimmingCharacters(in: CharacterSet(charactersIn: "-"))
        return "\(slug.isEmpty ? "course-navigator" : slug).course-nav.json"
    }

    private func savePlaybackTime(_ seconds: Double, for itemID: String, force: Bool = false) {
        playbackPositionStore.save(seconds, for: itemID, force: force)
    }
}

struct CoursePackageDocument: FileDocument {
    static var readableContentTypes: [UTType] { [.json] }

    var data: Data

    init(data: Data = Data()) {
        self.data = data
    }

    init(configuration: ReadConfiguration) throws {
        self.data = configuration.file.regularFileContents ?? Data()
    }

    func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper {
        FileWrapper(regularFileWithContents: data)
    }
}

struct CourseVideoPanel: View {
    var item: CourseItem
    var playbackURL: URL?
    var resumeTime: Double?
    @Binding var player: AVPlayer?
    @Binding var currentTime: Double
    var onPlaybackTimeChange: (Double, Bool) -> Void
    @State private var timeObserver = PlayerTimeObserver()

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let player {
                VideoPlayer(player: player)
                    .frame(minHeight: 220)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                VideoPlaybackStatus(currentTime: currentTime, duration: item.duration)
                VideoLearningControls(
                    canSeek: true,
                    seekBackward: { seek(by: -15) },
                    restart: { seek(to: 0) },
                    seekForward: { seek(by: 15) }
                )
            } else {
                ContentUnavailableView(
                    "当前没有可直接播放的视频",
                    systemImage: "video.slash",
                    description: Text("可以在电脑后端缓存视频，或为课程绑定电脑/NAS 上的视频文件。")
                )
                .frame(minHeight: 220)
            }
        }
        .task(id: playbackIdentity) {
            timeObserver.invalidate()
            let initialTime = sanitizedResumeTime
            currentTime = initialTime
            if let playbackURL {
                let nextPlayer = AVPlayer(url: playbackURL)
                player = nextPlayer
                if initialTime > 1 {
                    let time = CMTime(seconds: initialTime, preferredTimescale: 600)
                    nextPlayer.seek(to: time, toleranceBefore: .zero, toleranceAfter: .zero)
                }
                timeObserver.observe(nextPlayer) { seconds in
                    currentTime = seconds
                    onPlaybackTimeChange(seconds, false)
                }
            } else {
                player = nil
                currentTime = 0
            }
        }
        .onDisappear {
            if player != nil {
                onPlaybackTimeChange(currentTime, true)
            }
            player?.pause()
            timeObserver.invalidate()
        }
    }

    private var playbackIdentity: String {
        "\(item.id)|\(playbackURL?.absoluteString ?? "none")"
    }

    private var sanitizedResumeTime: Double {
        guard let resumeTime, resumeTime.isFinite else { return 0 }
        let positiveTime = max(0, resumeTime)
        if let duration = item.duration, duration > 0 {
            return min(positiveTime, max(0, duration - 1))
        }
        return positiveTime
    }

    private func seek(by delta: Double) {
        seek(to: currentTime + delta)
    }

    private func seek(to seconds: Double) {
        guard let player else { return }
        let clamped = clampedPlaybackTime(seconds)
        currentTime = clamped
        onPlaybackTimeChange(clamped, true)
        let time = CMTime(seconds: clamped, preferredTimescale: 600)
        player.seek(to: time, toleranceBefore: .zero, toleranceAfter: .zero)
    }

    private func clampedPlaybackTime(_ seconds: Double) -> Double {
        guard seconds.isFinite else { return 0 }
        let positive = max(0, seconds)
        if let duration = item.duration, duration > 0 {
            return min(positive, duration)
        }
        return positive
    }
}

struct PlaybackPositionStore {
    private static let storageKey = "course-navigator-mobile-playback-positions"
    private var positions: [String: Double]
    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        let rawPositions = defaults.dictionary(forKey: Self.storageKey) ?? [:]
        self.positions = rawPositions.compactMapValues { value in
            if let number = value as? NSNumber {
                return number.doubleValue
            }
            return value as? Double
        }
    }

    func position(for itemID: String) -> Double? {
        positions[itemID]
    }

    mutating func save(_ seconds: Double, for itemID: String, force: Bool = false) {
        let position = max(0, seconds)
        guard position.isFinite else { return }
        if !force, let existingPosition = positions[itemID], abs(existingPosition - position) < 5 {
            return
        }
        positions[itemID] = position
        defaults.set(positions, forKey: Self.storageKey)
    }
}

struct VideoPlaybackStatus: View {
    var currentTime: Double
    var duration: Double?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ProgressView(value: progress, total: 1)
            HStack {
                Label(formatTime(currentTime), systemImage: "clock")
                Spacer()
                if let duration {
                    Text(formatTime(duration))
                }
            }
            .font(.caption.monospacedDigit())
            .foregroundStyle(.secondary)
        }
    }

    private var progress: Double {
        guard let duration, duration > 0 else { return 0 }
        return min(1, max(0, currentTime / duration))
    }
}

struct VideoLearningControls: View {
    var canSeek: Bool
    var seekBackward: () -> Void
    var restart: () -> Void
    var seekForward: () -> Void

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 8) {
                controls
            }
            VStack(spacing: 8) {
                controls
            }
        }
    }

    @ViewBuilder
    private var controls: some View {
        Button {
            seekBackward()
        } label: {
            Label("后退 15 秒", systemImage: "gobackward.15")
                .lineLimit(1)
                .minimumScaleFactor(0.85)
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(.bordered)
        .disabled(!canSeek)

        Button {
            restart()
        } label: {
            Label("回到开头", systemImage: "backward.end")
                .lineLimit(1)
                .minimumScaleFactor(0.85)
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(.bordered)
        .disabled(!canSeek)

        Button {
            seekForward()
        } label: {
            Label("前进 15 秒", systemImage: "goforward.15")
                .lineLimit(1)
                .minimumScaleFactor(0.85)
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(.bordered)
        .disabled(!canSeek)
    }
}

final class PlayerTimeObserver {
    private weak var player: AVPlayer?
    private var token: Any?

    func observe(_ player: AVPlayer, onTick: @MainActor @Sendable @escaping (Double) -> Void) {
        invalidate()
        self.player = player
        let interval = CMTime(seconds: 0.5, preferredTimescale: 600)
        token = player.addPeriodicTimeObserver(forInterval: interval, queue: .main) { time in
            guard time.seconds.isFinite else { return }
            Task { @MainActor in
                onTick(max(0, time.seconds))
            }
        }
    }

    func invalidate() {
        if let token, let player {
            player.removeTimeObserver(token)
        }
        token = nil
        player = nil
    }

    deinit {
        invalidate()
    }
}

struct CourseHeader: View {
    var item: CourseItem
    @Binding var showingVideoSource: Bool
    @Binding var showingRename: Bool
    @Binding var showingDeleteConfirmation: Bool
    @Binding var showingRemoveCacheConfirmation: Bool
    var cacheVideo: (CourseItem) -> Void
    var openSource: (CourseItem) -> Void
    var exportCourse: (CourseItem) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(item.displayTitle)
                .font(.title2.weight(.semibold))
                .fixedSize(horizontal: false, vertical: true)

            HStack(spacing: 8) {
                StatusBadge(text: item.videoSourceType?.label ?? "在线视频", color: .blue)
                if item.transcript.isEmpty {
                    StatusBadge(text: "无字幕", color: .orange)
                } else {
                    StatusBadge(text: "\(item.transcript.count) 条字幕", color: .green)
                }
                if item.study != nil {
                    StatusBadge(text: "已生成学习地图", color: .purple)
                }
            }

            if let oneLine = item.study?.oneLine, !oneLine.isEmpty {
                Text(oneLine)
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }

            HStack {
                Button {
                    showingVideoSource = true
                } label: {
                    Label("视频源", systemImage: "link")
                }
                .buttonStyle(.bordered)

                Button {
                    cacheVideo(item)
                } label: {
                    Label("缓存", systemImage: "arrow.down.circle")
                }
                .buttonStyle(.bordered)
                .disabled(!item.canCacheToComputer)

                Spacer()

                Menu {
                    Button {
                        exportCourse(item)
                    } label: {
                        Label("导出课程包", systemImage: "square.and.arrow.up")
                    }
                    .disabled(item.transcript.isEmpty)

                    Button {
                        showingRename = true
                    } label: {
                        Label("编辑信息", systemImage: "pencil")
                    }

                    Button {
                        openSource(item)
                    } label: {
                        Label("打开源链接", systemImage: "safari")
                    }
                    .disabled(MobileURLNormalizer.normalizedHTTPURLString(item.sourceURL) == nil)

                    Button(role: .destructive) {
                        showingRemoveCacheConfirmation = true
                    } label: {
                        Label("移除电脑缓存", systemImage: "xmark.bin")
                    }
                    .disabled(!item.canRemoveComputerCache)

                    Button(role: .destructive) {
                        showingDeleteConfirmation = true
                    } label: {
                        Label("删除课程", systemImage: "trash")
                    }
                } label: {
                    Label("更多", systemImage: "ellipsis.circle")
                }
                .buttonStyle(.bordered)
            }
        }
    }
}

struct RenameCourseSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    var item: CourseItem
    @State private var title: String
    @State private var translatedTitle: String
    @State private var collectionGroupTitle: String
    @State private var collectionTitle: String
    @State private var courseIndexText: String

    init(item: CourseItem) {
        self.item = item
        _title = State(initialValue: item.title)
        _translatedTitle = State(initialValue: item.study?.translatedTitle ?? "")
        _collectionGroupTitle = State(initialValue: item.collectionGroupTitle ?? "")
        _collectionTitle = State(initialValue: item.collectionTitle ?? "")
        _courseIndexText = State(initialValue: Self.formatCourseIndex(item.courseIndex))
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("课程标题") {
                    TextField("标题", text: $title, axis: .vertical)
                        .lineLimit(2...4)
                    TextField("标题译名", text: $translatedTitle, axis: .vertical)
                        .lineLimit(1...3)
                }

                Section("专辑归档") {
                    TextField("上层分类", text: $collectionGroupTitle)
                    TextField("所属专辑", text: $collectionTitle)
                    TextField("课程序号", text: $courseIndexText)
                        .decimalInputHints()
                    Text("留空“所属专辑”会把课程移到未归档，并清空课程序号。")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("课程信息")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("保存") {
                        Task {
                            await model.updateCourseDetails(
                                item,
                                title: title,
                                translatedTitle: translatedTitle,
                                collectionGroupTitle: collectionGroupTitle,
                                collectionTitle: collectionTitle,
                                courseIndexText: courseIndexText
                            )
                            if model.errorMessage == nil { dismiss() }
                        }
                    }
                    .disabled(title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.isLoading)
                }
            }
        }
    }

    private static func formatCourseIndex(_ value: Double?) -> String {
        guard let value else { return "" }
        if value.rounded() == value {
            return String(Int(value))
        }
        return String(value)
    }
}

struct StudyActionPanel: View {
    @Environment(AppModel.self) private var model
    @Binding var outputLanguage: OutputLanguage
    @Binding var studySection: StudySection
    @Binding var detailLevel: StudyDetailLevel
    @State private var extractMode: ExtractMode = .browser
    @State private var subtitleSource: TranscriptSource = .subtitles
    @State private var showingExtractConfirmation = false
    @State private var showingSubtitleImporter = false
    @State private var showingSubtitleImportConfirmation = false
    @State private var showingCookieTextSheet = false
    @State private var cookiesPath = ""
    @State private var cookieSaveMessage: String?

    private static var subtitleFileTypes: [UTType] {
        [.plainText, .text] + ["srt", "vtt", "ass", "ssa", "txt"].compactMap { UTType(filenameExtension: $0) }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("字幕")
                .font(.headline)
            Picker("登录", selection: $extractMode) {
                ForEach(ExtractMode.mobileChoices) { mode in
                    Text(mode.label).tag(mode)
                }
            }
            if extractMode == .cookies {
                TextField("电脑后端 cookies.txt 路径", text: $cookiesPath, axis: .vertical)
                    .lineLimit(1...3)
                Button {
                    cookieSaveMessage = nil
                    showingCookieTextSheet = true
                } label: {
                    Label("填写 Cookie", systemImage: "key")
                }
                Text("用于当前课程重新提取字幕；Cookie 文本会保存到电脑后端。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                if let cookieSaveMessage {
                    Text(cookieSaveMessage)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            Picker("来源", selection: $subtitleSource) {
                ForEach([TranscriptSource.subtitles, .onlineASR, .asr]) { source in
                    Text(source.label).tag(source)
                }
            }
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 10) {
                    extractButton
                    importSubtitleButton
                }
                VStack(spacing: 10) {
                    extractButton
                    importSubtitleButton
                }
            }

            Divider()

            Text("学习地图")
                .font(.headline)
            Picker("输出语言", selection: $outputLanguage) {
                ForEach(OutputLanguage.allCases) { language in
                    Text(language.label).tag(language)
                }
            }
            Picker("内容", selection: $studySection) {
                ForEach(StudySection.allCases) { section in
                    Text(section.label).tag(section)
                }
            }
            .pickerStyle(.segmented)
            Picker("详细程度", selection: $detailLevel) {
                ForEach(StudyDetailLevel.allCases) { level in
                    Text(level.label).tag(level)
                }
            }
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 10) {
                    translateButton
                    generateStudyButton
                }
                VStack(spacing: 10) {
                    translateButton
                    generateStudyButton
                }
            }
        }
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 8))
        .confirmationDialog("重新提取字幕？", isPresented: $showingExtractConfirmation, titleVisibility: .visible) {
            Button("重新提取字幕", role: .destructive) {
                startExtract()
            }
            Button("取消", role: .cancel) {}
        } message: {
            Text("会刷新当前字幕；如果新字幕不同，已有学习地图也可能需要重新生成。")
        }
        .confirmationDialog("导入字幕文件？", isPresented: $showingSubtitleImportConfirmation, titleVisibility: .visible) {
            Button("导入并覆盖字幕", role: .destructive) {
                showingSubtitleImporter = true
            }
            Button("取消", role: .cancel) {}
        } message: {
            Text("会用选择的字幕文件替换当前字幕；已有译文会清空，学习地图可能需要重新生成。")
        }
        .fileImporter(
            isPresented: $showingSubtitleImporter,
            allowedContentTypes: Self.subtitleFileTypes,
            allowsMultipleSelection: false
        ) { result in
            handleSubtitleImport(result)
        }
        .sheet(isPresented: $showingCookieTextSheet) {
            CookieTextSheet(cookiesPath: $cookiesPath, message: $cookieSaveMessage)
        }
    }

    private var extractButton: some View {
        Button {
            guard let item = model.selectedCourse else { return }
            if item.transcript.isEmpty {
                startExtract()
            } else {
                showingExtractConfirmation = true
            }
        } label: {
            Label(model.selectedCourse?.transcript.isEmpty == false ? "重新提取字幕" : "提取字幕", systemImage: "captions.bubble")
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(.bordered)
        .disabled(!canExtractSubtitles)
    }

    private var importSubtitleButton: some View {
        Button {
            guard let item = model.selectedCourse else { return }
            if item.transcript.isEmpty {
                showingSubtitleImporter = true
            } else {
                showingSubtitleImportConfirmation = true
            }
        } label: {
            Label("导入字幕文件", systemImage: "doc.badge.plus")
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(.bordered)
        .disabled(model.selectedCourse == nil || model.isLoading)
    }

    private var canExtractSubtitles: Bool {
        guard let item = model.selectedCourse else { return false }
        return !model.isLoading
            && !item.sourceURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && (extractMode != .cookies || activeCookiesPath != nil)
    }

    private var activeCookiesPath: String? {
        let trimmed = cookiesPath.trimmingCharacters(in: .whitespacesAndNewlines)
        return extractMode == .cookies && !trimmed.isEmpty ? trimmed : nil
    }

    private func startExtract() {
        guard let item = model.selectedCourse else { return }
        Task {
            await model.extractSubtitles(
                for: item,
                mode: extractMode,
                subtitleSource: subtitleSource,
                cookiesPath: activeCookiesPath
            )
        }
    }

    private func handleSubtitleImport(_ result: Result<[URL], Error>) {
        do {
            guard let item = model.selectedCourse, let url = try result.get().first else { return }
            let shouldStopAccessing = url.startAccessingSecurityScopedResource()
            defer {
                if shouldStopAccessing {
                    url.stopAccessingSecurityScopedResource()
                }
            }
            let values = try url.resourceValues(forKeys: [.fileSizeKey])
            if let fileSize = values.fileSize, fileSize > 5 * 1024 * 1024 {
                model.errorMessage = "字幕文件超过 5MB，请先在电脑端处理。"
                return
            }
            let data = try Data(contentsOf: url)
            Task {
                await model.importSubtitleFile(for: item, data: data, filename: url.lastPathComponent)
            }
        } catch {
            model.errorMessage = error.localizedDescription
        }
    }

    private var translateButton: some View {
        Button {
            Task {
                await model.translateTranscript(outputLanguage: outputLanguage)
            }
        } label: {
            Label(model.selectedCourse?.study?.translatedTranscript.isEmpty == false ? "重新翻译字幕" : "翻译字幕", systemImage: "languages")
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(.bordered)
        .disabled(model.selectedCourse?.transcript.isEmpty != false || model.isLoading)
    }

    private var generateStudyButton: some View {
        Button {
            Task {
                await model.generateStudy(
                    section: studySection,
                    outputLanguage: outputLanguage,
                    detailLevel: detailLevel
                )
            }
        } label: {
            Label(model.selectedCourse?.study == nil ? "生成学习地图" : "重新生成", systemImage: "sparkles")
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(.borderedProminent)
        .disabled(model.selectedCourse?.transcript.isEmpty != false || model.isLoading)
    }
}

struct JobProgressView: View {
    var job: StudyJobStatus

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ProgressView(value: Double(job.progress), total: 100)
            HStack {
                Text(job.message)
                Spacer()
                Text("\(job.progress)%")
            }
            .font(.caption)
            .foregroundStyle(.secondary)
        }
        .padding()
        .background(.bar, in: RoundedRectangle(cornerRadius: 8))
    }
}
