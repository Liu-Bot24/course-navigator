import Foundation
import Network
import Observation

@MainActor
@Observable
final class AppModel {
    private struct ConnectionRefreshToken {
        var id: Int
        var endpointID: UUID?
    }

    var endpoints: [BackendEndpoint]
    var activeEndpointID: UUID?
    var connectionStatus: ConnectionStatus = .unknown
    var courses: [CourseItem] = []
    var selectedCourseID: String?
    var activeJob: StudyJobStatus?
    var modelSettings: ModelSettings?
    var onlineASRSettings: OnlineASRSettings?
    var backendCapabilityError: String?
    var isSyncingCourseLibrary = false
    var isCachingDeviceVideo = false
    var deviceVideoCacheRecords: [DeviceVideoCacheRecord] = []
    var localCourseLibraries: [LocalCourseLibrary] = []
    var isLoading = false
    var errorMessage: String?

    private let store = EndpointStore()
    private let courseCacheStore = CourseCacheStore()
    private let deviceVideoCacheStore = DeviceVideoCacheStore()
    private let networkMonitor = NWPathMonitor()
    private let networkMonitorQueue = DispatchQueue(label: "CourseNavigatorMobile.NetworkPath")
    private var autoSyncedEndpointKeys = Set<String>()
    private var didStartNetworkMonitor = false
    private var lastNetworkPathSatisfied: Bool?
    private var explicitLocalModeEndpointID: UUID?
    private var courseLibrarySyncTask: Task<Void, Never>?
    private var connectionRefreshSequence = 0
    private var isRefreshingAll = false
    private var libraryState = LibraryState()

    init() {
        let stored = store.load()
        let usableStoredEndpoints = Self.normalizedUsableStoredEndpoints(from: stored)
        endpoints = usableStoredEndpoints.isEmpty ? EndpointStore.defaultEndpoints : usableStoredEndpoints
        activeEndpointID = store.loadActiveEndpointID() ?? endpoints.first?.id
        explicitLocalModeEndpointID = store.loadExplicitLocalModeEndpointID()
        let loadedActiveEndpointID = activeEndpointID
        reconcileActiveEndpointSelection()
        reconcileExplicitLocalModeSelection()
        if stored != usableStoredEndpoints {
            store.save(usableStoredEndpoints)
        }
        if activeEndpointID != loadedActiveEndpointID {
            store.saveActiveEndpointID(activeEndpointID)
        }
        refreshLocalCourseLibraryIndex()
        refreshDeviceVideoCacheIndex()
    }

    var activeEndpoint: BackendEndpoint? {
        endpoints.first { $0.id == activeEndpointID } ?? endpoints.first
    }

    var isBackendOnline: Bool {
        if case .online = connectionStatus {
            return true
        }
        return false
    }

    var canShowCourseContent: Bool {
        isBackendOnline || !courses.isEmpty
    }

    var isLocalMode: Bool {
        connectionStatus.isLocal || shouldUseExplicitLocalMode
    }

    private var shouldUseExplicitLocalMode: Bool {
        guard let activeEndpointID else { return false }
        return explicitLocalModeEndpointID == activeEndpointID
    }

    var activeLocalCourseLibrary: LocalCourseLibrary? {
        guard let activeEndpointID else { return nil }
        return localCourseLibraries.first { $0.id == activeEndpointID }
    }

    var canEnterLocalMode: Bool {
        activeEndpointID != nil && (activeLocalCourseLibrary != nil || !courses.isEmpty)
    }

    var selectedCourse: CourseItem? {
        guard let selectedCourseID else { return courses.first }
        return courses.first { $0.id == selectedCourseID }
    }

    var activeDeviceVideoCacheRecords: [DeviceVideoCacheRecord] {
        guard let descriptor = activeEndpointDescriptor else { return [] }
        return deviceVideoCacheRecords
            .filter { $0.endpointKey == descriptor.key }
            .sorted { $0.courseTitle.localizedStandardCompare($1.courseTitle) == .orderedAscending }
    }

    var activeDeviceVideoCacheByteCount: Int64 {
        activeDeviceVideoCacheRecords.reduce(0) { $0 + $1.byteCount }
    }

    var api: CourseAPI? {
        guard let url = activeEndpoint?.normalizedBaseURL else { return nil }
        return CourseAPI(baseURL: url)
    }

    func bootstrap() async {
        startNetworkMonitoringIfNeeded()
        await refreshAll(syncCourseLibraryAfterRefresh: true)
    }

    func selectEndpoint(_ id: UUID?) async {
        invalidateConnectionRefreshes()
        clearExplicitLocalMode()
        activeEndpointID = id
        reconcileActiveEndpointSelection()
        store.saveActiveEndpointID(activeEndpointID)
        clearBackendContent()
        loadCachedCoursesForActiveEndpoint()
        refreshDeviceVideoCacheIndex()
        await refreshAll(syncCourseLibraryAfterRefresh: true)
    }

    func useLocalLibrary(_ endpointID: UUID) {
        cancelCourseLibrarySync()
        invalidateConnectionRefreshes()
        activeEndpointID = endpointID
        reconcileActiveEndpointSelection()
        store.saveActiveEndpointID(activeEndpointID)
        explicitLocalModeEndpointID = activeEndpointID
        store.saveExplicitLocalModeEndpointID(explicitLocalModeEndpointID)
        clearBackendContent()
        let loaded = loadCachedCoursesForActiveEndpoint()
        refreshDeviceVideoCacheIndex()
        if loaded {
            connectionStatus = .local(activeEndpoint?.name ?? "本地课程资料")
        } else {
            connectionStatus = .offline("当前设备没有这台后端的本地课程资料")
        }
    }

    func enterActiveLocalMode() async {
        guard let activeEndpointID else {
            connectionStatus = .offline("请先选择一个后端设备")
            return
        }
        cancelCourseLibrarySync()
        useLocalLibrary(activeEndpointID)
    }

    func useOnlineMode() async {
        cancelCourseLibrarySync()
        let refreshToken = beginConnectionRefresh()
        let endpointID = activeEndpointID
        debugNetwork("useOnlineMode start endpoint=\(activeEndpoint?.baseURL ?? "<none>") explicitLocal=\(shouldUseExplicitLocalMode)")
        guard let api else {
            enterLocalModeForActiveEndpoint(fallbackMessage: "请先配置电脑后端地址")
            errorMessage = "请先配置电脑后端地址"
            debugNetwork("useOnlineMode failed: missing api")
            return
        }

        connectionStatus = .checking
        do {
            let health = try await api.health()
            guard canContinueOnlineModeAttempt(refreshToken, endpointID: endpointID) else { return }
            guard health.ok else {
                enterLocalModeForActiveEndpoint(fallbackMessage: "后端未就绪")
                errorMessage = "后端未就绪，本地模式已保留"
                debugNetwork("useOnlineMode failed: health not ok")
                return
            }
            clearExplicitLocalMode()
            connectionStatus = .online(health.name)
            debugNetwork("useOnlineMode health ok")
            await refreshBackendCapabilities()
            guard canApplyConnectionRefresh(refreshToken) else {
                isLoading = false
                return
            }
            await refreshCourses(
                syncCourseLibraryAfterRefresh: false,
                refreshToken: refreshToken
            )
        } catch {
            guard canContinueOnlineModeAttempt(refreshToken, endpointID: endpointID) else { return }
            enterLocalModeForActiveEndpoint(fallbackMessage: "正在使用本地模式。可以稍后再切回 WiFi 模式。")
            errorMessage = "\(error.localizedDescription)。本地模式已保留。"
            debugNetwork("useOnlineMode failed: \(error.localizedDescription)")
        }
    }

