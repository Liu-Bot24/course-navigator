import AVKit
import SwiftUI
import UniformTypeIdentifiers

struct CourseDetail: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openURL) private var openURL
    @State private var showingVideoSource = false
    @State private var showingRename = false
    @State private var showingDeleteConfirmation = false
    @State private var showingRemoveDeviceCacheConfirmation = false
    @State private var showingCoursePackageExporter = false
    @State private var coursePackageDocument = CoursePackageDocument()
    @State private var coursePackageFilename = "course-navigator.course-nav.json"
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
                            isLocalMode: model.isLocalMode,
                            canCacheVideo: model.canCacheVideoToDevice(item),
                            isLoading: model.isLoading || model.isCachingDeviceVideo,
                            cacheVideo: { cacheVideoToDevice(item) },
                            onPlaybackTimeChange: { itemID, seconds, force in
                                savePlaybackTime(seconds, for: itemID, force: force)
                            }
                        )
                        CourseHeader(
                            item: item,
                            showingVideoSource: $showingVideoSource,
                            showingRename: $showingRename,
                            showingDeleteConfirmation: $showingDeleteConfirmation,
                            showingRemoveDeviceCacheConfirmation: $showingRemoveDeviceCacheConfirmation,
                            canCacheVideo: model.canCacheVideoToDevice(item),
                            hasDeviceVideoCache: model.hasDeviceVideoCache(for: item),
                            isLocalMode: model.isLocalMode,
                            isCachingDeviceVideo: model.isCachingDeviceVideo,
                            cacheVideo: cacheVideoToDevice,
                            openSource: openSource,
                            exportCourse: exportCoursePackage
                        )

                        if let job = model.activeJob {
                            JobProgressView(job: job)
                        }

                        StudyContentView(
                            item: item,
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
                    Text("会删除电脑后端课程记录，以及后端 Workspace/下载缓存中的课程视频；本地视频缓存和外部/NAS 原始文件不会被删除。")
                }
                .confirmationDialog("移除 \(MobileDeviceText.localCacheTitle)？", isPresented: $showingRemoveDeviceCacheConfirmation, titleVisibility: .visible) {
                    Button("移除缓存", role: .destructive) {
                        removeDeviceCache(item)
                    }
                    Button("取消", role: .cancel) {}
                } message: {
                    Text("只删除当前设备上的视频副本，课程资料、字幕和学习地图会保留。")
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

    private func cacheVideoToDevice(_ item: CourseItem) {
        Task {
            await model.cacheVideoToDevice(item)
        }
    }

    private func removeDeviceCache(_ item: CourseItem) {
        player?.pause()
        player = nil
        currentPlaybackTime = 0
        model.removeDeviceVideoCache(item)
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
    @Environment(\.scenePhase) private var scenePhase
    var item: CourseItem
    var playbackURL: URL?
    var resumeTime: Double?
    @Binding var player: AVPlayer?
    @Binding var currentTime: Double
    var isLocalMode: Bool
    var canCacheVideo: Bool
    var isLoading: Bool
    var cacheVideo: () -> Void
    var onPlaybackTimeChange: (String, Double, Bool) -> Void
    @State private var timeObserver = PlayerTimeObserver()
    @State private var observedItemID: String?
    @State private var floatingSubtitleMode: FloatingSubtitleMode = .hidden
    @State private var showingFullScreenVideo = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let player {
                VideoPlayer(player: player) {
                    VideoSubtitleOverlay(cue: activeSubtitleCue, mode: floatingSubtitleMode)
                }
                    .frame(minHeight: 220)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                VideoPlaybackStatus(currentTime: currentTime, duration: item.duration)
                VideoLearningControls(
                    canSeek: true,
                    seekBackward: { seek(by: -15) },
                    restart: { seek(to: 0) },
                    seekForward: { seek(by: 15) }
                )
                VideoViewingControls(
                    subtitleMode: $floatingSubtitleMode,
                    hasSubtitles: hasFloatingSubtitles,
                    showFullScreen: { showingFullScreenVideo = true }
                )
            } else {
                VStack(spacing: 12) {
                    ContentUnavailableView(
                        "当前没有可直接播放的视频",
                        systemImage: "video.slash",
                        description: Text(emptyVideoDescription)
                    )
                    if canCacheVideo {
                        Button {
                            cacheVideo()
                        } label: {
                            Label(MobileDeviceText.cacheButtonTitle, systemImage: "arrow.down.circle")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(isLoading)
                    }
                }
                .frame(minHeight: 220)
                .frame(maxWidth: .infinity)
            }
        }
        .fullScreenCover(isPresented: $showingFullScreenVideo) {
            if let player {
                FullScreenVideoView(
                    item: item,
                    player: player,
                    currentTime: $currentTime,
                    subtitleMode: $floatingSubtitleMode
                )
            }
        }
        .task(id: playbackIdentity) {
            saveCurrentPlaybackPosition(force: true)
            player?.pause()
            timeObserver.invalidate()
            let initialTime = sanitizedResumeTime
            currentTime = initialTime
            observedItemID = item.id
            if let playbackURL {
                let nextPlayer = AVPlayer(url: playbackURL)
                player = nextPlayer
                if initialTime > 1 {
                    let time = CMTime(seconds: initialTime, preferredTimescale: 600)
                    nextPlayer.seek(to: time, toleranceBefore: .zero, toleranceAfter: .zero)
                }
                timeObserver.observe(nextPlayer) { seconds in
                    currentTime = seconds
                    onPlaybackTimeChange(item.id, seconds, false)
                }
            } else {
                player = nil
                currentTime = 0
            }
        }
        .onDisappear {
            saveCurrentPlaybackPosition(force: true)
            player?.pause()
            timeObserver.invalidate()
        }
        .onChange(of: scenePhase) { _, phase in
            guard phase != .active else { return }
            saveCurrentPlaybackPosition(force: true)
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

    private var emptyVideoDescription: String {
        if isLocalMode {
            return "本地模式只播放当前设备已缓存的视频；这门课还没有本地视频缓存。"
        }
        return canCacheVideo
            ? "这门课还没有 \(MobileDeviceText.localCacheTitle)。缓存后离线也可以播放。"
            : "可以为课程绑定电脑/NAS 上的视频文件，或在电脑端准备可播放的视频源。"
    }

    private var hasFloatingSubtitles: Bool {
        !item.transcript.isEmpty || item.study?.translatedTranscript.isEmpty == false
    }

    private var activeSubtitleCue: FloatingSubtitleCue? {
        FloatingSubtitleCue.make(for: item, at: currentTime)
    }

    private func seek(by delta: Double) {
        seek(to: currentTime + delta)
    }

    private func seek(to seconds: Double) {
        guard let player else { return }
        let clamped = clampedPlaybackTime(seconds)
        currentTime = clamped
        onPlaybackTimeChange(item.id, clamped, true)
        let time = CMTime(seconds: clamped, preferredTimescale: 600)
        player.seek(to: time, toleranceBefore: .zero, toleranceAfter: .zero)
    }

    private func saveCurrentPlaybackPosition(force: Bool) {
        guard player != nil, let observedItemID else { return }
        onPlaybackTimeChange(observedItemID, currentTime, force)
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

enum FloatingSubtitleMode: String, CaseIterable, Identifiable {
    case hidden
    case source
    case translated
    case bilingual

    var id: String { rawValue }

    var title: String {
        switch self {
        case .hidden: "关闭"
        case .source: "原文"
        case .translated: "译文"
        case .bilingual: "双语"
        }
    }
}

struct FloatingSubtitleCue {
    var source: String?
    var translated: String?

    static func make(for item: CourseItem, at time: Double) -> FloatingSubtitleCue? {
        let sourceSegment = item.transcript.activeSegment(at: time)
        let translatedSegments = item.study?.translatedTranscript ?? []
        let translatedSegment = translatedSegments.activeSegment(at: time)
            ?? sourceSegment.flatMap { translatedSegments.nearestSegment(to: $0.start) }
        let cue = FloatingSubtitleCue(source: sourceSegment?.text, translated: translatedSegment?.text)
        return cue.source == nil && cue.translated == nil ? nil : cue
    }

    func lines(for mode: FloatingSubtitleMode) -> [String] {
        switch mode {
        case .hidden:
            []
        case .source:
            source.map { [$0] } ?? []
        case .translated:
            translated.map { [$0] } ?? []
        case .bilingual:
            [source, translated].compactMap { $0 }
        }
    }
}

struct VideoSubtitleOverlay: View {
    var cue: FloatingSubtitleCue?
    var mode: FloatingSubtitleMode
    var placement: VideoSubtitleOverlayPlacement = .inline

    var body: some View {
        Group {
            if let cue, !cue.lines(for: mode).isEmpty {
                switch placement {
                case .inline:
                    inlineSubtitle(lines: cue.lines(for: mode))
                case let .fullScreen(videoSize):
                    fullScreenSubtitle(lines: cue.lines(for: mode), videoSize: videoSize)
                }
            }
        }
        .allowsHitTesting(false)
    }

    private func inlineSubtitle(lines: [String]) -> some View {
        VStack {
            Spacer()
            subtitleCard(lines: lines, isFullScreen: false)
                .padding(.horizontal, 24)
                .padding(.bottom, 18)
        }
    }

    private func fullScreenSubtitle(lines: [String], videoSize: CGSize?) -> some View {
        GeometryReader { proxy in
            let videoRect = fittedVideoRect(in: proxy.size, videoSize: videoSize)
            let bottomOffset = min(max(videoRect.height * 0.12, 56), 112)
            subtitleCard(lines: lines, isFullScreen: true)
                .frame(maxWidth: min(videoRect.width - 48, proxy.size.width * 0.78))
                .position(x: videoRect.midX, y: videoRect.maxY - bottomOffset)
        }
    }

    private func subtitleCard(lines: [String], isFullScreen: Bool) -> some View {
        VStack(spacing: isFullScreen ? 6 : 5) {
            ForEach(Array(lines.enumerated()), id: \.offset) { _, line in
                Text(line)
                    .font((isFullScreen ? Font.title3 : Font.body).weight(.semibold))
                    .multilineTextAlignment(.center)
                    .foregroundStyle(.white)
                    .shadow(color: .black.opacity(0.9), radius: 2, x: 0, y: 1)
            }
        }
        .padding(.horizontal, isFullScreen ? 18 : 16)
        .padding(.vertical, isFullScreen ? 11 : 10)
        .background(.black.opacity(0.58), in: RoundedRectangle(cornerRadius: 8))
    }

    private func fittedVideoRect(in containerSize: CGSize, videoSize: CGSize?) -> CGRect {
        let fallbackAspectRatio = 16.0 / 9.0
        let sourceSize = videoSize ?? CGSize(width: fallbackAspectRatio, height: 1)
        let videoWidth = max(sourceSize.width, 1)
        let videoHeight = max(sourceSize.height, 1)
        let videoAspectRatio = videoWidth / videoHeight
        let containerAspectRatio = max(containerSize.width, 1) / max(containerSize.height, 1)

        if containerAspectRatio > videoAspectRatio {
            let fittedWidth = containerSize.height * videoAspectRatio
            return CGRect(
                x: (containerSize.width - fittedWidth) / 2,
                y: 0,
                width: fittedWidth,
                height: containerSize.height
            )
        }

        let fittedHeight = containerSize.width / videoAspectRatio
        return CGRect(
            x: 0,
            y: (containerSize.height - fittedHeight) / 2,
            width: containerSize.width,
            height: fittedHeight
        )
    }
}

enum VideoSubtitleOverlayPlacement {
    case inline
    case fullScreen(videoSize: CGSize?)
}

struct VideoViewingControls: View {
    @Binding var subtitleMode: FloatingSubtitleMode
    var hasSubtitles: Bool
    var showFullScreen: () -> Void

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
            showFullScreen()
        } label: {
            Label("全屏", systemImage: "arrow.up.left.and.arrow.down.right")
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(.bordered)

        FloatingSubtitleMenu(subtitleMode: $subtitleMode, hasSubtitles: hasSubtitles)
    }
}

struct FloatingSubtitleMenu: View {
    @Binding var subtitleMode: FloatingSubtitleMode
    var hasSubtitles: Bool

    var body: some View {
        Menu {
            ForEach(FloatingSubtitleMode.allCases) { mode in
                Button {
                    subtitleMode = mode
                } label: {
                    if subtitleMode == mode {
                        Label(mode.title, systemImage: "checkmark")
                    } else {
                        Text(mode.title)
                    }
                }
            }
        } label: {
            Label("字幕浮层：\(subtitleMode.title)", systemImage: "captions.bubble")
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(.bordered)
        .disabled(!hasSubtitles)
    }
}

struct FullScreenVideoView: View {
    @Environment(\.dismiss) private var dismiss
    var item: CourseItem
    var player: AVPlayer
    @Binding var currentTime: Double
    @Binding var subtitleMode: FloatingSubtitleMode

    var body: some View {
        ZStack(alignment: .topTrailing) {
            Color.black.ignoresSafeArea()
            VideoPlayer(player: player) {
                VideoSubtitleOverlay(
                    cue: FloatingSubtitleCue.make(for: item, at: currentTime),
                    mode: subtitleMode,
                    placement: .fullScreen(videoSize: presentationSize)
                )
            }
            .ignoresSafeArea()

            HStack(spacing: 10) {
                FloatingSubtitleMenu(subtitleMode: $subtitleMode, hasSubtitles: hasSubtitles)
                    .fixedSize(horizontal: true, vertical: false)
                Button {
                    dismiss()
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.title2)
                }
                .buttonStyle(.bordered)
                .tint(.white)
            }
            .padding()
        }
    }

    private var hasSubtitles: Bool {
        !item.transcript.isEmpty || item.study?.translatedTranscript.isEmpty == false
    }

    private var presentationSize: CGSize? {
        guard let size = player.currentItem?.presentationSize, size.width > 0, size.height > 0 else {
            return nil
        }
        return size
    }
}

private extension Array where Element == TranscriptSegment {
    func activeSegment(at time: Double) -> TranscriptSegment? {
        first { segment in
            time >= segment.start && time < Swift.max(segment.end, segment.start + 0.5)
        }
    }

    func nearestSegment(to start: Double) -> TranscriptSegment? {
        self.min { left, right in
            abs(left.start - start) < abs(right.start - start)
        }
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
    @Binding var showingRemoveDeviceCacheConfirmation: Bool
    var canCacheVideo: Bool
    var hasDeviceVideoCache: Bool
    var isLocalMode: Bool
    var isCachingDeviceVideo: Bool
    var cacheVideo: (CourseItem) -> Void
    var openSource: (CourseItem) -> Void
    var exportCourse: (CourseItem) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(item.displayTitle)
                .font(.title2.weight(.semibold))
                .fixedSize(horizontal: false, vertical: true)

            ViewThatFits(in: .horizontal) {
                HStack(spacing: 8) {
                    statusBadges
                }
                VStack(alignment: .leading, spacing: 6) {
                    statusBadges
                }
            }

            if let oneLine = item.study?.oneLine, !oneLine.isEmpty {
                Text(oneLine)
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }

            ViewThatFits(in: .horizontal) {
                HStack(spacing: 10) {
                    primaryActions(expands: false)
                    Spacer()
                    moreActions(expands: false)
                }
                VStack(spacing: 10) {
                    primaryActions(expands: true)
                    moreActions(expands: true)
                }
            }
        }
    }

    @ViewBuilder
    private var statusBadges: some View {
        StatusBadge(text: videoStatusText, color: videoStatusColor)
        if item.transcript.isEmpty {
            StatusBadge(text: "无字幕", color: .orange)
        } else {
            StatusBadge(text: "\(item.transcript.count) 条字幕", color: .green)
        }
        if item.study != nil {
            StatusBadge(text: "已生成学习地图", color: .purple)
        }
    }

    private var videoStatusText: String {
        if isLocalMode {
            return hasDeviceVideoCache ? "本地视频缓存" : "仅本地资料"
        }
        return item.videoSourceType?.label ?? "在线视频"
    }

    private var videoStatusColor: Color {
        if isLocalMode {
            return hasDeviceVideoCache ? .green : .secondary
        }
        return .blue
    }

    private func primaryActions(expands: Bool) -> some View {
        let maxWidth: CGFloat? = expands ? .infinity : nil
        return HStack(spacing: 10) {
            Button {
                showingVideoSource = true
            } label: {
                Label("视频源", systemImage: "link")
                    .frame(maxWidth: maxWidth)
            }
            .buttonStyle(.bordered)
            .disabled(isLocalMode)

            Button {
                cacheVideo(item)
            } label: {
                Label(cacheButtonTitle, systemImage: "arrow.down.circle")
                    .frame(maxWidth: maxWidth)
            }
            .buttonStyle(.bordered)
            .disabled(!canCacheVideo || isCachingDeviceVideo)
        }
    }

    private var cacheButtonTitle: String {
        if isCachingDeviceVideo { return "缓存中" }
        return hasDeviceVideoCache ? "重新缓存" : MobileDeviceText.cacheButtonTitle
    }

    private func moreActions(expands: Bool) -> some View {
        let maxWidth: CGFloat? = expands ? .infinity : nil
        return Menu {
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
            .disabled(isLocalMode)

            Button {
                openSource(item)
            } label: {
                Label("打开源链接", systemImage: "safari")
            }
            .disabled(isLocalMode || MobileURLNormalizer.normalizedHTTPURLString(item.sourceURL) == nil)

            Button(role: .destructive) {
                showingRemoveDeviceCacheConfirmation = true
            } label: {
                Label("移除本地缓存", systemImage: "xmark.bin")
            }
            .disabled(!hasDeviceVideoCache)

            Button(role: .destructive) {
                showingDeleteConfirmation = true
            } label: {
                Label("删除课程", systemImage: "trash")
            }
            .disabled(isLocalMode)
        } label: {
            Label("更多", systemImage: "ellipsis.circle")
                .frame(maxWidth: maxWidth)
        }
        .buttonStyle(.bordered)
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
