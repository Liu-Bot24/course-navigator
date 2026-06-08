import Foundation

struct CourseAPI {
    var baseURL: URL
    private static let healthTimeout: TimeInterval = 5
    private static let defaultTimeout: TimeInterval = 20
    private static let computerPickerTimeout: TimeInterval = 300

    func health() async throws -> HealthResponse {
        try await get("/health", timeout: Self.healthTimeout)
    }

    func listItems() async throws -> [CourseItem] {
        try await get("/items")
    }

    func listItemSummaries() async throws -> [CourseItem] {
        try await get("/items", queryItems: [URLQueryItem(name: "summary", value: "true")])
    }

    func libraryState() async throws -> LibraryState {
        try await get("/library-state")
    }

    func item(itemID: String) async throws -> CourseItem {
        try await get("/items/\(itemID.urlPathEncoded)")
    }

    func modelSettings() async throws -> ModelSettings {
        try await get("/settings/model")
    }

    func onlineASRSettings() async throws -> OnlineASRSettings {
        try await get("/settings/online-asr")
    }

    func importLocalVideosFromPicker(request: LocalVideoFilePickerRequest) async throws -> [CourseItem] {
        try await send(
            "/local-video-file-picker",
            method: "POST",
            body: request,
            timeout: Self.computerPickerTimeout
        )
    }

    func importCoursePackage(_ package: CourseSharePackage) async throws -> CourseImportResponse {
        try await send("/import", method: "POST", body: package)
    }

    func saveCookieText(_ request: CookieTextRequest) async throws -> CookieTextResponse {
        try await send("/cookies/text", method: "POST", body: request)
    }

    func preview(_ request: ExtractRequest) async throws -> CourseItem {
        try await send("/preview", method: "POST", body: request)
    }

    func startExtractJob(_ request: ExtractRequest) async throws -> StudyJobStatus {
        try await send("/extract-jobs", method: "POST", body: request)
    }

    func startStudyJob(itemID: String, request: StudyRequest) async throws -> StudyJobStatus {
        try await send("/items/\(itemID.urlPathEncoded)/study-jobs", method: "POST", body: request)
    }

    func startTranslationJob(itemID: String, request: TranslationRequest) async throws -> StudyJobStatus {
        try await send("/items/\(itemID.urlPathEncoded)/translation-jobs", method: "POST", body: request)
    }

    func startASRCorrectionJob(itemID: String, request: ASRCorrectionRequest) async throws -> StudyJobStatus {
        try await send("/items/\(itemID.urlPathEncoded)/asr-correction-jobs", method: "POST", body: request)
    }

    func asrCorrectionResult(jobID: String) async throws -> ASRCorrectionResult {
        try await get("/asr-correction-jobs/\(jobID.urlPathEncoded)/result")
    }

    func saveTranscript(itemID: String, request: TranscriptUpdateRequest) async throws -> CourseItem {
        try await send("/items/\(itemID.urlPathEncoded)/transcript", method: "PUT", body: request)
    }

    func startDownloadJob(itemID: String, request: DownloadRequest) async throws -> StudyJobStatus {
        try await send("/items/\(itemID.urlPathEncoded)/download-jobs", method: "POST", body: request)
    }

    func downloadJob(itemID: String) async throws -> StudyJobStatus? {
        try await getOptional("/items/\(itemID.urlPathEncoded)/download-job")
    }

    func resolvePlaybackSource(itemID: String) async throws -> CourseItem {
        try await post("/items/\(itemID.urlPathEncoded)/playback-source")
    }

    func bindVideoSource(itemID: String, request: VideoSourceBindingRequest) async throws -> CourseItem {
        try await send("/items/\(itemID.urlPathEncoded)/video-source", method: "POST", body: request)
    }

    func bindVideoSourceFromPicker(itemID: String) async throws -> CourseItem {
        try await post(
            "/items/\(itemID.urlPathEncoded)/video-source-picker",
            timeout: Self.computerPickerTimeout
        )
    }

    func importWorkspaceVideoFromPicker(itemID: String) async throws -> CourseItem {
        try await post(
            "/items/\(itemID.urlPathEncoded)/workspace-video-picker",
            timeout: Self.computerPickerTimeout
        )
    }