    @discardableResult
    func saveEndpoint(_ endpoint: BackendEndpoint, mergeByBaseURL: Bool = false) -> UUID {
        var endpoint = endpoint
        guard let normalizedBaseURL = endpoint.normalizedBaseURL?.absoluteString else {
            return endpoint.id
        }
        endpoint.baseURL = normalizedBaseURL
        let originalEndpointID = endpoint.id
        if
            mergeByBaseURL,
            let index = endpoints.firstIndex(where: { $0.normalizedBaseURL?.absoluteString == normalizedBaseURL })
        {
            endpoint.id = endpoints[index].id
            endpoints[index] = endpoint
            if originalEndpointID != endpoint.id {
                endpoints.removeAll { $0.id == originalEndpointID }
                if activeEndpointID == originalEndpointID {
                    activeEndpointID = endpoint.id
                }
            }
        } else if let index = endpoints.firstIndex(where: { $0.id == endpoint.id }) {
            endpoints[index] = endpoint
        } else {
            endpoints.append(endpoint)
        }
        if activeEndpointID == nil {
            activeEndpointID = endpoint.id
        }
        reconcileActiveEndpointSelection()
        reconcileExplicitLocalModeSelection()
        persistEndpoints()
        refreshLocalCourseLibraryIndex()
        return endpoint.id
    }

    func deleteEndpoint(_ endpoint: BackendEndpoint) async {
        let wasActiveEndpoint = activeEndpoint?.id == endpoint.id
        endpoints.removeAll { $0.id == endpoint.id }
        if explicitLocalModeEndpointID == endpoint.id {
            explicitLocalModeEndpointID = nil
            store.saveExplicitLocalModeEndpointID(nil)
        }
        if wasActiveEndpoint {
            activeEndpointID = endpoints.first?.id
            clearBackendContent()
            loadCachedCoursesForActiveEndpoint()
            refreshDeviceVideoCacheIndex()
        }
        reconcileActiveEndpointSelection()
        reconcileExplicitLocalModeSelection()
        persistEndpoints()
        refreshLocalCourseLibraryIndex()
        if wasActiveEndpoint {
            await refreshAll(syncCourseLibraryAfterRefresh: true)
        }
    }

    func refreshAll(
        allowExplicitLocalMode: Bool = true,
        syncCourseLibraryAfterRefresh: Bool = false,
        allowOfflineFallback: Bool = true
    ) async {
        if isRefreshingAll {
            return
        }
        isRefreshingAll = true
        defer {
            isRefreshingAll = false
        }
        if allowExplicitLocalMode, shouldUseExplicitLocalMode {
            enterLocalModeForActiveEndpoint(fallbackMessage: "正在使用本地模式。可以在后端设备里选择连接电脑后端。")
            isLoading = false
            return
        }
        if !allowExplicitLocalMode {
            clearExplicitLocalMode()
        }
        let refreshToken = beginConnectionRefresh()
        await checkHealth(refreshToken: refreshToken)
        guard canApplyConnectionRefresh(refreshToken) else {
            isLoading = false
            return
        }
        if allowExplicitLocalMode, shouldUseExplicitLocalMode {
            enterLocalModeForActiveEndpoint(fallbackMessage: "正在使用本地模式。可以在后端设备里选择连接电脑后端。")
            isLoading = false
            return
        }
        guard isBackendOnline else {
            await refreshBackendCapabilities()
            if allowOfflineFallback {
                let loaded = loadCachedCoursesForActiveEndpoint()
                if loaded || !courses.isEmpty {
                    connectionStatus = .local(activeEndpoint?.name ?? "本地课程资料")
                }
            }
            isLoading = false
            return
        }
        await refreshBackendCapabilities()
        guard canApplyConnectionRefresh(refreshToken) else {
            isLoading = false
            return
        }
        await refreshCourses(
            syncCourseLibraryAfterRefresh: syncCourseLibraryAfterRefresh,
            refreshToken: refreshToken
        )
    }

    func refreshAfterForegroundActivation() async {
        guard activeJob == nil, !isLoading, !isRefreshingAll else { return }
        if case .checking = connectionStatus { return }

        await refreshAll()
    }

    private func checkHealth(refreshToken: ConnectionRefreshToken? = nil) async {
        guard let api else {
            connectionStatus = .offline("请先配置电脑后端地址")
            return
        }
        let checkedEndpointID = refreshToken?.endpointID ?? activeEndpointID
        connectionStatus = .checking
        do {
            let health = try await api.health()
            guard canApplyHealthResult(for: checkedEndpointID, refreshToken: refreshToken) else { return }
            connectionStatus = health.ok ? .online(health.name) : .offline("后端未就绪")
        } catch {
            guard canApplyHealthResult(for: checkedEndpointID, refreshToken: refreshToken) else { return }
            connectionStatus = .offline(error.localizedDescription)
        }
    }

    func refreshBackendCapabilities() async {
        guard let api, case .online = connectionStatus else {
            modelSettings = nil
            onlineASRSettings = nil
            backendCapabilityError = nil
            return
        }
        do {
            async let modelSettings = api.modelSettings()
            async let onlineASRSettings = api.onlineASRSettings()
            self.modelSettings = try await modelSettings
            self.onlineASRSettings = try await onlineASRSettings
            backendCapabilityError = nil
        } catch {
            modelSettings = nil
            onlineASRSettings = nil
            backendCapabilityError = error.localizedDescription
        }
    }

    private func refreshCourses(
        syncCourseLibraryAfterRefresh: Bool = false,
        refreshToken: ConnectionRefreshToken? = nil
    ) async {
        guard let api, isBackendOnline else {
            courses = []
            selectedCourseID = nil
            return
        }
        isLoading = true
        defer { isLoading = false }
        do {
            let previousSelectedCourse = selectedCourse
            let refreshedLibraryState = try? await api.libraryState()
            let summaries = try await api.listItemSummaries()
            guard canApplyConnectionRefresh(refreshToken) else { return }
            libraryState = refreshedLibraryState ?? libraryState
            courses = applyLibraryState(to: summaries)
                .sorted(by: courseSort)
            saveCachedCoursesForActiveEndpoint()
            if selectedCourseID == nil {
                selectedCourseID = courses.first?.id
            }
            if let selectedCourseID, !courses.contains(where: { $0.id == selectedCourseID }) {
                self.selectedCourseID = courses.first?.id
            }
            if let selectedCourseID, let previousSelectedCourse, previousSelectedCourse.id == selectedCourseID {
                upsertCourse(previousSelectedCourse)
            }
            await refreshSelectedCourse()
            if syncCourseLibraryAfterRefresh {
                startAutoSyncCourseLibraryIfNeeded()
            }
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
            loadCachedCoursesForActiveEndpoint()
        }
    }

    func refreshSelectedCourse() async {
        guard let api, isBackendOnline, let selectedCourseID else { return }
        do {
            let item = (try await api.item(itemID: selectedCourseID)).applyingLibraryState(libraryState)
            upsertCourse(item)
            saveCachedCoursesForActiveEndpoint()
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func previewCourse(url: String, mode: ExtractMode, subtitleSource: TranscriptSource, cookiesPath: String? = nil) async {
        guard let api else { return }
        await runCourseMutation {
            let request = ExtractRequest(
                url: url,
                mode: mode,
                browser: "chrome",
                cookiesPath: cookiesPath,
                language: "auto",
                subtitleSource: subtitleSource
            )
            let item = try await api.preview(request)
            upsertCourse(item)
            selectedCourseID = item.id
        }
    }

    func extractCourse(url: String, mode: ExtractMode, subtitleSource: TranscriptSource, cookiesPath: String? = nil) async {
        guard let api else { return }
        await runCourseMutation {
            let request = ExtractRequest(
                url: url,
                mode: mode,
                browser: "chrome",
                cookiesPath: cookiesPath,
                language: "auto",
                subtitleSource: subtitleSource
            )
            let job = try await api.startExtractJob(request)
            activeJob = job
            try await poll(jobID: job.jobID, using: api)
        }
    }

    func saveCookieText(_ text: String) async -> String? {
        guard let api else { return nil }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            errorMessage = "Cookie 内容不能为空"
            return nil
        }
        guard trimmed.count <= 200_000 else {
            errorMessage = "Cookie 内容过大，请在电脑端保存 cookies.txt。"
            return nil
        }

        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            let response = try await api.saveCookieText(CookieTextRequest(text: trimmed))
            return response.path
        } catch {
            errorMessage = error.localizedDescription
            return nil
        }
    }

