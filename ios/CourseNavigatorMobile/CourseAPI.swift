import Foundation

struct CourseAPI {
    var baseURL: URL

    func health() async throws -> HealthResponse {
        try await get("/health")
    }

    func listItems() async throws -> [CourseItem] {
        try await get("/items")
    }

    func modelSettings() async throws -> ModelSettings {
        try await get("/settings/model")
    }

    func onlineASRSettings() async throws -> OnlineASRSettings {
        try await get("/settings/online-asr")
    }

    func importLocalVideosFromPicker(request: LocalVideoFilePickerRequest) async throws -> [CourseItem] {
        try await send("/local-video-file-picker", method: "POST", body: request)
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

    func bindVideoSource(itemID: String, request: VideoSourceBindingRequest) async throws -> CourseItem {
        try await send("/items/\(itemID.urlPathEncoded)/video-source", method: "POST", body: request)
    }

    func bindVideoSourceFromPicker(itemID: String) async throws -> CourseItem {
        try await post("/items/\(itemID.urlPathEncoded)/video-source-picker")
    }

    func importWorkspaceVideoFromPicker(itemID: String) async throws -> CourseItem {
        try await post("/items/\(itemID.urlPathEncoded)/workspace-video-picker")
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

    private func get<T: Decodable>(_ path: String) async throws -> T {
        guard let url = apiURL(path) else { throw CourseAPIError.invalidURL }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        return try await perform(request)
    }

    private func delete<T: Decodable>(_ path: String) async throws -> T {
        guard let url = apiURL(path) else { throw CourseAPIError.invalidURL }
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        return try await perform(request)
    }

    private func post<T: Decodable>(_ path: String) async throws -> T {
        guard let url = apiURL(path) else { throw CourseAPIError.invalidURL }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        return try await perform(request)
    }

    private func send<T: Decodable, Body: Encodable>(
        _ path: String,
        method: String,
        body: Body
    ) async throws -> T {
        guard let url = apiURL(path) else { throw CourseAPIError.invalidURL }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder.courseNavigator.encode(body)
        return try await perform(request)
    }

    private func perform<T: Decodable>(_ request: URLRequest) async throws -> T {
        var request = request
        request.timeoutInterval = 20
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw CourseAPIError.invalidResponse
        }
        guard (200..<300).contains(http.statusCode) else {
            throw CourseAPIError.server(message: Self.errorMessage(from: data) ?? "Request failed: \(http.statusCode)")
        }
        do {
            return try JSONDecoder.courseNavigator.decode(T.self, from: data)
        } catch {
            throw CourseAPIError.decode(error.localizedDescription)
        }
    }

    private func apiURL(_ path: String) -> URL? {
        var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false)
        let basePath = components?.path.trimmingCharacters(in: CharacterSet(charactersIn: "/")) ?? ""
        let apiPath = path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        components?.path = "/" + [basePath, "api", apiPath]
            .filter { !$0.isEmpty }
            .joined(separator: "/")
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
}

enum CourseAPIError: LocalizedError {
    case invalidURL
    case invalidResponse
    case server(message: String)
    case decode(String)

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
