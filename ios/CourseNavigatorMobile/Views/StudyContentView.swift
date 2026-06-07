import SwiftUI

struct StudyContentView: View {
    var item: CourseItem
    var outputLanguage: OutputLanguage
    var currentTime: Double?
    var seekTo: ((Double) -> Void)?
    @State private var tab: StudyTab = .guide
    @State private var transcriptDisplayMode: TranscriptDisplayMode = .bilingual
    @State private var focusAroundPlayback = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 10) {
                    studyTabPicker
                    focusPlaybackButton
                }
                VStack(spacing: 10) {
                    studyTabPicker
                    focusPlaybackButton
                }
            }

            switch tab {
            case .guide:
                GuideView(study: item.study)
            case .timeline:
                TimeMapView(
                    study: item.study,
                    currentTime: currentTime,
                    focusAroundPlayback: activeFocusAroundPlayback,
                    seekTo: seekTo
                )
            case .outline:
                OutlineRootView(study: item.study, currentTime: currentTime, seekTo: seekTo)
            case .notes:
                NotesView(study: item.study)
            case .transcript:
                TranscriptView(
                    item: item,
                    outputLanguage: outputLanguage,
                    displayMode: $transcriptDisplayMode,
                    currentTime: currentTime,
                    focusAroundPlayback: activeFocusAroundPlayback,
                    seekTo: seekTo
                )
            }
        }
    }

    private var studyTabPicker: some View {
        Picker("学习内容", selection: $tab) {
            ForEach(StudyTab.allCases) { tab in
                Text(tab.title).tag(tab)
            }
        }
        .pickerStyle(.segmented)
    }

    private var focusPlaybackButton: some View {
        Button {
            focusAroundPlayback.toggle()
        } label: {
            Label(focusAroundPlayback ? "显示全部" : "当前附近", systemImage: focusAroundPlayback ? "list.bullet" : "scope")
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(.bordered)
        .disabled(!canFocusAroundPlayback)
    }

    private var activeFocusAroundPlayback: Bool {
        focusAroundPlayback && canFocusAroundPlayback
    }

    private var canFocusAroundPlayback: Bool {
        currentTime != nil && (tab == .timeline || tab == .transcript)
    }
}

enum StudyTab: String, CaseIterable, Identifiable {
    case guide
    case timeline
    case outline
    case notes
    case transcript

    var id: String { rawValue }

    var title: String {
        switch self {
        case .guide: "导读"
        case .timeline: "时间"
        case .outline: "大纲"
        case .notes: "笔记"
        case .transcript: "字幕"
        }
    }
}

enum TranscriptDisplayMode: String, CaseIterable, Identifiable {
    case source
    case translated
    case bilingual

    var id: String { rawValue }

    var title: String {
        switch self {
        case .source: "原文"
        case .translated: "译文"
        case .bilingual: "双语"
        }
    }
}

struct GuideView: View {
    var study: StudyMaterial?

    var body: some View {
        if let study {
            VStack(alignment: .leading, spacing: 16) {
                StudySectionBlock(title: "一句话", text: study.oneLine)
                if let context = study.contextSummary, !context.isEmpty {
                    StudySectionBlock(title: "上下文", text: context)
                }
                BulletList(title: "预备知识", items: study.prerequisites)
                BulletList(title: "思考问题", items: study.thoughtPrompts)
                BulletList(title: "复习建议", items: study.reviewSuggestions)
                BulletList(title: "新手重点", items: study.beginnerFocus)
                BulletList(title: "进阶路线", items: study.experiencedGuidance)
            }
        } else {
            EmptyStudyView()
        }
    }
}

struct TimeMapView: View {
    var study: StudyMaterial?
    var currentTime: Double?
    var focusAroundPlayback: Bool
    var seekTo: ((Double) -> Void)?

    var body: some View {
        if let ranges = study?.timeMap, !ranges.isEmpty {
            LazyVStack(alignment: .leading, spacing: 12) {
                if focusAroundPlayback, let currentTime {
                    FocusWindowHint(currentTime: currentTime, shownCount: displayedRanges.count, totalCount: ranges.count)
                }
                ForEach(displayedRanges) { range in
                    let isActive = range.contains(currentTime)
                    Button {
                        seekTo?(range.start)
                    } label: {
                        VStack(alignment: .leading, spacing: 6) {
                            HStack {
                                Text(formatTime(range.start))
                                    .font(.caption.monospacedDigit())
                                    .foregroundStyle(.secondary)
                                Text(range.title)
                                    .font(.headline)
                                Spacer()
                                if seekTo != nil {
                                    Image(systemName: "play.circle")
                                        .foregroundStyle(.secondary)
                                }
                                StatusBadge(text: priorityLabel(range.priority), color: priorityColor(range.priority))
                            }
                            Text(range.summary)
                                .font(.callout)
                                .foregroundStyle(.secondary)
                        }
                        .padding()
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background {
                            StudyRowBackground(isActive: isActive)
                        }
                    }
                    .buttonStyle(.plain)
                    .disabled(seekTo == nil)
                }
            }
        } else {
            EmptyStudyView()
        }
    }

