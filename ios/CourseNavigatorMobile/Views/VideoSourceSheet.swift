import SwiftUI

struct VideoSourceSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    var item: CourseItem
    @State private var sourceText = ""
    @State private var sourceKind: SourceKind = .remote

    var body: some View {
        NavigationStack {
            Form {
                Section("课程") {
                    Text(item.displayTitle)
                }

                Section("视频源") {
                    Picker("类型", selection: $sourceKind) {
                        ForEach(SourceKind.allCases) { kind in
                            Text(kind.label).tag(kind)
                        }
                    }
                    .pickerStyle(.segmented)
                    TextField(sourceKind.placeholder, text: $sourceText, axis: .vertical)
                        .urlInputHints()
                        .lineLimit(2...5)
                }

                Section("电脑选择") {
                    Button {
                        Task {
                            await model.bindVideoSourceFromComputerPicker(item)
                            if model.errorMessage == nil { dismiss() }
                        }
                    } label: {
                        Label("选择电脑/NAS 文件", systemImage: "folder")
                    }
                    .disabled(model.isLoading)

                    Text("让电脑后端打开文件选择器，并把选中的本地或 NAS 视频路径绑定到这门课程；不会复制视频文件。")
                        .font(.caption)
                        .foregroundStyle(.secondary)

                    Button {
                        Task {
                            await model.importWorkspaceVideoFromComputerPicker(item)
                            if model.errorMessage == nil { dismiss() }
                        }
                    } label: {
                        Label("导入到 Workspace", systemImage: "square.and.arrow.down")
                    }
                    .disabled(model.isLoading)

                    Text("让电脑后端选择一个视频并复制进当前 Workspace，适合希望课程文件跟项目一起保存的情况。")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Section {
                    Text(sourceKind.help)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("视频源")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("保存") {
                        Task {
                            await model.bindVideoSource(input: sourceText, asPath: sourceKind == .path)
                            if model.errorMessage == nil { dismiss() }
                        }
                    }
                    .disabled(sourceText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.isLoading)
                }
            }
        }
        .onAppear {
            sourceKind = item.videoSourceType == .external ? .path : .remote
            sourceText = item.videoSourceType == .external ? (item.localVideoPath ?? "") : item.sourceURL
        }
    }
}

enum SourceKind: String, CaseIterable, Identifiable {
    case remote
    case path

    var id: String { rawValue }

    var label: String {
        switch self {
        case .remote: "链接"
        case .path: "电脑路径"
        }
    }

    var placeholder: String {
        switch self {
        case .remote: "https://..."
        case .path: "/Volumes/NAS/course/video.mp4 或 D:\\\\course\\\\video.mp4"
        }
    }

    var help: String {
        switch self {
        case .remote:
            "在线视频链接由电脑后端解析和提取字幕。"
        case .path:
            "这里填写的是电脑后端能访问的路径，不是 iPhone/iPad 本机文件路径。"
        }
    }
}
