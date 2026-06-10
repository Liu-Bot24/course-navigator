import Foundation

struct BackendEndpoint: Codable, Identifiable, Equatable, Hashable {
    var id: UUID
    var name: String
    var baseURL: String

    init(id: UUID = UUID(), name: String, baseURL: String) {
        self.id = id
        self.name = name
        self.baseURL = baseURL
    }

    var normalizedBaseURL: URL? {
        var raw = baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        if raw.isEmpty { return nil }
        if raw.rangeOfCharacter(from: .whitespacesAndNewlines) != nil { return nil }
        if !raw.contains("://") {
            raw = "http://\(raw)"
        }
        guard var components = URLComponents(string: raw.trimmingCharacters(in: CharacterSet(charactersIn: "/"))) else {
            return nil
        }
        guard let scheme = components.scheme?.lowercased(), ["http", "https"].contains(scheme) else {
            return nil
        }
        guard components.host?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false else {
            return nil
        }
        components.scheme = scheme
        components.query = nil
        components.fragment = nil
        let path = components.path
            .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
            .lowercased()
        if path.isEmpty {
            components.path = ""
        } else if path == "api" || path.hasPrefix("api/") {
            components.path = ""
        } else {
            return nil
        }
        return components.url
    }

    var hasUnsupportedBackendPath: Bool {
        var raw = baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        if raw.isEmpty || raw.rangeOfCharacter(from: .whitespacesAndNewlines) != nil {
            return false
        }
        if !raw.contains("://") {
            raw = "http://\(raw)"
        }
        guard
            let components = URLComponents(string: raw.trimmingCharacters(in: CharacterSet(charactersIn: "/"))),
            ["http", "https"].contains(components.scheme?.lowercased() ?? "")
        else {
            return false
        }
        let path = components.path
            .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
            .lowercased()
        return !path.isEmpty && path != "api" && !path.hasPrefix("api/")
    }

    var isLoopbackBaseURL: Bool {
        guard let host = normalizedBaseURL?.host?.lowercased() else { return false }
        return host == "localhost"
            || host == "::1"
            || host == "0:0:0:0:0:0:0:1"
            || host.hasPrefix("127.")
    }

    var isWildcardBaseURL: Bool {
        guard let host = normalizedBaseURL?.host?.lowercased() else { return false }
        return host == "0.0.0.0"
            || host == "::"
            || host == "0:0:0:0:0:0:0:0"
    }

    var isLinkLocalBaseURL: Bool {
        guard let host = normalizedBaseURL?.host?.lowercased() else { return false }
        return host.hasPrefix("169.254.")
            || host.hasPrefix("fe80:")
    }

    var isUsableOnCurrentDevice: Bool {
        guard normalizedBaseURL != nil else { return false }
        guard !isWildcardBaseURL, !isLinkLocalBaseURL else { return false }
        #if targetEnvironment(simulator)
        return true
        #else
        return !isLoopbackBaseURL
        #endif
    }
}

enum MobileURLNormalizer {
    static func normalizedHTTPURLString(_ value: String) -> String? {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        guard trimmed.rangeOfCharacter(from: .whitespacesAndNewlines) == nil else { return nil }
        let raw = trimmed.contains("://") ? trimmed : "https://\(trimmed)"
        guard var components = URLComponents(string: raw) else { return nil }
        guard let scheme = components.scheme?.lowercased(), ["http", "https"].contains(scheme) else {
            return nil
        }
        guard components.host?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false else {
            return nil
        }
        components.scheme = scheme
        return components.url?.absoluteString
    }
}

enum ConnectionStatus: Equatable {
    case unknown
    case checking
    case online(String)
    case local(String)
    case offline(String)

    var label: String {
        switch self {
        case .unknown:
            "未连接"
        case .checking:
            "正在检查"
        case .online:
            "已连接"
        case .local:
            "本地模式"
        case .offline:
            "连接失败"
        }
    }

    var isLocal: Bool {
        if case .local = self {
            return true
        }
        return false
    }
}

enum ExtractMode: String, Codable, CaseIterable, Identifiable {
    case normal
    case browser
    case cookies

    var id: String { rawValue }

    var label: String {
        switch self {
        case .normal: "普通"
        case .browser: "浏览器 Cookie"
        case .cookies: "Cookie 文件"
        }
    }