    private var displayedRanges: [TimeRange] {
        guard let ranges = study?.timeMap, !ranges.isEmpty else { return [] }
        guard focusAroundPlayback, let currentTime else { return ranges }
        return ranges.nearbyWindow(around: currentTime, leading: 1, trailing: 2)
    }
}

struct OutlineRootView: View {
    var study: StudyMaterial?
    var currentTime: Double?
    var seekTo: ((Double) -> Void)?

    var body: some View {
        if let outline = study?.outline, !outline.isEmpty {
            LazyVStack(alignment: .leading, spacing: 10) {
                ForEach(outline) { node in
                    OutlineNodeView(node: node, currentTime: currentTime, seekTo: seekTo)
                }
            }
        } else {
            EmptyStudyView()
        }
    }
}

struct OutlineNodeView: View {
    var node: OutlineNode
    var currentTime: Double?
    var seekTo: ((Double) -> Void)?

    var body: some View {
        let isActive = node.contains(currentTime)
        DisclosureGroup {
            Text(node.summary)
                .font(.callout)
                .foregroundStyle(.secondary)
                .padding(.vertical, 4)
            ForEach(node.children) { child in
                OutlineNodeView(node: child, currentTime: currentTime, seekTo: seekTo)
                    .padding(.leading, 10)
            }
        } label: {
            HStack {
                SeekTimeButton(time: node.start, seekTo: seekTo)
                Text(node.title)
                    .font(.body.weight(.medium))
            }
        }
        .padding()
        .background {
            StudyRowBackground(isActive: isActive)
        }
    }
}

struct NotesView: View {
    var study: StudyMaterial?

    var body: some View {
        if let study {
            VStack(alignment: .leading, spacing: 16) {
                StudySectionBlock(title: "详细解释", text: study.detailedNotes)
                StudySectionBlock(title: "高保真文本", text: study.highFidelityText)
            }
        } else {
            EmptyStudyView()
        }
    }
}

struct TranscriptView: View {
    var item: CourseItem
    var outputLanguage: OutputLanguage
    @Binding var displayMode: TranscriptDisplayMode
    var currentTime: Double?
    var focusAroundPlayback: Bool
    var seekTo: ((Double) -> Void)?
    @State private var correctionSuggestions: [ASRCorrectionSuggestion] = []
    @State private var correctionMessage: String?

    var body: some View {
        if transcriptLines.isEmpty {
            ContentUnavailableView("没有字幕", systemImage: "captions.bubble")
        } else {
            VStack(alignment: .leading, spacing: 12) {
                ASRCorrectionPanel(
                    item: item,
                    outputLanguage: outputLanguage,
                    suggestions: $correctionSuggestions,
                    message: $correctionMessage
                )

                if hasTranslatedTranscript {
                    Picker("字幕显示", selection: $displayMode) {
                        ForEach(TranscriptDisplayMode.allCases) { mode in
                            Text(mode.title).tag(mode)
                        }
                    }
                    .pickerStyle(.segmented)
                }

                LazyVStack(alignment: .leading, spacing: 10) {
                    if focusAroundPlayback, let currentTime {
                        FocusWindowHint(currentTime: currentTime, shownCount: displayedTranscriptLines.count, totalCount: transcriptLines.count)
                    }
                    ForEach(displayedTranscriptLines) { line in
                        let isActive = line.contains(currentTime)
                        HStack(alignment: .top, spacing: 10) {
                            SeekTimeButton(time: line.start, seekTo: seekTo)
                                .frame(width: 62, alignment: .leading)
                            VStack(alignment: .leading, spacing: 6) {
                                if let source = line.source {
                                    TranscriptTextLine(label: line.translated == nil ? nil : "原文", text: source)
                                }
                                if let translated = line.translated {
                                    TranscriptTextLine(label: line.source == nil ? nil : "译文", text: translated)
                                }
                            }
                        }
                        .padding(.vertical, 6)
                        .padding(.horizontal, 8)
                        .background {
                            StudyRowBackground(isActive: isActive, cornerRadius: 7)
                        }
                    }
                }
            }
            .onChange(of: item.id) {
                correctionSuggestions = []
                correctionMessage = nil
            }
        }
    }