    func extractSubtitles(
        for item: CourseItem,
        mode: ExtractMode,
        subtitleSource: TranscriptSource,
        cookiesPath: String? = nil
    ) async {
        guard let api else { return }
        await runCourseMutation {
            let request = ExtractRequest(
                url: item.sourceURL,
                mode: mode,
                browser: "chrome",
                cookiesPath: cookiesPath,
                language: "auto",
                subtitleSource: subtitleSource
            )
            let job = try await api.startExtractJob(request)
            activeJob = job
            selectedCourseID = item.id
            try await poll(jobID: job.jobID, using: api)
        }
    }

    @discardableResult
    func importComputerVideos(mode: LocalVideoImportMode) async -> Int {
        guard let api else { return 0 }
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            let imported = try await api.importLocalVideosFromPicker(
                request: LocalVideoFilePickerRequest(mode: mode)
            )
            guard !imported.isEmpty else { return 0 }
            for item in imported {
                upsertCourse(item)
            }
            selectedCourseID = imported.first?.id
            return imported.count
        } catch {
            errorMessage = error.localizedDescription
            return 0
        }
    }

    @discardableResult
    func importCoursePackage(data: Data) async -> Int {
        guard let api else { return 0 }
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            let package = try JSONDecoder.courseNavigator.decode(CourseSharePackage.self, from: data)
            let response = try await api.importCoursePackage(package)
            guard !response.items.isEmpty else { return 0 }
            for item in response.items {
                upsertCourse(item)
            }
            selectedCourseID = response.items.first?.id
            return response.items.count
        } catch {
            errorMessage = error.localizedDescription
            return 0
        }
    }

    func importSubtitleFile(for item: CourseItem, data: Data, filename: String) async {
        guard let api else { return }
        guard data.count <= 5 * 1024 * 1024 else {
            errorMessage = "字幕文件超过 5MB，请先在电脑端处理。"
            return
        }
        guard let text = SubtitleTextParser.decodeText(from: data) else {
            errorMessage = "无法读取这个字幕文件的文本编码。"
            return
        }
        let transcript = SubtitleTextParser.parse(text, filename: filename, duration: item.duration)
        guard !transcript.isEmpty else {
            errorMessage = "没有解析到可用字幕。"
            return
        }

        await runCourseMutation {
            let updated = try await api.saveTranscript(
                itemID: item.id,
                request: TranscriptUpdateRequest(transcript: transcript)
            )
            upsertCourse(updated)
            selectedCourseID = updated.id
        }
    }

    func generateStudy(section: StudySection, outputLanguage: OutputLanguage, detailLevel: StudyDetailLevel) async {
        guard let api, let item = selectedCourse else { return }
        await runCourseMutation {
            let job = try await api.startStudyJob(
                itemID: item.id,
                request: StudyRequest(outputLanguage: outputLanguage, section: section, detailLevel: detailLevel)
            )
            activeJob = job
            try await poll(jobID: job.jobID, using: api)
        }
    }

    func translateTranscript(outputLanguage: OutputLanguage) async {
        guard let api, let item = selectedCourse else { return }
        await runCourseMutation {
            let job = try await api.startTranslationJob(
                itemID: item.id,
                request: TranslationRequest(outputLanguage: outputLanguage)
            )
            activeJob = job
            try await poll(jobID: job.jobID, using: api)
        }
    }

    func generateASRCorrectionSuggestions(
        for item: CourseItem,
        outputLanguage: OutputLanguage
    ) async -> [ASRCorrectionSuggestion] {
        guard let api, !item.transcript.isEmpty else { return [] }
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            let job = try await api.startASRCorrectionJob(
                itemID: item.id,
                request: ASRCorrectionRequest(outputLanguage: outputLanguage)
            )
            activeJob = job
            try await poll(jobID: job.jobID, using: api)
            let result = try await api.asrCorrectionResult(jobID: job.jobID)
            return result.suggestions.filter { $0.status == "pending" }
        } catch {
            errorMessage = error.localizedDescription
            activeJob = nil
            return []
        }
    }

    func acceptASRCorrection(_ suggestion: ASRCorrectionSuggestion, itemID: String) async {
        guard let api, let item = courses.first(where: { $0.id == itemID }) else { return }
        guard let transcript = item.transcript.applyingASRCorrection(suggestion) else {
            errorMessage = "这条 ASR 建议无法应用到当前字幕"
            return
        }
        await runCourseMutation {
            let updated = try await api.saveTranscript(
                itemID: itemID,
                request: TranscriptUpdateRequest(transcript: transcript)
            )
            upsertCourse(updated)
            selectedCourseID = updated.id
        }
    }

    func cacheVideo(_ item: CourseItem) async {
        guard let api, item.canCacheToComputer else { return }
        await runCourseMutation {
            let request = backendDownloadRequest(for: item)
            let job = try await api.startDownloadJob(itemID: item.id, request: request)
            activeJob = job
            selectedCourseID = item.id
            try await poll(jobID: job.jobID, using: api)
        }
    }

    func removeComputerCache(_ item: CourseItem) async {
        guard let api, item.canRemoveComputerCache else { return }
        await runCourseMutation {
            let updated = try await api.deleteLocalVideo(itemID: item.id)
            upsertCourse(updated)
            selectedCourseID = updated.id
        }
    }

    func bindVideoSource(input: String, asPath: Bool) async {
        guard let api, let item = selectedCourse else { return }
        let trimmed = input.trimmingCharacters(in: .whitespacesAndNewlines)
        let normalizedInput: String
        if asPath {
            guard !trimmed.isEmpty else {
                errorMessage = "电脑路径不能为空"
                return
            }
            normalizedInput = trimmed
        } else {
            guard let normalizedURL = MobileURLNormalizer.normalizedHTTPURLString(trimmed) else {
                errorMessage = "在线视频链接无效"
                return
            }
            normalizedInput = normalizedURL
        }
        await runCourseMutation {
            let request = VideoSourceBindingRequest(
                sourceType: asPath ? "external" : "remote",
                url: asPath ? nil : normalizedInput,
                path: asPath ? normalizedInput : nil
            )
            let updated = try await api.bindVideoSource(itemID: item.id, request: request)
            upsertCourse(updated)
            selectedCourseID = updated.id
        }
    }

    func bindVideoSourceFromComputerPicker(_ item: CourseItem) async {
        guard let api else { return }
        await runCourseMutation {
            let updated = try await api.bindVideoSourceFromPicker(itemID: item.id)
            upsertCourse(updated)
            selectedCourseID = updated.id
        }
    }

    func importWorkspaceVideoFromComputerPicker(_ item: CourseItem) async {
        guard let api else { return }
        await runCourseMutation {
            let updated = try await api.importWorkspaceVideoFromPicker(itemID: item.id)
            upsertCourse(updated)
            selectedCourseID = updated.id
        }
    }

    func renameCourse(_ item: CourseItem, title: String) async {
        guard let api else { return }
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            errorMessage = "课程标题不能为空"
            return
        }
        await runCourseMutation {
            let updated = try await api.updateItem(itemID: item.id, request: CourseItemUpdate(title: trimmed))
            upsertCourse(updated)
            selectedCourseID = updated.id
        }
    }

    func updateCourseDetails(
        _ item: CourseItem,
        title: String,
        translatedTitle: String,
        collectionGroupTitle: String,
        collectionTitle: String,
        courseIndexText: String
    ) async {
        guard let api else { return }
        let title = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !title.isEmpty else {
            errorMessage = "课程标题不能为空"
            return
        }

        let indexText = courseIndexText.trimmingCharacters(in: .whitespacesAndNewlines)
        let courseIndex: Double?
        if indexText.isEmpty {
            courseIndex = nil
        } else if let parsed = Double(indexText.replacingOccurrences(of: ",", with: ".")), parsed.isFinite {
            courseIndex = parsed
        } else {
            errorMessage = "课程序号必须是数字"
            return
        }

        let collectionTitle = collectionTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        let request = CourseDetailsUpdate(
            title: title,
            translatedTitle: normalizedOptional(translatedTitle),
            collectionGroupTitle: collectionTitle.isEmpty ? nil : normalizedOptional(collectionGroupTitle),
            collectionTitle: collectionTitle.isEmpty ? nil : collectionTitle,
            courseIndex: collectionTitle.isEmpty ? nil : courseIndex,
            sortOrder: collectionTitle.isEmpty ? nil : courseIndex
        )

        await runCourseMutation {
            let updated = try await api.updateItemDetails(itemID: item.id, request: request)
            upsertCourse(updated)
            selectedCourseID = updated.id
        }
    }

    func deleteCourse(_ item: CourseItem) async {
        guard let api else { return }
        await runCourseMutation {
            let response = try await api.deleteItem(itemID: item.id)
            guard response.deleted else {
                throw CourseAPIError.server(message: "课程删除失败")
            }
            courses.removeAll { $0.id == item.id }
            selectedCourseID = courses.first?.id
        }
    }

    func playbackURL(for item: CourseItem) -> URL? {
        if let cached = deviceVideoCacheStore.localVideoURL(for: item, endpoint: activeEndpointDescriptor) {
            return cached
        }
        guard !isLocalMode else { return nil }
        return remotePlaybackURL(for: item)
    }

    func remotePlaybackURL(for item: CourseItem) -> URL? {
        guard !isLocalMode else { return nil }
        if item.hasPlayableLocalVideo, let api {
            return api.videoURL(itemID: item.id)
        }
        if let hls = item.metadata?.hlsManifestURL, let url = URL(string: hls) {
            return url
        }
        if let stream = item.metadata?.streamURL, let url = URL(string: stream) {
            return url
        }
        return nil
    }

    func hasDeviceVideoCache(for item: CourseItem) -> Bool {
        deviceVideoCacheStore.localVideoURL(for: item, endpoint: activeEndpointDescriptor) != nil
    }

    func sortsCategoryBefore(_ left: String, _ right: String) -> Bool {
        libraryState.sortsCategoryBefore(left, right)
    }

    func sortsCollectionBefore(_ left: String, _ right: String) -> Bool {
        libraryState.sortsCollectionBefore(left, right)
    }

    func canCacheVideoToDevice(_ item: CourseItem) -> Bool {
        if item.hasPlayableLocalVideo {
            return remotePlaybackURL(for: item)?.isHTTPOrHTTPS == true
        }
        if item.canCacheToComputer, api != nil, isBackendOnline {
            return true
        }
        guard let url = remotePlaybackURL(for: item) else { return false }
        return url.isHTTPOrHTTPS && !url.isHLSManifest
    }

    func cacheVideoToDevice(_ item: CourseItem) async {
        guard !isLocalMode else {
            errorMessage = "本地模式不会连接电脑后端或网络视频。请切回 WiFi 模式后再缓存。"
            return
        }
        guard let descriptor = activeEndpointDescriptor else {
            errorMessage = "请先连接电脑后端"
            return
        }
        guard let sourceItem = await itemReadyForDeviceVideoCache(item) else {
            if errorMessage == nil {
                errorMessage = "当前课程没有可缓存的视频地址"
            }
            return
        }
        guard let url = remotePlaybackURL(for: sourceItem), url.isHTTPOrHTTPS else {
            errorMessage = "当前课程没有可缓存的视频地址"
            return
        }
        isCachingDeviceVideo = true
        errorMessage = nil
        defer {
            isCachingDeviceVideo = false
            refreshDeviceVideoCacheIndex()
        }
        do {
            _ = try await deviceVideoCacheStore.cacheVideo(item: sourceItem, endpoint: descriptor, remoteURL: url)
        } catch DeviceVideoCacheError.unsupportedFileContainer where sourceItem.canRemoveComputerCache {
            guard let recachedItem = await recacheBackendVideoForDeviceTransfer(sourceItem),
                  let retryURL = remotePlaybackURL(for: recachedItem),
                  retryURL.isHTTPOrHTTPS else {
                if errorMessage == nil {
                    errorMessage = DeviceVideoCacheError.unsupportedFileContainer.localizedDescription
                }
                return
            }
            do {
                _ = try await deviceVideoCacheStore.cacheVideo(item: recachedItem, endpoint: descriptor, remoteURL: retryURL)
            } catch {
                errorMessage = error.localizedDescription
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func removeDeviceVideoCache(_ item: CourseItem) {
        do {
            try deviceVideoCacheStore.removeVideo(item, endpoint: activeEndpointDescriptor)
            refreshDeviceVideoCacheIndex()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func removeDeviceVideoCache(_ record: DeviceVideoCacheRecord) {
        do {
            try deviceVideoCacheStore.removeVideo(record)
            refreshDeviceVideoCacheIndex()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func syncCourseLibrary(allowOnlineConnection: Bool = false) async {
        let returnToLocalModeEndpointID = allowOnlineConnection && shouldUseExplicitLocalMode ? activeEndpointID : nil
        if allowOnlineConnection, shouldUseExplicitLocalMode {
            clearExplicitLocalMode()
            await checkHealth()
        }
        defer {
            if let returnToLocalModeEndpointID {
                useLocalLibrary(returnToLocalModeEndpointID)
            }
        }
        guard let api, isBackendOnline else {
            loadCachedCoursesForActiveEndpoint()
            return
        }
        guard !isSyncingCourseLibrary else { return }
        isSyncingCourseLibrary = true
        defer { isSyncingCourseLibrary = false }

        let descriptor = activeEndpointDescriptor
        do {
            let summaries = try await api.listItemSummaries().sorted(by: courseSort)
            libraryState = (try? await api.libraryState()) ?? libraryState
            let cachedCourses = descriptor.flatMap { try? courseCacheStore.load(endpoint: $0)?.courses } ?? []
            var mergedByID = [String: CourseItem]()
            var failedCount = 0

            for summary in summaries {
                try Task.checkCancellation()
                let current = courses.first { $0.id == summary.id }
                let cached = cachedCourses.first { $0.id == summary.id }
                let existing = richestOfflineCourse(summary, current, cached).applyingLibraryState(libraryState)
                if canReuseSyncedCourse(existing, for: summary) {
                    mergedByID[summary.id] = existing
                    continue
                }
                do {
                    mergedByID[summary.id] = (try await api.item(itemID: summary.id)).applyingLibraryState(libraryState)
                } catch is CancellationError {
                    throw CancellationError()
                } catch {
                    if Task.isCancelled {
                        throw CancellationError()
                    }
                    mergedByID[summary.id] = existing
                    failedCount += 1
                }
            }

            courses = Array(mergedByID.values).sorted(by: courseSort)
            if selectedCourseID == nil || !courses.contains(where: { $0.id == selectedCourseID }) {
                selectedCourseID = courses.first?.id
            }
            saveCachedCoursesForActiveEndpoint(replacingExisting: true)
            errorMessage = failedCount == 0 ? nil : "\(failedCount) 门课程资料暂时没有同步成功"
            if failedCount > 0, let descriptor {
                autoSyncedEndpointKeys.remove(descriptor.key)
            }
        } catch is CancellationError {
            if let descriptor {
                autoSyncedEndpointKeys.remove(descriptor.key)
            }
        } catch {
            if Task.isCancelled {
                if let descriptor {
                    autoSyncedEndpointKeys.remove(descriptor.key)
                }
                return
            }
            errorMessage = error.localizedDescription
            if let descriptor {
                autoSyncedEndpointKeys.remove(descriptor.key)
            }
        }
    }

    private func itemReadyForDeviceVideoCache(_ item: CourseItem) async -> CourseItem? {
        guard !isLocalMode else { return nil }
        if item.hasPlayableLocalVideo {
            return item
        }
        if let url = remotePlaybackURL(for: item), url.isHTTPOrHTTPS, !url.isHLSManifest {
            return item
        }
        if item.canCacheToComputer {
            await cacheBackendVideoForDeviceTransfer(item)
            guard let updated = courses.first(where: { $0.id == item.id }), updated.hasPlayableLocalVideo else {
                return nil
            }
            return updated
        }
        return nil
    }

    private func recacheBackendVideoForDeviceTransfer(_ item: CourseItem) async -> CourseItem? {
        await cacheBackendVideoForDeviceTransfer(item, forceExistingRemoteCache: true)
        guard let updated = courses.first(where: { $0.id == item.id }), updated.hasPlayableLocalVideo else {
            return nil
        }
        return updated
    }

    private func cacheBackendVideoForDeviceTransfer(_ item: CourseItem, forceExistingRemoteCache: Bool = false) async {
        guard let api else { return }
        guard item.canCacheToComputer || (forceExistingRemoteCache && item.canRemoveComputerCache) else { return }
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            let request = backendDownloadRequest(for: item)
            let job = try await api.startDownloadJob(itemID: item.id, request: request)
            activeJob = job
            selectedCourseID = item.id
            try await poll(jobID: job.jobID, using: api)
            await refreshSelectedCourse()
        } catch {
            errorMessage = error.localizedDescription
            activeJob = nil
        }
    }

    private func backendDownloadRequest(for item: CourseItem) -> DownloadRequest {
        if !item.hasPlayableLocalVideo, let url = metadataRemoteVideoURL(for: item) {
            return DownloadRequest(
                url: url.absoluteString,
                mode: .normal,
                browser: "chrome",
                cookiesPath: nil
            )
        }
        return DownloadRequest(
            url: item.sourceURL,
            mode: .browser,
            browser: "chrome",
            cookiesPath: nil
        )
    }

    private func metadataRemoteVideoURL(for item: CourseItem) -> URL? {
        if let stream = item.metadata?.streamURL, let url = URL(string: stream), url.isHTTPOrHTTPS {
            return url
        }
        if let hls = item.metadata?.hlsManifestURL, let url = URL(string: hls), url.isHTTPOrHTTPS {
            return url
        }
        return nil
    }

    private func poll(jobID: String, using api: CourseAPI) async throws {
        while true {
            try Task.checkCancellation()
            try await Task.sleep(for: .seconds(1))
            let job = try await api.job(jobID)
            activeJob = job
            if job.isFinished {
                if job.status == "failed" {
                    throw CourseAPIError.server(message: job.error ?? job.message)
                }
                activeJob = nil
                await refreshCourses(syncCourseLibraryAfterRefresh: false)
                return
            }
        }
    }

    private func runCourseMutation(_ operation: () async throws -> Void) async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            try await operation()
        } catch {
            errorMessage = error.localizedDescription
            activeJob = nil
        }
    }

    private func upsertCourse(_ item: CourseItem) {
        let item = item.applyingLibraryState(libraryState)
        if let index = courses.firstIndex(where: { $0.id == item.id }) {
            courses[index] = item
        } else {
            courses.append(item)
        }
        courses.sort(by: courseSort)
    }

    private func clearBackendContent() {
        courses = []
        selectedCourseID = nil
        activeJob = nil
        libraryState = LibraryState()
        modelSettings = nil
        onlineASRSettings = nil
        backendCapabilityError = nil
        isLoading = false
    }

    private func startNetworkMonitoringIfNeeded() {
        guard !didStartNetworkMonitor else { return }
        didStartNetworkMonitor = true
        networkMonitor.pathUpdateHandler = { [weak self] path in
            let isSatisfied = path.status == .satisfied
            Task { @MainActor [weak self] in
                guard let self else { return }
                guard self.lastNetworkPathSatisfied != isSatisfied else { return }
                self.lastNetworkPathSatisfied = isSatisfied
                if isSatisfied {
                    guard !self.shouldUseExplicitLocalMode else { return }
                    await self.refreshAll(syncCourseLibraryAfterRefresh: true)
                } else {
                    self.cancelCourseLibrarySync()
                    self.enterLocalModeForActiveEndpoint(fallbackMessage: "网络不可用。可以选择本地模式使用当前设备已同步的课程资料。")
                }
            }
        }
        networkMonitor.start(queue: networkMonitorQueue)
    }

    private func enterLocalModeForActiveEndpoint(fallbackMessage: String) {
        let loaded = loadCachedCoursesForActiveEndpoint()
        refreshDeviceVideoCacheIndex()
        if loaded || !courses.isEmpty {
            connectionStatus = .local(activeEndpoint?.name ?? "本地课程资料")
        } else {
            connectionStatus = .offline(fallbackMessage)
        }
    }

    private var activeEndpointDescriptor: EndpointCacheDescriptor? {
        activeEndpoint.flatMap(EndpointCacheDescriptor.init(endpoint:))
    }

    private func startAutoSyncCourseLibraryIfNeeded() {
        guard
            isBackendOnline,
            !shouldUseExplicitLocalMode,
            let descriptor = activeEndpointDescriptor,
            !autoSyncedEndpointKeys.contains(descriptor.key)
        else {
            return
        }
        autoSyncedEndpointKeys.insert(descriptor.key)
        startCourseLibrarySync()
    }

    func startCourseLibrarySync(allowOnlineConnection: Bool = false) {
        courseLibrarySyncTask?.cancel()
        courseLibrarySyncTask = Task { [weak self] in
            await self?.syncCourseLibrary(allowOnlineConnection: allowOnlineConnection)
        }
    }

    private func cancelCourseLibrarySync() {
        courseLibrarySyncTask?.cancel()
        courseLibrarySyncTask = nil
        isSyncingCourseLibrary = false
    }

    @discardableResult
    private func loadCachedCoursesForActiveEndpoint() -> Bool {
        guard let descriptor = activeEndpointDescriptor else { return false }
        guard let snapshot = try? courseCacheStore.load(endpoint: descriptor), !snapshot.courses.isEmpty else { return false }
        libraryState = snapshot.libraryState
        courses = snapshot.courses.sorted(by: courseSort)
        if selectedCourseID == nil || !courses.contains(where: { $0.id == selectedCourseID }) {
            selectedCourseID = courses.first?.id
        }
        refreshLocalCourseLibraryIndex()
        return true
    }

    private func saveCachedCoursesForActiveEndpoint(replacingExisting: Bool = false) {
        guard let descriptor = activeEndpointDescriptor, !courses.isEmpty else { return }
        let coursesToSave: [CourseItem]
        if replacingExisting {
            coursesToSave = courses
        } else {
            let existingCourses = (try? courseCacheStore.load(endpoint: descriptor)?.courses) ?? []
            coursesToSave = courses.map { current in
                let existing = existingCourses.first { $0.id == current.id }
                return richestOfflineCourse(current, existing)
            }
        }
        try? courseCacheStore.save(courses: coursesToSave, libraryState: libraryState, endpoint: descriptor)
        refreshLocalCourseLibraryIndex()
    }

    private func richestOfflineCourse(_ candidates: CourseItem?...) -> CourseItem {
        candidates
            .compactMap { $0 }
            .max { left, right in
                left.offlinePayloadScore < right.offlinePayloadScore
            }!
    }

    private func canReuseSyncedCourse(_ course: CourseItem, for summary: CourseItem) -> Bool {
        guard
            let courseUpdatedAt = course.updatedAt,
            let summaryUpdatedAt = summary.updatedAt,
            courseUpdatedAt == summaryUpdatedAt
        else {
            return false
        }
        if course.offlinePayloadScore > summary.offlinePayloadScore {
            return true
        }
        return summary.transcript.isEmpty
            && summary.study == nil
            && course.offlinePayloadScore == summary.offlinePayloadScore
    }

    private func applyLibraryState(to items: [CourseItem]) -> [CourseItem] {
        items.map { $0.applyingLibraryState(libraryState) }
    }

    private func refreshDeviceVideoCacheIndex() {
        deviceVideoCacheRecords = (try? deviceVideoCacheStore.loadUsableRecords()) ?? []
    }

    private func refreshLocalCourseLibraryIndex() {
        localCourseLibraries = endpoints
            .compactMap { endpoint in
                courseCacheStore.localLibrary(endpointID: endpoint.id, endpoint: endpoint)
            }
            .sorted { left, right in
                left.endpointName.localizedStandardCompare(right.endpointName) == .orderedAscending
            }
    }

    private func reconcileActiveEndpointSelection() {
        if let activeEndpointID, endpoints.contains(where: { $0.id == activeEndpointID }) {
            return
        }
        activeEndpointID = endpoints.first?.id
    }

    private func reconcileExplicitLocalModeSelection() {
        guard let explicitLocalModeEndpointID else { return }
        guard endpoints.contains(where: { $0.id == explicitLocalModeEndpointID }) else {
            self.explicitLocalModeEndpointID = nil
            store.saveExplicitLocalModeEndpointID(nil)
            return
        }
        guard explicitLocalModeEndpointID == activeEndpointID else { return }
    }

    private func clearExplicitLocalMode() {
        guard explicitLocalModeEndpointID != nil else { return }
        explicitLocalModeEndpointID = nil
        store.saveExplicitLocalModeEndpointID(nil)
    }

    private func beginConnectionRefresh() -> ConnectionRefreshToken {
        connectionRefreshSequence += 1
        return ConnectionRefreshToken(id: connectionRefreshSequence, endpointID: activeEndpointID)
    }

    private func invalidateConnectionRefreshes() {
        connectionRefreshSequence += 1
    }

    private func canApplyConnectionRefresh(_ refreshToken: ConnectionRefreshToken?) -> Bool {
        guard let refreshToken else { return true }
        return connectionRefreshSequence == refreshToken.id
            && activeEndpointID == refreshToken.endpointID
            && !shouldUseExplicitLocalMode
    }

    private func canContinueOnlineModeAttempt(_ refreshToken: ConnectionRefreshToken, endpointID: UUID?) -> Bool {
        connectionRefreshSequence == refreshToken.id
            && activeEndpointID == endpointID
    }

    private func canApplyHealthResult(for endpointID: UUID?, refreshToken: ConnectionRefreshToken? = nil) -> Bool {
        activeEndpointID == endpointID
            && !shouldUseExplicitLocalMode
            && canApplyConnectionRefresh(refreshToken)
    }

    private func debugNetwork(_ message: String) {
        guard ProcessInfo.processInfo.environment["COURSE_NAVIGATOR_DEBUG_NETWORK"] == "1" else { return }
        print("[CourseNavigatorState] \(message)")
    }

    private func persistEndpoints() {
        store.save(endpoints)
        store.saveActiveEndpointID(activeEndpointID)
    }

    private func normalizedOptional(_ value: String) -> String? {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    private static func normalizedUsableStoredEndpoints(from endpoints: [BackendEndpoint]) -> [BackendEndpoint] {
        var seenBaseURLs = Set<String>()
        var normalizedEndpoints: [BackendEndpoint] = []

        for storedEndpoint in endpoints {
            guard
                storedEndpoint.isUsableOnCurrentDevice,
                let normalizedBaseURL = storedEndpoint.normalizedBaseURL?.absoluteString,
                !seenBaseURLs.contains(normalizedBaseURL)
            else {
                continue
            }

            var endpoint = storedEndpoint
            endpoint.baseURL = normalizedBaseURL
            normalizedEndpoints.append(endpoint)
            seenBaseURLs.insert(normalizedBaseURL)
        }

        return normalizedEndpoints
    }
}

private func courseSort(_ left: CourseItem, _ right: CourseItem) -> Bool {
    let leftGroup = left.collectionGroupTitle ?? ""
    let rightGroup = right.collectionGroupTitle ?? ""
    if leftGroup != rightGroup { return leftGroup < rightGroup }
    if left.collectionDisplayName != right.collectionDisplayName {
        return left.collectionDisplayName < right.collectionDisplayName
    }
    let leftOrder = left.sortOrder ?? left.courseIndex ?? 0
    let rightOrder = right.sortOrder ?? right.courseIndex ?? 0
    if leftOrder != rightOrder { return leftOrder < rightOrder }
    return left.title.localizedStandardCompare(right.title) == .orderedAscending
}

private extension URL {
    var isHTTPOrHTTPS: Bool {
        ["http", "https"].contains(scheme?.lowercased() ?? "")
    }

    var isHLSManifest: Bool {
        pathExtension.lowercased() == "m3u8"
    }
}

private extension Array where Element == TranscriptSegment {
    func applyingASRCorrection(_ suggestion: ASRCorrectionSuggestion) -> [TranscriptSegment]? {
        guard indices.contains(suggestion.segmentIndex) else { return nil }
        var transcript = self
        let segment = transcript[suggestion.segmentIndex]
        transcript[suggestion.segmentIndex] = TranscriptSegment(
            start: segment.start,
            end: segment.end,
            text: suggestion.correctedText
        )
        return transcript
    }
}

struct LocalCourseLibrary: Identifiable, Hashable {
    var id: UUID
    var endpointName: String
    var endpointBaseURL: String
    var courseCount: Int?
    var savedAt: Date

    var courseCountLabel: String {
        guard let courseCount else { return "已同步课程资料" }
        return "\(courseCount) 门课程"
    }
}

struct EndpointStore {
    private let endpointsKey = "course-navigator-mobile-endpoints"
    private let activeEndpointKey = "course-navigator-mobile-active-endpoint"
    private let explicitLocalModeEndpointKey = "course-navigator-mobile-explicit-local-mode-endpoint"

    static var defaultEndpoints: [BackendEndpoint] {
        #if targetEnvironment(simulator)
        [BackendEndpoint(name: "模拟器本机", baseURL: "http://127.0.0.1:18000")]
        #else
        []
        #endif
    }

    func load() -> [BackendEndpoint] {
        guard let data = UserDefaults.standard.data(forKey: endpointsKey) else { return [] }
        return (try? JSONDecoder.courseNavigator.decode([BackendEndpoint].self, from: data)) ?? []
    }

    func save(_ endpoints: [BackendEndpoint]) {
        if let data = try? JSONEncoder.courseNavigator.encode(endpoints) {
            UserDefaults.standard.set(data, forKey: endpointsKey)
        }
    }

    func loadActiveEndpointID() -> UUID? {
        guard let raw = UserDefaults.standard.string(forKey: activeEndpointKey) else { return nil }
        return UUID(uuidString: raw)
    }

    func saveActiveEndpointID(_ id: UUID?) {
        UserDefaults.standard.set(id?.uuidString, forKey: activeEndpointKey)
    }

    func loadExplicitLocalModeEndpointID() -> UUID? {
        guard let raw = UserDefaults.standard.string(forKey: explicitLocalModeEndpointKey) else { return nil }
        return UUID(uuidString: raw)
    }

    func saveExplicitLocalModeEndpointID(_ id: UUID?) {
        UserDefaults.standard.set(id?.uuidString, forKey: explicitLocalModeEndpointKey)
    }
}

struct EndpointCacheDescriptor: Codable, Hashable {
    var key: String
    var name: String
    var baseURL: String

    init?(endpoint: BackendEndpoint) {
        guard let normalizedBaseURL = endpoint.normalizedBaseURL?.absoluteString else { return nil }
        key = Self.key(for: normalizedBaseURL)
        name = endpoint.name
        baseURL = normalizedBaseURL
    }

    static func key(for value: String) -> String {
        Data(value.utf8)
            .base64EncodedString()
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "=", with: "")
    }
}

struct CourseCacheSnapshot: Codable {
    var endpointName: String
    var endpointBaseURL: String
    var savedAt: Date
    var libraryState: LibraryState
    var courses: [CourseItem]

    enum CodingKeys: String, CodingKey {
        case endpointName
        case endpointBaseURL
        case savedAt
        case libraryState
        case courses
    }

    init(endpointName: String, endpointBaseURL: String, savedAt: Date, libraryState: LibraryState, courses: [CourseItem]) {
        self.endpointName = endpointName
        self.endpointBaseURL = endpointBaseURL
        self.savedAt = savedAt
        self.libraryState = libraryState
        self.courses = courses
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        endpointName = try container.decode(String.self, forKey: .endpointName)
        endpointBaseURL = try container.decode(String.self, forKey: .endpointBaseURL)
        savedAt = try container.decode(Date.self, forKey: .savedAt)
        libraryState = (try? container.decode(LibraryState.self, forKey: .libraryState)) ?? LibraryState()
        courses = try container.decode([CourseItem].self, forKey: .courses)
    }
}

private struct CourseCacheMetadata: Codable {
    var endpointName: String
    var endpointBaseURL: String
    var savedAt: Date
    var courseCount: Int?
}

struct CourseCacheStore {
    private let fileManager = FileManager.default

    func load(endpoint: EndpointCacheDescriptor) throws -> CourseCacheSnapshot? {
        let fileURL = try snapshotURL(for: endpoint)
        guard fileManager.fileExists(atPath: fileURL.path) else { return nil }
        let data = try Data(contentsOf: fileURL)
        let snapshot = try JSONDecoder.courseNavigator.decode(CourseCacheSnapshot.self, from: data)
        try? saveMetadata(
            CourseCacheMetadata(
                endpointName: snapshot.endpointName,
                endpointBaseURL: snapshot.endpointBaseURL,
                savedAt: snapshot.savedAt,
                courseCount: snapshot.courses.count
            ),
            endpoint: endpoint
        )
        return snapshot
    }

    func save(courses: [CourseItem], libraryState: LibraryState, endpoint: EndpointCacheDescriptor) throws {
        let fileURL = try snapshotURL(for: endpoint)
        try fileManager.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        let savedAt = Date()
        let snapshot = CourseCacheSnapshot(
            endpointName: endpoint.name,
            endpointBaseURL: endpoint.baseURL,
            savedAt: savedAt,
            libraryState: libraryState,
            courses: courses
        )
        let data = try JSONEncoder.courseNavigator.encode(snapshot)
        try data.write(to: fileURL, options: .atomic)
        try saveMetadata(
            CourseCacheMetadata(
                endpointName: endpoint.name,
                endpointBaseURL: endpoint.baseURL,
                savedAt: savedAt,
                courseCount: courses.count
            ),
            endpoint: endpoint
        )
    }

    func localLibrary(endpointID: UUID, endpoint: BackendEndpoint) -> LocalCourseLibrary? {
        guard let descriptor = EndpointCacheDescriptor(endpoint: endpoint) else { return nil }
        if let metadata = try? loadMetadata(endpoint: descriptor) {
            return LocalCourseLibrary(
                id: endpointID,
                endpointName: endpoint.name,
                endpointBaseURL: descriptor.baseURL,
                courseCount: metadata.courseCount,
                savedAt: metadata.savedAt
            )
        }
        guard
            let snapshotURL = try? snapshotURL(for: descriptor),
            fileManager.fileExists(atPath: snapshotURL.path)
        else {
            return nil
        }
        let attributes = try? fileManager.attributesOfItem(atPath: snapshotURL.path)
        let savedAt = attributes?[.modificationDate] as? Date ?? Date()
        return LocalCourseLibrary(
            id: endpointID,
            endpointName: endpoint.name,
            endpointBaseURL: descriptor.baseURL,
            courseCount: nil,
            savedAt: savedAt
        )
    }

    private func snapshotURL(for endpoint: EndpointCacheDescriptor) throws -> URL {
        try applicationSupportDirectory()
            .appendingPathComponent("CourseSnapshots", isDirectory: true)
            .appendingPathComponent(endpoint.key, isDirectory: true)
            .appendingPathComponent("courses.json")
    }

    private func metadataURL(for endpoint: EndpointCacheDescriptor) throws -> URL {
        try applicationSupportDirectory()
            .appendingPathComponent("CourseSnapshots", isDirectory: true)
            .appendingPathComponent(endpoint.key, isDirectory: true)
            .appendingPathComponent("metadata.json")
    }

    private func loadMetadata(endpoint: EndpointCacheDescriptor) throws -> CourseCacheMetadata? {
        let fileURL = try metadataURL(for: endpoint)
        guard fileManager.fileExists(atPath: fileURL.path) else { return nil }
        let data = try Data(contentsOf: fileURL)
        return try JSONDecoder.courseNavigator.decode(CourseCacheMetadata.self, from: data)
    }

    private func saveMetadata(_ metadata: CourseCacheMetadata, endpoint: EndpointCacheDescriptor) throws {
        let fileURL = try metadataURL(for: endpoint)
        try fileManager.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        let data = try JSONEncoder.courseNavigator.encode(metadata)
        try data.write(to: fileURL, options: .atomic)
    }

    private func applicationSupportDirectory() throws -> URL {
        let base = try fileManager.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        let directory = base.appendingPathComponent("CourseNavigatorMobile", isDirectory: true)
        try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory
    }
}

struct DeviceVideoCacheRecord: Codable, Identifiable, Hashable {
    var endpointKey: String
    var endpointName: String
    var endpointBaseURL: String
    var courseID: String
    var courseTitle: String
    var filename: String
    var byteCount: Int64
    var cachedAt: Date
    var sourceURL: String

    var id: String { "\(endpointKey)|\(courseID)" }

    var sizeLabel: String {
        ByteCountFormatter.string(fromByteCount: byteCount, countStyle: .file)
    }
}

@MainActor
struct DeviceVideoCacheStore {
    private let fileManager = FileManager.default

    func loadRecords() throws -> [DeviceVideoCacheRecord] {
        let fileURL = try indexURL()
        guard fileManager.fileExists(atPath: fileURL.path) else { return [] }
        let data = try Data(contentsOf: fileURL)
        return try JSONDecoder.courseNavigator.decode([DeviceVideoCacheRecord].self, from: data)
    }

    func loadUsableRecords() throws -> [DeviceVideoCacheRecord] {
        let records = try loadRecords()
        let usable = records.filter { isUsableCachedVideo($0) }
        let removedRecords = records.filter { !usable.contains($0) }
        for record in removedRecords {
            removeCachedFileIfNeeded(record)
        }
        if usable.count != records.count {
            try save(usable)
        }
        return usable
    }

    func localVideoURL(for item: CourseItem, endpoint: EndpointCacheDescriptor?) -> URL? {
        guard let endpoint, let record = try? loadRecords().first(where: { $0.endpointKey == endpoint.key && $0.courseID == item.id }) else {
            return nil
        }
        let fileURL = videoDirectory(endpointKey: record.endpointKey).appendingPathComponent(record.filename)
        return isUsableCachedVideo(record, fileURL: fileURL) ? fileURL : nil
    }

    func cacheVideo(item: CourseItem, endpoint: EndpointCacheDescriptor, remoteURL: URL) async throws -> DeviceVideoCacheRecord {
        let (temporaryURL, response) = try await URLSession.shared.download(from: remoteURL)
        var stagingURL: URL?
        do {
            try validateDownloadResponse(response, remoteURL: remoteURL)
            let filename = try cachedFilename(item: item, response: response, remoteURL: remoteURL)
            let directory = videoDirectory(endpointKey: endpoint.key)
            try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
            let destinationURL = directory.appendingPathComponent(filename)
            let preparedURL = directory.appendingPathComponent(".\(UUID().uuidString)-\(filename)")
            stagingURL = preparedURL
            try fileManager.moveItem(at: temporaryURL, to: preparedURL)
            let values = try preparedURL.resourceValues(forKeys: [.fileSizeKey])
            let byteCount = Int64(values.fileSize ?? 0)
            guard byteCount > 0 else {
                try? fileManager.removeItem(at: preparedURL)
                throw DeviceVideoCacheError.emptyFile
            }
            guard isPlayableContainerFile(preparedURL) else {
                try? fileManager.removeItem(at: preparedURL)
                throw DeviceVideoCacheError.unsupportedFileContainer
            }
            if fileManager.fileExists(atPath: destinationURL.path) {
                try fileManager.removeItem(at: destinationURL)
            }
            try fileManager.moveItem(at: preparedURL, to: destinationURL)
            stagingURL = nil
            let record = DeviceVideoCacheRecord(
                endpointKey: endpoint.key,
                endpointName: endpoint.name,
                endpointBaseURL: endpoint.baseURL,
                courseID: item.id,
                courseTitle: item.displayTitle,
                filename: filename,
                byteCount: byteCount,
                cachedAt: Date(),
                sourceURL: remoteURL.absoluteString
            )
            try upsert(record)
            return record
        } catch {
            try? fileManager.removeItem(at: temporaryURL)
            if let stagingURL {
                try? fileManager.removeItem(at: stagingURL)
            }
            throw error
        }
    }

    func removeVideo(_ item: CourseItem, endpoint: EndpointCacheDescriptor?) throws {
        guard let endpoint, let record = try loadRecords().first(where: { $0.endpointKey == endpoint.key && $0.courseID == item.id }) else {
            return
        }
        try removeVideo(record)
    }

    func removeVideo(_ record: DeviceVideoCacheRecord) throws {
        removeCachedFileIfNeeded(record)
        var records = try loadRecords()
        records.removeAll { $0.id == record.id }
        try save(records)
    }

    private func upsert(_ record: DeviceVideoCacheRecord) throws {
        var records = try loadRecords()
        let oldRecords = records.filter { $0.id == record.id }
        for oldRecord in oldRecords where oldRecord.filename != record.filename {
            removeCachedFileIfNeeded(oldRecord)
        }
        records.removeAll { $0.id == record.id }
        records.append(record)
        try save(records)
    }

    private func save(_ records: [DeviceVideoCacheRecord]) throws {
        let fileURL = try indexURL()
        try fileManager.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        let data = try JSONEncoder.courseNavigator.encode(records.sorted { $0.courseTitle < $1.courseTitle })
        try data.write(to: fileURL, options: .atomic)
    }

    private func validateDownloadResponse(_ response: URLResponse, remoteURL: URL) throws {
        if remoteURL.pathExtension.lowercased() == "m3u8" {
            throw DeviceVideoCacheError.unsupportedStreamingFormat
        }
        if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
            throw DeviceVideoCacheError.badHTTPStatus(http.statusCode)
        }
        guard let mimeType = response.mimeType?.lowercased(), !mimeType.isEmpty else { return }
        if mimeType.contains("mpegurl") || mimeType.contains("x-mpegurl") || mimeType.contains("vnd.apple.mpegurl") {
            throw DeviceVideoCacheError.unsupportedStreamingFormat
        }
        if mimeType.contains("mp2t") || mimeType.contains("mpegts") {
            throw DeviceVideoCacheError.unsupportedFileContainer
        }
        if mimeType.hasPrefix("text/") || mimeType == "application/json" {
            throw DeviceVideoCacheError.unsupportedContentType(mimeType)
        }
    }

    private func cachedFilename(item: CourseItem, response: URLResponse, remoteURL: URL) throws -> String {
        guard let ext = cachedFileExtension(item: item, response: response, remoteURL: remoteURL) else {
            throw DeviceVideoCacheError.unsupportedFileType
        }
        let safeID = item.id.replacingOccurrences(of: #"[^A-Za-z0-9._-]"#, with: "-", options: .regularExpression)
        return "\(safeID).\(ext)"
    }

    private func cachedFileExtension(item: CourseItem, response: URLResponse, remoteURL: URL) -> String? {
        [
            item.localVideoPath.flatMap { supportedPlayableExtension(URL(fileURLWithPath: $0).pathExtension) },
            supportedPlayableExtension(URL(fileURLWithPath: response.suggestedFilename ?? "").pathExtension),
            supportedExtension(forMIMEType: response.mimeType),
            supportedPlayableExtension(remoteURL.pathExtension)
        ]
        .compactMap { $0 }
        .first
    }

    private func supportedExtension(forMIMEType mimeType: String?) -> String? {
        switch mimeType?.lowercased() {
        case "video/mp4", "application/mp4", "audio/mp4":
            "mp4"
        case "video/x-m4v":
            "m4v"
        case "video/quicktime":
            "mov"
        default:
            nil
        }
    }

    private func supportedPlayableExtension(_ value: String?) -> String? {
        let ext = value?.lowercased().trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard ["mp4", "m4v", "mov"].contains(ext) else { return nil }
        return ext
    }

    private func isUsableCachedVideo(_ record: DeviceVideoCacheRecord) -> Bool {
        isUsableCachedVideo(record, fileURL: videoDirectory(endpointKey: record.endpointKey).appendingPathComponent(record.filename))
    }

    private func isUsableCachedVideo(_ record: DeviceVideoCacheRecord, fileURL: URL) -> Bool {
        guard supportedPlayableExtension(fileURL.pathExtension) != nil else { return false }
        guard fileManager.fileExists(atPath: fileURL.path) else { return false }
        let byteCount = ((try? fileURL.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0)
        return byteCount > 0 && record.byteCount > 0 && isPlayableContainerFile(fileURL)
    }

    private func isPlayableContainerFile(_ fileURL: URL) -> Bool {
        guard let ext = supportedPlayableExtension(fileURL.pathExtension) else { return false }
        guard let handle = try? FileHandle(forReadingFrom: fileURL) else { return false }
        defer { try? handle.close() }
        let data = (try? handle.read(upToCount: 512)) ?? Data()
        guard data.count >= 12 else { return false }
        if looksLikeMPEGTransportStream(data) {
            return false
        }
        return looksLikeISOBaseMedia(data, allowQuickTimeAtoms: ext == "mov")
    }

    private func looksLikeMPEGTransportStream(_ data: Data) -> Bool {
        let bytes = [UInt8](data)
        guard bytes.count > 188 else { return false }
        if bytes[0] == 0x47 && bytes[188] == 0x47 { return true }
        guard bytes.count > 376 else { return false }
        return bytes[0] == 0x47 && bytes[188] == 0x47 && bytes[376] == 0x47
    }

    private func looksLikeISOBaseMedia(_ data: Data, allowQuickTimeAtoms: Bool) -> Bool {
        let bytes = [UInt8](data)
        let atomNames = stride(from: 4, through: min(bytes.count - 4, 256), by: 4).compactMap { offset -> String? in
            guard offset + 4 <= bytes.count else { return nil }
            return String(bytes: bytes[offset..<offset + 4], encoding: .ascii)
        }
        if atomNames.contains("ftyp") { return true }
        guard allowQuickTimeAtoms else { return false }
        return atomNames.contains("moov") || atomNames.contains("mdat")
    }

    private func removeCachedFileIfNeeded(_ record: DeviceVideoCacheRecord) {
        let fileURL = videoDirectory(endpointKey: record.endpointKey).appendingPathComponent(record.filename)
        if fileManager.fileExists(atPath: fileURL.path) {
            try? fileManager.removeItem(at: fileURL)
        }
    }

    private func indexURL() throws -> URL {
        try cacheRootDirectory().appendingPathComponent("video-cache-index.json")
    }

    private func videoDirectory(endpointKey: String) -> URL {
        (try? cacheRootDirectory().appendingPathComponent(endpointKey, isDirectory: true))
            ?? URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("CourseNavigatorMobileVideoCache", isDirectory: true)
    }

    private func cacheRootDirectory() throws -> URL {
        let base = try fileManager.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        let directory = base
            .appendingPathComponent("CourseNavigatorMobile", isDirectory: true)
            .appendingPathComponent("VideoCache", isDirectory: true)
        try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory
    }
}

enum DeviceVideoCacheError: LocalizedError {
    case badHTTPStatus(Int)
    case unsupportedContentType(String)
    case unsupportedStreamingFormat
    case unsupportedFileType
    case unsupportedFileContainer
    case emptyFile

    var errorDescription: String? {
        switch self {
        case .badHTTPStatus(let status):
            "缓存到当前设备失败：视频地址返回 HTTP \(status)。"
        case .unsupportedContentType(let mimeType):
            "缓存到当前设备失败：这个地址返回的是 \(mimeType)，不是可缓存的视频文件。"
        case .unsupportedStreamingFormat:
            "缓存到当前设备失败：当前版本暂不支持 HLS/分片流离线缓存，会继续使用在线播放。"
        case .unsupportedFileType:
            "缓存到当前设备失败：没有拿到本机可直接播放的视频文件格式。"
        case .unsupportedFileContainer:
            "缓存到当前设备失败：后端返回的视频不是可直接播放的 MP4/MOV 文件。"
        case .emptyFile:
            "缓存到当前设备失败：下载结果是空文件。"
        }
    }
}

enum MobileDeviceText {
    static let currentDeviceName = "当前设备"
    static let cacheButtonTitle = "缓存到当前设备"
    static let localCacheTitle = "本地视频缓存"
    static let videoCacheTitle = "本地视频缓存"
}