    static var mobileChoices: [ExtractMode] {
        [.normal, .browser, .cookies]
    }
}

enum TranscriptSource: String, Codable, CaseIterable, Identifiable {
    case subtitles
    case asr
    case onlineASR = "online_asr"
    case imported

    var id: String { rawValue }

    var label: String {
        switch self {
        case .subtitles: "原字幕优先"
        case .asr: "本地 ASR"
        case .onlineASR: "在线 ASR"
        case .imported: "已导入字幕"
        }
    }
}

enum OutputLanguage: String, Codable, CaseIterable, Identifiable {
    case zhCN = "zh-CN"
    case en
    case ja

    var id: String { rawValue }

    var label: String {
        switch self {
        case .zhCN: "中文"
        case .en: "English"
        case .ja: "日本語"
        }
    }
}

enum StudySection: String, Codable, CaseIterable, Identifiable {
    case all
    case guide
    case outline
    case detailed
    case high

    var id: String { rawValue }

    var label: String {
        switch self {
        case .all: "全部"
        case .guide: "导览"
        case .outline: "大纲"
        case .detailed: "解读"
        case .high: "详解"
        }
    }
}

enum StudyDetailLevel: String, Codable, CaseIterable, Identifiable {
    case fast
    case standard
    case detailed
    case faithful

    var id: String { rawValue }

    var label: String {
        switch self {
        case .fast: "快速"
        case .standard: "标准"
        case .detailed: "详细"
        case .faithful: "高保真"
        }
    }
}

enum VideoSourceType: String, Codable {
    case remote
    case workspace
    case external

    var label: String {
        switch self {
        case .remote: "在线视频"
        case .workspace: "电脑 Workspace"
        case .external: "电脑/NAS 文件"
        }
    }
}

enum LocalVideoImportMode: String, Codable, CaseIterable, Identifiable {
    case external
    case workspace

    var id: String { rawValue }

    var label: String {
        switch self {
        case .external: "链接电脑/NAS 文件"
        case .workspace: "导入到 Workspace"
        }
    }

    var help: String {
        switch self {
        case .external: "只记录电脑上的原文件位置，不复制视频。"
        case .workspace: "让电脑后端复制到 Workspace，适合需要后端保存一份视频副本的情况。"
        }
    }

    var systemImage: String {
        switch self {
        case .external: "folder"
        case .workspace: "tray.and.arrow.down"
        }
    }
}

struct ModelProfile: Codable, Hashable, Identifiable {
    var id: String
    var name: String
    var providerType: String
    var baseURL: String
    var model: String
    var contextWindow: Int?
    var maxTokens: Int?
    var hasAPIKey: Bool

    enum CodingKeys: String, CodingKey {
        case id
        case name
        case providerType = "provider_type"
        case baseURL = "base_url"
        case model
        case contextWindow = "context_window"
        case maxTokens = "max_tokens"
        case hasAPIKey = "has_api_key"
    }
}

struct ModelSettings: Codable, Hashable {
    var profiles: [ModelProfile]
    var translationModelID: String
    var learningModelID: String
    var globalModelID: String
    var asrModelID: String
    var studyDetailLevel: StudyDetailLevel

    enum CodingKeys: String, CodingKey {
        case profiles
        case translationModelID = "translation_model_id"
        case learningModelID = "learning_model_id"
        case globalModelID = "global_model_id"
        case asrModelID = "asr_model_id"
        case studyDetailLevel = "study_detail_level"
    }

    func profile(for id: String) -> ModelProfile? {
        profiles.first { $0.id == id } ?? profiles.first
    }

    var configuredProfileCount: Int {
        profiles.filter(\.hasAPIKey).count
    }
}

struct OnlineASRServiceSettings: Codable, Hashable {
    var hasAPIKey: Bool

    enum CodingKeys: String, CodingKey {
        case hasAPIKey = "has_api_key"
    }
}

struct OnlineASRCustomSettings: Codable, Hashable {
    var baseURL: String?
    var model: String?
    var hasAPIKey: Bool

    enum CodingKeys: String, CodingKey {
        case baseURL = "base_url"
        case model
        case hasAPIKey = "has_api_key"
    }
}