    private var displayedTranscriptLines: [TranscriptDisplayLine] {
        guard focusAroundPlayback, let currentTime else { return transcriptLines }
        return transcriptLines.nearbyWindow(around: currentTime, leading: 2, trailing: 4)
    }

    private var hasTranslatedTranscript: Bool {
        item.study?.translatedTranscript.isEmpty == false
    }

    private var effectiveDisplayMode: TranscriptDisplayMode {
        hasTranslatedTranscript ? displayMode : .source
    }

    private var transcriptLines: [TranscriptDisplayLine] {
        let translated = item.study?.translatedTranscript ?? []
        switch effectiveDisplayMode {
        case .source:
            return item.transcript.map { segment in
                TranscriptDisplayLine(start: segment.start, end: segment.end, source: segment.text, translated: nil)
            }
        case .translated:
            return translated.map { segment in
                TranscriptDisplayLine(start: segment.start, end: segment.end, source: nil, translated: segment.text)
            }
        case .bilingual:
            if item.transcript.isEmpty {
                return translated.map { segment in
                    TranscriptDisplayLine(start: segment.start, end: segment.end, source: nil, translated: segment.text)
                }
            }
            return item.transcript.enumerated().map { index, segment in
                let translatedSegment = translated[safe: index] ?? translated.nearest(to: segment.start)
                return TranscriptDisplayLine(
                    start: segment.start,
                    end: segment.end,
                    source: segment.text,
                    translated: translatedSegment?.text
                )
            }
        }
    }
}

struct ASRCorrectionPanel: View {
    @Environment(AppModel.self) private var model
    var item: CourseItem
    var outputLanguage: OutputLanguage
    @Binding var suggestions: [ASRCorrectionSuggestion]
    @Binding var message: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ViewThatFits(in: .horizontal) {
                HStack {
                    runButton
                    Spacer()
                    if !suggestions.isEmpty {
                        StatusBadge(text: "\(suggestions.count) 条建议", color: .orange)
                    }
                }
                VStack(alignment: .leading, spacing: 8) {
                    runButton
                    if !suggestions.isEmpty {
                        StatusBadge(text: "\(suggestions.count) 条建议", color: .orange)
                    }
                }
            }

            if let message {
                Text(message)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            if !suggestions.isEmpty {
                LazyVStack(alignment: .leading, spacing: 8) {
                    ForEach(suggestions) { suggestion in
                        ASRCorrectionSuggestionRow(
                            suggestion: suggestion,
                            accept: {
                                await accept(suggestion)
                            }
                        )
                    }
                }
            }
        }
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 8))
    }

    private var runButton: some View {
        Button {
            Task { await runCorrection() }
        } label: {
            Label("生成 ASR 校正建议", systemImage: "wand.and.stars")
        }
        .buttonStyle(.bordered)
        .disabled(model.isLoading || item.transcript.isEmpty)
    }

    private func runCorrection() async {
        message = nil
        suggestions = []
        let result = await model.generateASRCorrectionSuggestions(
            for: item,
            outputLanguage: outputLanguage
        )
        suggestions = result
        if result.isEmpty, model.errorMessage == nil {
            message = "没有发现需要校正的字幕"
        }
    }

    private func accept(_ suggestion: ASRCorrectionSuggestion) async {
        await model.acceptASRCorrection(suggestion, itemID: item.id)
        if model.errorMessage == nil {
            suggestions.removeAll { $0.id == suggestion.id }
            message = "已保存字幕"
        }
    }
}

struct ASRCorrectionSuggestionRow: View {
    var suggestion: ASRCorrectionSuggestion
    var accept: () async -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(formatTime(suggestion.start))
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
                StatusBadge(text: confidenceLabel, color: .orange)
                Spacer()
                Button {
                    Task { await accept() }
                } label: {
                    Label("接受", systemImage: "checkmark")
                }
                .buttonStyle(.borderedProminent)
            }

            VStack(alignment: .leading, spacing: 5) {
                TranscriptTextLine(label: "原文", text: suggestion.originalText)
                TranscriptTextLine(label: "建议", text: suggestion.correctedText)
            }

            if !suggestion.reason.isEmpty {
                Text(suggestion.reason)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding()
        .background {
            StudyRowBackground(isActive: false, cornerRadius: 8)
        }
    }

    private var confidenceLabel: String {
        "\(Int((suggestion.confidence * 100).rounded()))%"
    }
}

struct TranscriptDisplayLine: Identifiable, Hashable {
    var start: Double
    var end: Double
    var source: String?
    var translated: String?

    var id: String {
        "\(start)-\(source ?? "")-\(translated ?? "")"
    }
}

