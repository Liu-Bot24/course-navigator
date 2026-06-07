import SwiftUI

struct CourseSidebar: View {
    @Environment(AppModel.self) private var model
    @Binding var selectedCourseID: String?
    @Binding var showingImport: Bool
    @Binding var showingDevices: Bool
    @State private var searchText = ""

    var groupedCourses: [(String, [CourseItem])] {
        let groups = Dictionary(grouping: filteredCourses, by: \.collectionDisplayName)
        return groups.keys.sorted().map { key in
            (key, groups[key] ?? [])
        }
    }

    var filteredCourses: [CourseItem] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return model.courses }
        return model.courses.filter { item in
            item.displayTitle.localizedCaseInsensitiveContains(query)
                || item.title.localizedCaseInsensitiveContains(query)
                || item.collectionDisplayName.localizedCaseInsensitiveContains(query)
        }
    }

    var body: some View {
        List(selection: $selectedCourseID) {
            Section {
                BackendHeader(showingDevices: $showingDevices)
            }

            if !model.isBackendOnline {
                ContentUnavailableView(
                    "等待电脑后端",
                    systemImage: "server.rack",
                    description: Text("连接后会显示课程库。")
                )
                .listRowSeparator(.hidden)
            } else if model.courses.isEmpty {
                ContentUnavailableView(
                    "没有课程",
                    systemImage: "books.vertical",
                    description: Text("连接电脑后端后，导入一个视频链接开始学习。")
                )
                .listRowSeparator(.hidden)
            } else if filteredCourses.isEmpty {
                ContentUnavailableView.search(text: searchText)
                    .listRowSeparator(.hidden)
            } else {
                ForEach(groupedCourses, id: \.0) { collection, courses in
                    Section(collection) {
                        ForEach(courses) { item in
                            CourseRow(item: item)
                                .tag(item.id)
                        }
                    }
                }
            }
        }
        .navigationTitle("课程")
        .searchable(text: $searchText, prompt: "搜索课程或合集")
        .toolbar {
            ToolbarItem(placement: .automatic) {
                Button {
                    showingDevices = true
                } label: {
                    Label("后端", systemImage: "server.rack")
                }
            }
            ToolbarItemGroup(placement: .primaryAction) {
                Button {
                    Task { await model.refreshAll() }
                } label: {
                    Label("刷新", systemImage: "arrow.clockwise")
                }
                Button {
                    showingImport = true
                } label: {
                    Label("导入", systemImage: "plus")
                }
                .disabled(!model.isBackendOnline)
            }
        }
        .overlay {
            if model.isLoading && model.courses.isEmpty {
                ProgressView("正在读取课程")
                    .padding()
                    .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
            }
        }
    }
}

struct BackendHeader: View {
    @Environment(AppModel.self) private var model
    @Binding var showingDevices: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                Image(systemName: statusIcon)
                    .foregroundStyle(statusColor)
                VStack(alignment: .leading, spacing: 2) {
                    Text(model.activeEndpoint?.name ?? "未选择后端")
                        .font(.headline)
                    Text(model.activeEndpoint?.baseURL ?? "添加电脑后端地址")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                Spacer()
            }
            HStack {
                StatusBadge(text: model.connectionStatus.label, color: statusColor)
                Spacer()
                Button("管理") {
                    showingDevices = true
                }
                .buttonStyle(.bordered)
            }
            if case .offline(let message) = model.connectionStatus {
                Text(message)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
        }
        .padding(.vertical, 6)
    }

    private var statusIcon: String {
        switch model.connectionStatus {
        case .online: "checkmark.circle.fill"
        case .checking: "clock"
        case .offline: "exclamationmark.triangle.fill"
        case .unknown: "circle.dashed"
        }
    }

    private var statusColor: Color {
        switch model.connectionStatus {
        case .online: .green
        case .checking: .orange
        case .offline: .red
        case .unknown: .secondary
        }
    }
}

struct CourseRow: View {
    var item: CourseItem

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(item.displayTitle)
                .font(.body.weight(.medium))
                .lineLimit(2)
            HStack(spacing: 8) {
                if let index = item.courseIndex {
                    Text("#\(Int(index))")
                }
                Text(item.videoSourceType?.label ?? "视频")
                if item.study != nil {
                    Label("学习地图", systemImage: "map")
                        .labelStyle(.titleAndIcon)
                }
            }
            .font(.caption)
            .foregroundStyle(.secondary)
        }
        .padding(.vertical, 4)
    }
}