struct OnlineASRSettings: Codable, Hashable {
    var provider: String
    var openAI: OnlineASRServiceSettings
    var groq: OnlineASRServiceSettings
    var xai: OnlineASRServiceSettings
    var custom: OnlineASRCustomSettings

    enum CodingKeys: String, CodingKey {
        case provider
        case openAI = "openai"
        case groq
        case xai
        case custom
    }

    var providerLabel: String {
        switch provider {
        case "openai": "OpenAI Whisper"
        case "groq": "Groq Whisper"
        case "xai": "xAI"
        case "custom": "自定义"
        default: "未启用"
        }
    }

    var isReady: Bool {
        switch provider {
        case "openai":
            openAI.hasAPIKey
        case "groq":
            groq.hasAPIKey
        case "xai":
            xai.hasAPIKey
        case "custom":
            custom.hasAPIKey
                && custom.baseURL?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false
                && custom.model?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false
        default:
            false
        }
    }
}

struct TranscriptSegment: Codable, Identifiable, Hashable {
    var start: Double
    var end: Double
    var text: String

    var id: String { "\(start)-\(end)-\(text.hashValue)" }
}

enum SubtitleTextParser {
    private struct PartialSegment {
        var start: Double
        var end: Double?
        var text: String
    }

    private static let timecodeRegex = try! NSRegularExpression(
        pattern: #"(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[,.]\d{1,3})?"#
    )

    static func decodeText(from data: Data) -> String? {
        for encoding in [
            String.Encoding.utf8,
            .utf16,
            .utf16LittleEndian,
            .utf16BigEndian,
            .isoLatin1,
        ] {
            if let text = String(data: data, encoding: encoding) {
                return text
            }
        }
        return nil
    }

    static func parse(_ raw: String, filename: String, duration: Double?) -> [TranscriptSegment] {
        let cleaned = raw
            .replacingOccurrences(of: "\u{FEFF}", with: "")
            .replacingOccurrences(of: "\r\n", with: "\n")
            .replacingOccurrences(of: "\r", with: "\n")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleaned.isEmpty else { return [] }

        let cueSegments = parseCueBlocks(cleaned)
        if !cueSegments.isEmpty {
            return normalize(cueSegments, duration: duration)
        }

        let timedSegments = parseTimedLines(cleaned)
        if !timedSegments.isEmpty {
            return normalize(timedSegments, duration: duration)
        }

        return buildPlainTextTranscript(cleaned, filename: filename, duration: duration)
    }

    private static func parseCueBlocks(_ raw: String) -> [PartialSegment] {
        guard raw.contains("-->") else { return [] }
        var segments: [PartialSegment] = []
        for block in raw.components(separatedBy: "\n\n") {
            let lines = block
                .components(separatedBy: "\n")
                .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                .filter { !$0.isEmpty }
            guard let timeLineIndex = lines.firstIndex(where: { $0.contains("-->") }) else { continue }
            let parts = lines[timeLineIndex].components(separatedBy: "-->")
            guard parts.count >= 2,
                  let start = parseTimecode(parts[0]),
                  let end = parseTimecode(
                    parts[1]
                        .trimmingCharacters(in: .whitespacesAndNewlines)
                        .components(separatedBy: .whitespaces)
                        .first ?? ""
                  ) else {
                continue
            }
            let text = lines[(timeLineIndex + 1)...]
                .map(normalizeSubtitleLine)
                .filter { !$0.isEmpty }
                .joined(separator: " ")
            if !text.isEmpty {
                segments.append(PartialSegment(start: start, end: end, text: text))
            }
        }
        return segments
    }

    private static func parseTimedLines(_ raw: String) -> [PartialSegment] {
        var segments: [PartialSegment] = []
        for sourceLine in raw.components(separatedBy: "\n") {
            let line = sourceLine.trimmingCharacters(in: .whitespacesAndNewlines)
            if line.isEmpty || isSubtitleHeaderLine(line) { continue }
            if let assSegment = parseASSDialogueLine(line) {
                segments.append(assSegment)
                continue
            }

            let matches = timecodeMatches(in: line)
            if matches.count >= 2,
               let start = parseTimecode(matches[0].value),
               let end = parseTimecode(matches[1].value) {
                let rawText = String(line[matches[1].range.upperBound...])
                let text = normalizeSubtitleLine(rawText)
                if !text.isEmpty {
                    segments.append(PartialSegment(start: start, end: end, text: text))
                }
                continue
            }

            if let match = matches.first,
               line.distance(from: line.startIndex, to: match.range.lowerBound) <= 2,
               let start = parseTimecode(match.value) {
                let rawText = String(line[match.range.upperBound...])
                let text = normalizeSubtitleLine(rawText)
                if !text.isEmpty {
                    segments.append(PartialSegment(start: start, end: nil, text: text))
                }
            }
        }
        return segments
    }

