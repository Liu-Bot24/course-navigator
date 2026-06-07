import Foundation
import Observation

@MainActor
@Observable
final class AppModel {
    var endpoints: [BackendEndpoint]
    var activeEndpointID: UUID?
    var connectionStatus: ConnectionStatus = .unknown
    var courses: [CourseItem] = []
    var selectedCourseID: String?
    var activeJob: StudyJobStatus?
    var modelSettings: ModelSettings?
    var onlineASRSettings: OnlineASRSettings?
    var backendCapabilityError: String?
    var isLoading = false
    var errorMessage: String?

    private let store = EndpointStore()

    init() {
        let stored = store.load()
        let usableStoredEndpoints = stored.filter(\.isUsableOnCurrentDevice)
        endpoints = usableStoredEndpoints.isEmpty ? EndpointStore.defaultEndpoints : usableStoredEndpoints
        activeEndpointID = store.loadActiveEndpointID() ?? endpoints.first?.id
        let loadedActiveEndpointID = activeEndpointID
        reconcileActiveEndpointSelection()
        if stored != usableStoredEndpoints {
            store.save(usableStoredEndpoints)
        }
        if activeEndpointID != loadedActiveEndpointID {
            store.saveActiveEndpointID(activeEndpointID)
        }
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

    var selectedCourse: CourseItem? {
        guard let selectedCourseID else { return courses.first }
        return courses.first { $0.id == selectedCourseID }
    }

    var api: CourseAPI? {
        guard let url = activeEndpoint?.normalizedBaseURL else { return nil }
        return CourseAPI(baseURL: url)
    }

    func bootstrap() async {
        await refreshAll()
    }

    func selectEndpoint(_ id: UUID?) async {
        activeEndpointID = id
        reconcileActiveEndpointSelection()
        store.saveActiveEndpointID(activeEndpointID)
        clearBackendContent()
        await refreshAll()
    }

    @discardableResult
    func saveEndpoint(_ endpoint: BackendEndpoint, mergeByBaseURL: Bool = false) -> UUID {
        var endpoint = endpoint
        let originalEndpointID = endpoint.id
        if
            mergeByBaseURL,
            let normalizedBaseURL = endpoint.normalizedBaseURL?.absoluteString,
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
        persistEndpoints()
        return endpoint.id
    }

    func deleteEndpoint(_ endpoint: BackendEndpoint) async {
        let wasActiveEndpoint = activeEndpoint?.id == endpoint.id
        endpoints.removeAll { $0.id == endpoint.id }
        if wasActiveEndpoint {
            activeEndpointID = endpoints.first?.id
            clearBackendContent()
        }
        reconcileActiveEndpointSelection()
        persistEndpoints()
        if wasActiveEndpoint {
            await refreshAll()
        }
    }

    func refreshAll() async {
        await checkHealth()
        await refreshBackendCapabilities()
        guard isBackendOnline else {
            courses = []
            selectedCourseID = nil
            isLoading = false
            return
        }
        await refreshCourses()
    }

    func checkHealth() async {
        guard let api else {
            connectionStatus = .offline("请先配置电脑后端地址")
            return
        }
        connectionStatus = .checking
        do {
            let health = try await api.health()
            connectionStatus = health.ok ? .online(health.name) : .offline("后端未就绪")
        } catch {
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

    func refreshCourses() async {
        guard let api, isBackendOnline else {
            courses = []
            selectedCourseID = nil
            return
        }
        isLoading = true
        defer { isLoading = false }
        do {
            courses = try await api.listItems().sorted(by: courseSort)
            if selectedCourseID == nil {
                selectedCourseID = courses.first?.id
            }
            if let selectedCourseID, !courses.contains(where: { $0.id == selectedCourseID }) {
                self.selectedCourseID = courses.first?.id
            }
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
            let request = DownloadRequest(
                url: item.sourceURL,
                mode: .browser,
                browser: "chrome",
                cookiesPath: nil
            )
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
                await refreshCourses()
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
        modelSettings = nil
        onlineASRSettings = nil
        backendCapabilityError = nil
        isLoading = false
    }

    private func reconcileActiveEndpointSelection() {
        if let activeEndpointID, endpoints.contains(where: { $0.id == activeEndpointID }) {
            return
        }
        activeEndpointID = endpoints.first?.id
    }

    private func persistEndpoints() {
        store.save(endpoints)
        store.saveActiveEndpointID(activeEndpointID)
    }

    private func normalizedOptional(_ value: String) -> String? {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
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

struct EndpointStore {
    private let endpointsKey = "course-navigator-mobile-endpoints"
    private let activeEndpointKey = "course-navigator-mobile-active-endpoint"

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
}