    func updateItem(itemID: String, request: CourseItemUpdate) async throws -> CourseItem {
        try await send("/items/\(itemID.urlPathEncoded)", method: "PATCH", body: request)
    }

    func updateItemDetails(itemID: String, request: CourseDetailsUpdate) async throws -> CourseItem {
        try await send("/items/\(itemID.urlPathEncoded)", method: "PATCH", body: request)
    }

    func deleteItem(itemID: String) async throws -> DeleteResponse {
        try await delete("/items/\(itemID.urlPathEncoded)")
    }

    func deleteLocalVideo(itemID: String) async throws -> CourseItem {
        try await delete("/items/\(itemID.urlPathEncoded)/local-video")
    }

    func job(_ jobID: String) async throws -> StudyJobStatus {
        try await get("/jobs/\(jobID.urlPathEncoded)")
    }

    func videoURL(itemID: String) -> URL? {
        apiURL("/items/\(itemID.urlPathEncoded)/video")
    }

    private func get<T: Decodable>(
        _ path: String,
        timeout: TimeInterval = Self.defaultTimeout,
        queryItems: [URLQueryItem] = []
    ) async throws -> T {
        guard let url = apiURL(path, queryItems: queryItems) else { throw CourseAPIError.invalidURL }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        return try await perform(request, timeout: timeout)
    }