    private static func buildPlainTextTranscript(_ raw: String, filename: String, duration: Double?) -> [TranscriptSegment] {
        let lines = raw
            .components(separatedBy: "\n")
            .map(normalizeSubtitleLine)
            .filter { !$0.isEmpty && !isSubtitleHeaderLine($0) }
        guard !lines.isEmpty else { return [] }
        let safeDuration = duration.flatMap { $0 > 0 ? $0 : nil }
        let step = safeDuration.map { $0 / Double(lines.count) } ?? 3
        return lines.enumerated().map { index, line in
            let start = roundSeconds(Double(index) * step)
            let end: Double
            if let safeDuration, index == lines.count - 1 {
                end = safeDuration
            } else {
                end = roundSeconds(Double(index + 1) * step)
            }
            return TranscriptSegment(
                start: start,
                end: max(roundSeconds(start + 0.8), end),
                text: stripImportedFilenamePrefix(line, filename: filename)
            )
        }
    }

    private static func normalize(_ segments: [PartialSegment], duration: Double?) -> [TranscriptSegment] {
        let sorted = segments
            .map { PartialSegment(start: $0.start, end: $0.end, text: $0.text.trimmingCharacters(in: .whitespacesAndNewlines)) }
            .filter { !$0.text.isEmpty }
            .sorted { $0.start < $1.start }
        let safeDuration = duration.flatMap { $0 > 0 ? $0 : nil }
        let fallbackStep = safeDuration.map { max(1, $0 / Double(max(sorted.count, 1))) } ?? 3

        return sorted.enumerated().map { index, segment in
            let nextStart = index + 1 < sorted.count ? sorted[index + 1].start : nil
            let candidateEnd: Double
            if let end = segment.end, end > segment.start {
                candidateEnd = end
            } else if let nextStart, nextStart > segment.start {
                candidateEnd = nextStart
            } else if let safeDuration, safeDuration > segment.start {
                candidateEnd = min(safeDuration, segment.start + fallbackStep)
            } else {
                candidateEnd = segment.start + fallbackStep
            }
            return TranscriptSegment(
                start: roundSeconds(segment.start),
                end: roundSeconds(max(candidateEnd, segment.start + 0.8)),
                text: segment.text
            )
        }
    }

    private static func parseASSDialogueLine(_ line: String) -> PartialSegment? {
        guard line.lowercased().hasPrefix("dialogue:") else { return nil }
        let payload = line.drop(while: { $0 != ":" }).dropFirst().trimmingCharacters(in: .whitespacesAndNewlines)
        let parts = payload.components(separatedBy: ",")
        guard parts.count >= 10,
              let start = parseTimecode(parts[1]),
              let end = parseTimecode(parts[2]) else {
            return nil
        }
        let text = normalizeSubtitleLine(parts.dropFirst(9).joined(separator: ","))
        guard !text.isEmpty else { return nil }
        return PartialSegment(start: start, end: end, text: text)
    }

    private static func parseTimecode(_ value: String) -> Double? {
        let normalized = value
            .trimmingCharacters(in: CharacterSet(charactersIn: " \t[]()（）【】"))
            .replacingOccurrences(of: ",", with: ".")
        let parts = normalized.components(separatedBy: ":")
        guard parts.count >= 2, parts.count <= 3 else { return nil }
        let numbers = parts.compactMap(Double.init)
        guard numbers.count == parts.count else { return nil }
        if numbers.count == 2 {
            return numbers[0] * 60 + numbers[1]
        }
        return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    }