struct StudyRowBackground: View {
    var isActive: Bool
    var cornerRadius: Double = 8

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: cornerRadius)
                .fill(.thinMaterial)
            if isActive {
                RoundedRectangle(cornerRadius: cornerRadius)
                    .fill(Color.accentColor.opacity(0.14))
            }
        }
        .overlay {
            RoundedRectangle(cornerRadius: cornerRadius)
                .stroke(isActive ? Color.accentColor.opacity(0.55) : Color.clear, lineWidth: 1)
        }
    }
}

struct FocusWindowHint: View {
    var currentTime: Double
    var shownCount: Int
    var totalCount: Int

    var body: some View {
        Label("当前 \(formatTime(currentTime)) 附近：\(shownCount)/\(totalCount)", systemImage: "scope")
            .font(.caption)
            .foregroundStyle(.secondary)
            .padding(.horizontal, 8)
    }
}

struct TranscriptTextLine: View {
    var label: String?
    var text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            if let label {
                Text(label)
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(.secondary)
            }
            Text(text)
                .font(.body)
                .textSelection(.enabled)
        }
    }
}

struct SeekTimeButton: View {
    var time: Double
    var seekTo: ((Double) -> Void)?

    var body: some View {
        if let seekTo {
            Button {
                seekTo(time)
            } label: {
                Label(formatTime(time), systemImage: "play.circle")
                    .labelStyle(.titleAndIcon)
                    .font(.caption.monospacedDigit())
            }
            .buttonStyle(.plain)
            .foregroundStyle(.secondary)
        } else {
            Text(formatTime(time))
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
        }
    }
}

struct StudySectionBlock: View {
    var title: String
    var text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.headline)
            Text(text.isEmpty ? "暂无内容" : text)
                .font(.body)
                .textSelection(.enabled)
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 8))
    }
}

struct BulletList: View {
    var title: String
    var items: [String]

    var body: some View {
        if !items.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                Text(title)
                    .font(.headline)
                ForEach(items, id: \.self) { item in
                    Label(item, systemImage: "circle.fill")
                        .font(.callout)
                }
            }
            .padding()
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 8))
        }
    }
}

struct EmptyStudyView: View {
    var body: some View {
        ContentUnavailableView(
            "还没有学习地图",
            systemImage: "map",
            description: Text("先完成字幕提取，然后在上方生成学习地图。")
        )
        .frame(minHeight: 180)
    }
}

func formatTime(_ value: Double) -> String {
    let total = max(0, Int(value.rounded()))
    let hours = total / 3600
    let minutes = (total % 3600) / 60
    let seconds = total % 60
    if hours > 0 {
        return String(format: "%d:%02d:%02d", hours, minutes, seconds)
    }
    return String(format: "%02d:%02d", minutes, seconds)
}

func priorityLabel(_ value: String) -> String {
    switch value {
    case "focus": "重点"
    case "review": "复习"
    case "skip": "略过"
    default: "浏览"
    }
}

func priorityColor(_ value: String) -> Color {
    switch value {
    case "focus": .red
    case "review": .purple
    case "skip": .secondary
    default: .blue
    }
}

private protocol TimedStudyItem {
    var start: Double { get }
    var end: Double { get }
}

extension TimeRange: TimedStudyItem {}
extension TranscriptDisplayLine: TimedStudyItem {}

private extension Array where Element: TimedStudyItem {
    func nearbyWindow(around time: Double, leading: Int, trailing: Int) -> [Element] {
        guard !isEmpty else { return [] }
        let activeIndex = firstIndex { item in
            time >= item.start && time < Swift.max(item.end, item.start + 0.5)
        }
        let nearestIndex = activeIndex ?? indices.min { left, right in
            abs(self[left].start - time) < abs(self[right].start - time)
        } ?? startIndex
        let lowerBound = Swift.max(startIndex, nearestIndex - leading)
        let upperBound = Swift.min(endIndex, nearestIndex + trailing + 1)
        return Array(self[lowerBound..<upperBound])
    }
}

private extension Array where Element == TranscriptSegment {
    subscript(safe index: Int) -> TranscriptSegment? {
        indices.contains(index) ? self[index] : nil
    }

    func nearest(to start: Double) -> TranscriptSegment? {
        self.min { left, right in
            abs(left.start - start) < abs(right.start - start)
        }
    }
}

private extension TimeRange {
    func contains(_ time: Double?) -> Bool {
        guard let time else { return false }
        return time >= start && time < max(end, start + 0.5)
    }
}

private extension OutlineNode {
    func contains(_ time: Double?) -> Bool {
        guard let time else { return false }
        return time >= start && time < max(end, start + 0.5)
    }
}

private extension TranscriptDisplayLine {
    func contains(_ time: Double?) -> Bool {
        guard let time else { return false }
        return time >= start && time < max(end, start + 0.5)
    }
}