    private func getOptional<T: Decodable>(
        _ path: String,
        timeout: TimeInterval = Self.defaultTimeout
    ) async throws -> T? {
        guard let url = apiURL(path) else { throw CourseAPIError.invalidURL }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = timeout
        Self.debugNetwork("START \(request.httpMethod ?? "GET") \(request.url?.absoluteString ?? "<invalid>") timeout=\(timeout)")
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await URLSession.shared.data(for: request)
        } catch let error as URLError {
            Self.debugNetwork("ERROR \(error.code.rawValue) \(request.url?.absoluteString ?? "<invalid>") \(error.localizedDescription)")
            throw CourseAPIError.transport(Self.transportMessage(for: error))
        }
        guard let http = response as? HTTPURLResponse else {
            Self.debugNetwork("ERROR invalid-response \(request.url?.absoluteString ?? "<invalid>")")
            throw CourseAPIError.invalidResponse
        }
        if http.statusCode == 404 {
            Self.debugNetwork("OK status=404 optional-empty \(request.url?.absoluteString ?? "<invalid>")")
            return nil
        }
        guard (200..<300).contains(http.statusCode) else {
            Self.debugNetwork("ERROR status=\(http.statusCode) \(request.url?.absoluteString ?? "<invalid>")")
            throw CourseAPIError.server(message: Self.errorMessage(from: data) ?? "Request failed: \(http.statusCode)")
        }
        do {
            let value = try JSONDecoder.courseNavigator.decode(T.self, from: data)
            Self.debugNetwork("OK status=\(http.statusCode) bytes=\(data.count) \(request.url?.absoluteString ?? "<invalid>")")
            return value
        } catch {
            Self.debugNetwork("ERROR decode \(request.url?.absoluteString ?? "<invalid>") \(error.localizedDescription)")
            throw CourseAPIError.decode(error.localizedDescription)
        }
    }

    private func delete<T: Decodable>(
        _ path: String,
        timeout: TimeInterval = Self.defaultTimeout
    ) async throws -> T {
        guard let url = apiURL(path) else { throw CourseAPIError.invalidURL }
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        return try await perform(request, timeout: timeout)
    }

    private func post<T: Decodable>(
        _ path: String,
        timeout: TimeInterval = Self.defaultTimeout
    ) async throws -> T {
        guard let url = apiURL(path) else { throw CourseAPIError.invalidURL }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        return try await perform(request, timeout: timeout)
    }

    private func send<T: Decodable, Body: Encodable>(
        _ path: String,
        method: String,
        body: Body,
        timeout: TimeInterval = Self.defaultTimeout
    ) async throws -> T {
        guard let url = apiURL(path) else { throw CourseAPIError.invalidURL }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder.courseNavigator.encode(body)
        return try await perform(request, timeout: timeout)
    }

    private func perform<T: Decodable>(
        _ request: URLRequest,
        timeout: TimeInterval
    ) async throws -> T {
        var request = request
        request.timeoutInterval = timeout
        Self.debugNetwork("START \(request.httpMethod ?? "GET") \(request.url?.absoluteString ?? "<invalid>") timeout=\(timeout)")
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await URLSession.shared.data(for: request)
        } catch let error as URLError {
            Self.debugNetwork("ERROR \(error.code.rawValue) \(request.url?.absoluteString ?? "<invalid>") \(error.localizedDescription)")
            throw CourseAPIError.transport(Self.transportMessage(for: error))
        }
        guard let http = response as? HTTPURLResponse else {
            Self.debugNetwork("ERROR invalid-response \(request.url?.absoluteString ?? "<invalid>")")
            throw CourseAPIError.invalidResponse
        }
        guard (200..<300).contains(http.statusCode) else {
            Self.debugNetwork("ERROR status=\(http.statusCode) \(request.url?.absoluteString ?? "<invalid>")")
            throw CourseAPIError.server(message: Self.errorMessage(from: data) ?? "Request failed: \(http.statusCode)")
        }
        do {
            let value = try JSONDecoder.courseNavigator.decode(T.self, from: data)
            Self.debugNetwork("OK status=\(http.statusCode) bytes=\(data.count) \(request.url?.absoluteString ?? "<invalid>")")
            return value
        } catch {
            Self.debugNetwork("ERROR decode \(request.url?.absoluteString ?? "<invalid>") \(error.localizedDescription)")
            throw CourseAPIError.decode(error.localizedDescription)
        }
    }

    private static func debugNetwork(_ message: String) {
        guard ProcessInfo.processInfo.environment["COURSE_NAVIGATOR_DEBUG_NETWORK"] == "1" else { return }
        print("[CourseNavigatorNetwork] \(message)")
    }

    private func apiURL(_ path: String, queryItems: [URLQueryItem] = []) -> URL? {
        var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false)
        let basePath = components?.path.trimmingCharacters(in: CharacterSet(charactersIn: "/")) ?? ""
        let apiPath = path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        components?.path = "/" + [basePath, "api", apiPath]
            .filter { !$0.isEmpty }
            .joined(separator: "/")
        if !queryItems.isEmpty {
            components?.queryItems = queryItems
        }
        return components?.url
    }

    private static func errorMessage(from data: Data) -> String? {
        guard
            let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let detail = object["detail"]
        else {
            return String(data: data, encoding: .utf8)
        }
        if let message = detail as? String {
            return message
        }
        if let entries = detail as? [[String: Any]] {
            let messages = entries.compactMap { $0["msg"] as? String }
            return messages.isEmpty ? nil : messages.joined(separator: ", ")
        }
        return nil
    }

    private static func transportMessage(for error: URLError) -> String {
        switch error.code {
        case .timedOut:
            "连接电脑后端超时，请确认电脑后端已启动，并且当前设备和电脑在同一局域网。"
        case .cannotFindHost:
            "找不到这个电脑后端地址，请检查局域网 IP 或 .local 地址是否填对。"
        case .cannotConnectToHost:
            "无法连接电脑后端，请确认脚本已启动，且没有被防火墙或网络隔离拦住。"
        case .networkConnectionLost:
            "连接电脑后端时网络中断，请确认 Wi-Fi 稳定后重试。"
        case .notConnectedToInternet:
            "当前设备没有可用网络，请连接到和电脑相同的 Wi-Fi 后重试。"
        case .appTransportSecurityRequiresSecureConnection:
            "iOS 阻止了这个后端地址，请改用脚本打印的局域网 HTTP 地址。"
        case .cancelled:
            "请求已取消"
        default:
            "无法连接电脑后端：\(error.localizedDescription)"
        }
    }
}

enum CourseAPIError: LocalizedError {
    case invalidURL
    case invalidResponse
    case server(message: String)
    case decode(String)
    case transport(String)

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            "后端地址无效"
        case .invalidResponse:
            "后端响应无效"
        case .server(let message):
            message
        case .decode(let message):
            "无法解析后端数据：\(message)"
        case .transport(let message):
            message
        }
    }
}

extension JSONDecoder {
    static var courseNavigator: JSONDecoder {
        JSONDecoder()
    }
}

extension JSONEncoder {
    static var courseNavigator: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        return encoder
    }
}

private extension String {
    var urlPathEncoded: String {
        addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? self
    }
}