    private static func normalizeSubtitleLine(_ line: String) -> String {
        line
            .replacingOccurrences(of: #"\{[^}]*\}"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: #"\\[Nn]"#, with: " ", options: .regularExpression)
            .replacingOccurrences(of: #"<[^>]+>"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: #"^#{1,6}\s+"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: #"^>\s+"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: #"^[-*+]\s+"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: #"^\d+[.)]\s+"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: #"^[\]\)）】\s:：\-–—~>]+"#, with: "", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func isSubtitleHeaderLine(_ line: String) -> Bool {
        ["WEBVTT", "NOTE", "STYLE", "REGION"].contains(line.trimmingCharacters(in: .whitespacesAndNewlines).uppercased())
    }

    private static func stripImportedFilenamePrefix(_ text: String, filename: String) -> String {
        let basename = filename.replacingOccurrences(of: #"\.[^.]+$"#, with: "", options: .regularExpression)
        if !basename.isEmpty, text.hasPrefix("\(basename):") {
            return String(text.dropFirst(basename.count + 1)).trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return text
    }

    private static func timecodeMatches(in line: String) -> [(value: String, range: Range<String.Index>)] {
        let nsRange = NSRange(line.startIndex..<line.endIndex, in: line)
        return timecodeRegex.matches(in: line, range: nsRange).compactMap { match in
            guard let range = Range(match.range, in: line) else { return nil }
            return (String(line[range]), range)
        }
    }

    private static func roundSeconds(_ value: Double) -> Double {
        max(0, (value * 1000).rounded() / 1000)
    }
}

struct ASRCorrectionRequest: Codable {
    var outputLanguage: OutputLanguage

    enum CodingKeys: String, CodingKey {
        case outputLanguage = "output_language"
    }
}

struct ASRCorrectionSuggestion: Codable, Identifiable, Hashable {
    var id: String
    var segmentIndex: Int
    var start: Double
    var end: Double
    var originalText: String
    var correctedText: String
    var confidence: Double
    var reason: String
    var evidence: String?
    var status: String
    var source: String

    enum CodingKeys: String, CodingKey {
        case id
        case segmentIndex = "segment_index"
        case start
        case end
        case originalText = "original_text"
        case correctedText = "corrected_text"
        case confidence
        case reason
        case evidence
        case status
        case source
    }
}

struct ASRCorrectionResult: Codable, Hashable {
    var jobID: String
    var itemID: String
    var generatedAt: String
    var searchEnabled: Bool
    var searchProvider: String?
    var suggestions: [ASRCorrectionSuggestion]

    enum CodingKeys: String, CodingKey {
        case jobID = "job_id"
        case itemID = "item_id"
        case generatedAt = "generated_at"
        case searchEnabled = "search_enabled"
        case searchProvider = "search_provider"
        case suggestions
    }
}

struct TranscriptUpdateRequest: Codable {
    var transcript: [TranscriptSegment]
}

struct TimeRange: Codable, Identifiable, Hashable {
    var start: Double
    var end: Double
    var title: String
    var summary: String
    var priority: String

    var id: String { "\(start)-\(end)-\(title)" }
}

struct OutlineNode: Codable, Identifiable, Hashable {
    var id: String
    var start: Double
    var end: Double
    var title: String
    var summary: String
    var children: [OutlineNode]
}

struct StudyMaterial: Codable, Hashable {
    var oneLine: String
    var translatedTitle: String?
    var contextSummary: String?
    var timeMap: [TimeRange]
    var outline: [OutlineNode]
    var detailedNotes: String
    var highFidelityText: String
    var translatedTranscript: [TranscriptSegment]
    var prerequisites: [String]
    var thoughtPrompts: [String]
    var reviewSuggestions: [String]
    var beginnerFocus: [String]
    var experiencedGuidance: [String]

    enum CodingKeys: String, CodingKey {
        case oneLine = "one_line"
        case translatedTitle = "translated_title"
        case contextSummary = "context_summary"
        case timeMap = "time_map"
        case outline
        case detailedNotes = "detailed_notes"
        case highFidelityText = "high_fidelity_text"
        case translatedTranscript = "translated_transcript"
        case prerequisites
        case thoughtPrompts = "thought_prompts"
        case reviewSuggestions = "review_suggestions"
        case beginnerFocus = "beginner_focus"
        case experiencedGuidance = "experienced_guidance"
    }
}

struct VideoMetadata: Codable, Hashable {
    var id: String
    var title: String
    var duration: Double?
    var uploader: String?
    var channel: String?
    var creator: String?
    var description: String?
    var playlistTitle: String?
    var playlistIndex: Int?
    var webpageURL: String
    var extractor: String
    var streamURL: String?
    var hlsManifestURL: String?
    var language: String?
    var subtitles: [String]
    var automaticCaptions: [String]

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case duration
        case uploader
        case channel
        case creator
        case description
        case playlistTitle = "playlist_title"
        case playlistIndex = "playlist_index"
        case webpageURL = "webpage_url"
        case extractor
        case streamURL = "stream_url"
        case hlsManifestURL = "hls_manifest_url"
        case language
        case subtitles
        case automaticCaptions = "automatic_captions"
    }
}

struct LibraryState: Codable, Hashable {
    var manualCollections: [String]
    var manualCollectionGroups: [String]
    var collectionOrder: [String]
    var collectionGroupOrder: [String]
    var collectionGroupAssignments: [String: String]

    init(
        manualCollections: [String] = [],
        manualCollectionGroups: [String] = [],
        collectionOrder: [String] = [],
        collectionGroupOrder: [String] = [],
        collectionGroupAssignments: [String: String] = [:]
    ) {
        self.manualCollections = manualCollections
        self.manualCollectionGroups = manualCollectionGroups
        self.collectionOrder = collectionOrder
        self.collectionGroupOrder = collectionGroupOrder
        self.collectionGroupAssignments = collectionGroupAssignments
    }

    enum CodingKeys: String, CodingKey {
        case manualCollections = "manual_collections"
        case manualCollectionGroups = "manual_collection_groups"
        case collectionOrder = "collection_order"
        case collectionGroupOrder = "collection_group_order"
        case collectionGroupAssignments = "collection_group_assignments"
    }

    func collectionGroupTitle(for item: CourseItem) -> String? {
        let explicitGroup = item.collectionGroupTitle?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !explicitGroup.isEmpty {
            return explicitGroup
        }
        let assignedGroup = collectionGroupAssignments[Self.collectionStorageKey(item.collectionTitle)]?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return assignedGroup.isEmpty ? nil : assignedGroup
    }

    static func collectionStorageKey(_ value: String?) -> String {
        let normalized = (value ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        return normalized.isEmpty ? "collection:" : "collection:\(normalized)"
    }

    static func collectionGroupStorageKey(_ value: String?) -> String {
        let normalized = (value ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        return normalized.isEmpty ? "collection-group:" : "collection-group:\(normalized)"
    }

    func sortsCategoryBefore(_ left: String, _ right: String) -> Bool {
        sortedByPersistedOrder(
            left,
            right,
            bottomTitle: "未分类",
            order: collectionGroupOrder,
            key: Self.collectionGroupStorageKey
        )
    }

    func sortsCollectionBefore(_ left: String, _ right: String) -> Bool {
        sortedByPersistedOrder(
            left,
            right,
            bottomTitle: "未归档",
            order: collectionOrder,
            key: Self.collectionStorageKey
        )
    }

    private func sortedByPersistedOrder(
        _ left: String,
        _ right: String,
        bottomTitle: String,
        order: [String],
        key: (String?) -> String
    ) -> Bool {
        if left == bottomTitle && right != bottomTitle { return false }
        if right == bottomTitle && left != bottomTitle { return true }
        var orderIndex: [String: Int] = [:]
        for (index, value) in order.enumerated() where orderIndex[value] == nil {
            orderIndex[value] = index
        }
        let leftIndex = orderIndex[key(left)]
        let rightIndex = orderIndex[key(right)]
        if let leftIndex, let rightIndex, leftIndex != rightIndex {
            return leftIndex < rightIndex
        }
        if leftIndex != nil, rightIndex == nil { return true }
        if leftIndex == nil, rightIndex != nil { return false }
        return left.localizedStandardCompare(right) == .orderedAscending
    }
}

struct CourseItem: Codable, Identifiable, Hashable {
    var id: String
    var sourceURL: String
    var title: String
    var customTitle: Bool?
    var collectionGroupTitle: String?
    var collectionTitle: String?
    var courseIndex: Double?
    var sortOrder: Double?
    var duration: Double?
    var createdAt: String
    var updatedAt: String?
    var transcript: [TranscriptSegment]
    var transcriptSource: TranscriptSource?
    var metadata: VideoMetadata?
    var study: StudyMaterial?
    var videoSourceType: VideoSourceType?
    var localVideoPath: String?

    enum CodingKeys: String, CodingKey {
        case id
        case sourceURL = "source_url"
        case title
        case customTitle = "custom_title"
        case collectionGroupTitle = "collection_group_title"
        case collectionTitle = "collection_title"
        case courseIndex = "course_index"
        case sortOrder = "sort_order"
        case duration
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case transcript
        case transcriptSource = "transcript_source"
        case metadata
        case study
        case videoSourceType = "video_source_type"
        case localVideoPath = "local_video_path"
    }

    var displayTitle: String {
        if let translated = study?.translatedTitle, !translated.isEmpty {
            return translated
        }
        return title
    }

    var collectionDisplayName: String {
        let value = collectionTitle?.trimmingCharacters(in: .whitespacesAndNewlines)
        return value?.isEmpty == false ? value! : "未归档"
    }

    var collectionSectionDisplayName: String {
        let group = collectionGroupTitle?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard !group.isEmpty else { return collectionDisplayName }
        return "\(group) / \(collectionDisplayName)"
    }

    var hasPlayableLocalVideo: Bool {
        localVideoPath?.isEmpty == false
    }

    var canCacheToComputer: Bool {
        let source = sourceURL.trimmingCharacters(in: .whitespacesAndNewlines)
        return !source.isEmpty
            && !source.hasPrefix("local-video://")
            && !source.hasPrefix("external-video://")
            && localVideoPath?.isEmpty != false
            && videoSourceType != .external
    }

    var canRemoveComputerCache: Bool {
        let source = sourceURL.trimmingCharacters(in: .whitespacesAndNewlines)
        return localVideoPath?.isEmpty == false
            && !source.hasPrefix("local-video://")
            && !source.hasPrefix("external-video://")
            && videoSourceType != .external
    }

    var offlinePayloadScore: Int {
        var score = transcript.count * 100
        if metadata != nil {
            score += 10
        }
        if localVideoPath?.isEmpty == false {
            score += 1
        }
        guard let study else { return score }

        score += study.detailedNotes.count
        score += study.highFidelityText.count
        score += study.translatedTranscript.count * 50
        score += study.timeMap.count * 20
        score += study.outline.count * 20
        score += study.prerequisites.count
        score += study.thoughtPrompts.count
        score += study.reviewSuggestions.count
        score += study.beginnerFocus.count
        score += study.experiencedGuidance.count
        return score
    }
}

extension CourseItem {
    func applyingLibraryState(_ state: LibraryState) -> CourseItem {
        var copy = self
        copy.collectionGroupTitle = state.collectionGroupTitle(for: self)
        return copy
    }
}

struct CourseShareItem: Codable, Hashable {
    var id: String?
    var sourceURL: String
    var title: String
    var customTitle: Bool?
    var collectionGroupTitle: String?
    var collectionTitle: String?
    var courseIndex: Double?
    var sortOrder: Double?
    var duration: Double?
    var createdAt: String?
    var transcript: [TranscriptSegment]
    var transcriptSource: TranscriptSource?
    var metadata: VideoMetadata?
    var study: StudyMaterial?

    enum CodingKeys: String, CodingKey {
        case id
        case sourceURL = "source_url"
        case title
        case customTitle = "custom_title"
        case collectionGroupTitle = "collection_group_title"
        case collectionTitle = "collection_title"
        case courseIndex = "course_index"
        case sortOrder = "sort_order"
        case duration
        case createdAt = "created_at"
        case transcript
        case transcriptSource = "transcript_source"
        case metadata
        case study
    }
}

extension CourseShareItem {
    init(exporting item: CourseItem) {
        self.id = item.id
        self.sourceURL = item.sourceURL
        self.title = item.title
        self.customTitle = item.customTitle ?? false
        self.collectionGroupTitle = nil
        self.collectionTitle = nil
        self.courseIndex = nil
        self.sortOrder = nil
        self.duration = item.duration
        self.createdAt = item.createdAt
        self.transcript = item.transcript
        self.transcriptSource = .imported
        self.metadata = item.metadata
        self.study = item.study
    }
}

struct CourseSharePackage: Codable, Hashable {
    var format: String
    var version: Int
    var exportedAt: String?
    var message: String?
    var items: [CourseShareItem]

    enum CodingKeys: String, CodingKey {
        case format
        case version
        case exportedAt = "exported_at"
        case message
        case items
    }
}

extension CourseSharePackage {
    init(exporting item: CourseItem, exportedAt: Date = Date()) {
        self.format = "course-navigator-share"
        self.version = 1
        self.exportedAt = ISO8601DateFormatter().string(from: exportedAt)
        self.message = nil
        self.items = [CourseShareItem(exporting: item)]
    }
}

struct CourseImportResponse: Codable, Hashable {
    var items: [CourseItem]
    var message: String?
}

struct StudyJobStatus: Codable, Identifiable, Hashable {
    var jobID: String
    var itemID: String
    var status: String
    var progress: Int
    var phase: String
    var message: String
    var error: String?
    var startedAt: String?
    var updatedAt: String?

    var id: String { jobID }

    enum CodingKeys: String, CodingKey {
        case jobID = "job_id"
        case itemID = "item_id"
        case status
        case progress
        case phase
        case message
        case error
        case startedAt = "started_at"
        case updatedAt = "updated_at"
    }

    var isFinished: Bool {
        status == "succeeded" || status == "failed"
    }
}

struct ExtractRequest: Codable {
    var url: String
    var mode: ExtractMode
    var browser: String
    var cookiesPath: String?
    var language: String
    var subtitleSource: TranscriptSource

    enum CodingKeys: String, CodingKey {
        case url
        case mode
        case browser
        case cookiesPath = "cookies_path"
        case language
        case subtitleSource = "subtitle_source"
    }
}

struct CookieTextRequest: Codable {
    var text: String
}

struct CookieTextResponse: Codable {
    var path: String
}

struct StudyRequest: Codable {
    var outputLanguage: OutputLanguage
    var section: StudySection
    var detailLevel: StudyDetailLevel?

    enum CodingKeys: String, CodingKey {
        case outputLanguage = "output_language"
        case section
        case detailLevel = "detail_level"
    }
}

struct TranslationRequest: Codable {
    var outputLanguage: OutputLanguage

    enum CodingKeys: String, CodingKey {
        case outputLanguage = "output_language"
    }
}

struct DownloadRequest: Codable {
    var url: String
    var mode: ExtractMode
    var browser: String
    var cookiesPath: String?

    enum CodingKeys: String, CodingKey {
        case url
        case mode
        case browser
        case cookiesPath = "cookies_path"
    }
}

struct LocalVideoFilePickerRequest: Codable {
    var mode: LocalVideoImportMode
}

struct VideoSourceBindingRequest: Codable {
    var sourceType: String
    var url: String?
    var path: String?

    enum CodingKeys: String, CodingKey {
        case sourceType = "source_type"
        case url
        case path
    }
}

struct CourseItemUpdate: Codable {
    var title: String
}

struct CourseDetailsUpdate: Encodable {
    var title: String
    var translatedTitle: String?
    var collectionGroupTitle: String?
    var collectionTitle: String?
    var courseIndex: Double?
    var sortOrder: Double?

    enum CodingKeys: String, CodingKey {
        case title
        case translatedTitle = "translated_title"
        case collectionGroupTitle = "collection_group_title"
        case collectionTitle = "collection_title"
        case courseIndex = "course_index"
        case sortOrder = "sort_order"
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(title, forKey: .title)
        try container.encodeNilOrValue(translatedTitle, forKey: .translatedTitle)
        try container.encodeNilOrValue(collectionGroupTitle, forKey: .collectionGroupTitle)
        try container.encodeNilOrValue(collectionTitle, forKey: .collectionTitle)
        try container.encodeNilOrValue(courseIndex, forKey: .courseIndex)
        try container.encodeNilOrValue(sortOrder, forKey: .sortOrder)
    }
}

private extension KeyedEncodingContainer {
    mutating func encodeNilOrValue<T: Encodable>(_ value: T?, forKey key: Key) throws {
        if let value {
            try encode(value, forKey: key)
        } else {
            try encodeNil(forKey: key)
        }
    }
}

struct DeleteResponse: Codable {
    var deleted: Bool
}

struct HealthResponse: Codable {
    var ok: Bool
    var name: String
}
