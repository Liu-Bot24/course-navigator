import SwiftUI

struct CourseSidebar: View {
    @Environment(AppModel.self) private var model
    @Binding var selectedCourseID: String?
    @Binding var showingDevices: Bool
    @State private var searchText = ""
    @State private var expandedCategories = Set<String>()
    @State private var expandedAlbums = Set<String>()

    private var groupedCourses: [CourseCategoryGroup] {
        let categoryGroups = Dictionary(grouping: filteredCourses, by: Self.categoryTitle)
        return categoryGroups.keys.sorted(by: Self.localizedAscending).map { categoryTitle in
            let categoryCourses = categoryGroups[categoryTitle] ?? []
            let albumGroups = Dictionary(grouping: categoryCourses, by: \.collectionDisplayName)
            let albums = albumGroups.keys.sorted(by: Self.localizedAscending).map { albumTitle in
                CourseAlbumGroup(
                    categoryTitle: categoryTitle,
                    title: albumTitle,
                    courses: sortedCourses(albumGroups[albumTitle] ?? [])
                )
            }
            return CourseCategoryGroup(title: categoryTitle, albums: albums)
        }
    }

    private var filteredCourses: [CourseItem] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return model.courses }
        return model.courses.filter { item in
            item.displayTitle.localizedCaseInsensitiveContains(query)
                || item.title.localizedCaseInsensitiveContains(query)
                || item.collectionDisplayName.localizedCaseInsensitiveContains(query)
                || item.collectionSectionDisplayName.localizedCaseInsensitiveContains(query)
                || Self.categoryTitle(for: item).localizedCaseInsensitiveContains(query)
        }
    }

    private var isSearching: Bool {
        !searchText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private var courseIDs: [String] {
        model.courses.map(\.id)
    }

    var body: some View {
        List {
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
                ForEach(groupedCourses) { category in
                    DisclosureGroup(isExpanded: categoryExpansionBinding(for: category.title)) {
                        ForEach(category.albums) { album in
                            DisclosureGroup(isExpanded: albumExpansionBinding(for: album)) {
                                ForEach(album.courses) { item in
                                    Button {
                                        selectedCourseID = item.id
                                    } label: {
                                        CourseRow(item: item)
                                    }
                                    .buttonStyle(.plain)
                                    .listRowBackground(courseRowBackground(for: item))
                                }
                            } label: {
                                CourseGroupLabel(
                                    title: album.title,
                                    count: album.courses.count,
                                    systemImage: "rectangle.stack"
                                )
                            }
                        }
                    } label: {
                        CourseGroupLabel(
                            title: category.title,
                            count: category.courseCount,
                            systemImage: "folder"
                        )
                    }
                }
            }
        }
        .onAppear {
            expandSelectedCoursePath()
        }
        .onChange(of: selectedCourseID) { _, _ in
            expandSelectedCoursePath()
        }
        .onChange(of: courseIDs) { _, _ in
            expandSelectedCoursePath()
        }
        .navigationTitle("课程")
        .searchable(text: $searchText, prompt: "搜索课程或合集")
        .refreshable {
            await model.refreshAll()
        }
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
                .disabled(model.connectionStatus == .checking)
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

    private func courseRowBackground(for item: CourseItem) -> Color {
        item.id == selectedCourseID ? Color.accentColor.opacity(0.12) : Color.clear
    }

    private func categoryExpansionBinding(for title: String) -> Binding<Bool> {
        Binding {
            isSearching || expandedCategories.contains(title)
        } set: { isExpanded in
            if isExpanded {
                expandedCategories.insert(title)
            } else {
                expandedCategories.remove(title)
            }
        }
    }

    private func albumExpansionBinding(for album: CourseAlbumGroup) -> Binding<Bool> {
        let key = album.expansionKey
        return Binding {
            isSearching || expandedAlbums.contains(key)
        } set: { isExpanded in
            if isExpanded {
                expandedAlbums.insert(key)
            } else {
                expandedAlbums.remove(key)
            }
        }
    }

    private func expandSelectedCoursePath() {
        guard let selectedCourseID, let item = model.courses.first(where: { $0.id == selectedCourseID }) else { return }
        let category = Self.categoryTitle(for: item)
        expandedCategories.insert(category)
        expandedAlbums.insert(Self.albumExpansionKey(categoryTitle: category, albumTitle: item.collectionDisplayName))
    }

    private func sortedCourses(_ courses: [CourseItem]) -> [CourseItem] {
        courses.sorted { left, right in
            let leftOrder = left.sortOrder ?? left.courseIndex
            let rightOrder = right.sortOrder ?? right.courseIndex
            if let leftOrder, let rightOrder, leftOrder != rightOrder {
                return leftOrder < rightOrder
            }
            if leftOrder != nil, rightOrder == nil { return true }
            if leftOrder == nil, rightOrder != nil { return false }
            return left.displayTitle.localizedStandardCompare(right.displayTitle) == .orderedAscending
        }
    }

    private static func categoryTitle(for item: CourseItem) -> String {
        let value = item.collectionGroupTitle?.trimmingCharacters(in: .whitespacesAndNewlines)
        return value?.isEmpty == false ? value! : "未分类"
    }

    private static func albumExpansionKey(categoryTitle: String, albumTitle: String) -> String {
        "\(categoryTitle)|\(albumTitle)"
    }

    private static func localizedAscending(_ left: String, _ right: String) -> Bool {
        left.localizedStandardCompare(right) == .orderedAscending
    }
}

private struct CourseCategoryGroup: Identifiable {
    var title: String
    var albums: [CourseAlbumGroup]

    var id: String { title }
    var courseCount: Int {
        albums.reduce(0) { $0 + $1.courses.count }
    }
}

private struct CourseAlbumGroup: Identifiable {
    var categoryTitle: String
    var title: String
    var courses: [CourseItem]

    var id: String { expansionKey }
    var expansionKey: String {
        "\(categoryTitle)|\(title)"
    }
}

private struct CourseGroupLabel: View {
    var title: String
    var count: Int
    var systemImage: String

    var body: some View {
        HStack(spacing: 8) {
            Label(title, systemImage: systemImage)
                .font(.body.weight(.medium))
            Spacer()
            Text("\(count)")
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
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
