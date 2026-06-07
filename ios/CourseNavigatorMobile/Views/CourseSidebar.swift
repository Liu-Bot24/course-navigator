import SwiftUI

struct CourseSidebar: View {
    @Environment(AppModel.self) private var model
    @Binding var selectedCourseID: String?
    @Binding var showingDevices: Bool
    @Binding var showingStorage: Bool
    @State private var searchText = ""
    @State private var expandedCategories = Set<String>()
    @State private var expandedAlbums = Set<String>()

    private var groupedCourses: [CourseCategoryGroup] {
        let categoryGroups = Dictionary(grouping: filteredCourses, by: Self.categoryTitle)
        return categoryGroups.keys.sorted(by: model.sortsCategoryBefore).map { categoryTitle in
            let categoryCourses = categoryGroups[categoryTitle] ?? []
            let albumGroups = Dictionary(grouping: categoryCourses, by: \.collectionDisplayName)
            let albums = albumGroups.keys.sorted(by: model.sortsCollectionBefore).map { albumTitle in
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

            if !model.canShowCourseContent {
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
        .searchable(text: $searchText, prompt: "搜索课程或专辑")
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
                    showingStorage = true
                } label: {
                    Label("存储", systemImage: "internaldrive")
                }
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
            VStack(alignment: .leading, spacing: 2) {
                Text(titleLines.primary)
                    .font(.headline)
                    .lineLimit(1)
                    .truncationMode(.tail)
                Text(titleLines.secondary)
                    .font(.headline)
                    .lineLimit(1)
                    .truncationMode(.tail)
                    .opacity(titleLines.hasSecondaryLine ? 1 : 0)
                Text(model.activeEndpoint?.baseURL ?? "添加电脑后端地址")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            ViewThatFits(in: .horizontal) {
                HStack(spacing: HeaderMetrics.controlSpacing) {
                    HeaderStatusLabel(text: model.connectionStatus.label, color: statusColor)
                    headerModeButton
                    headerManageButton
                }
                VStack(alignment: .leading, spacing: 8) {
                    HeaderStatusLabel(text: model.connectionStatus.label, color: statusColor)
                    HStack(spacing: HeaderMetrics.controlSpacing) {
                        headerModeButton
                        headerManageButton
                    }
                }
            }
            if case .offline(let message) = model.connectionStatus {
                Text(message)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
            if !model.isBackendOnline, !model.courses.isEmpty {
                Label("正在使用当前设备上已同步的课程资料", systemImage: "internaldrive")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 6)
    }

    @ViewBuilder
    private var headerModeButton: some View {
        if model.isLocalMode {
            Button {
                Task { await model.useOnlineMode() }
            } label: {
                HeaderActionLabel(title: "WiFi 模式", systemImage: "wifi", imageScale: .small)
            }
            .buttonStyle(.plain)
            .disabled(model.connectionStatus == .checking)
        } else if model.canEnterLocalMode {
            Button {
                Task { await model.enterActiveLocalMode() }
            } label: {
                HeaderActionLabel(title: "本地模式", systemImage: "internaldrive")
            }
            .buttonStyle(.plain)
            .disabled(model.isSyncingCourseLibrary || model.connectionStatus == .checking)
        }
    }

    private var headerManageButton: some View {
        Button {
            showingDevices = true
        } label: {
            HeaderTextButtonLabel(title: "管理")
        }
        .buttonStyle(.plain)
    }

    private var titleLines: (primary: String, secondary: String, hasSecondaryLine: Bool) {
        let name = model.activeEndpoint?.name.trimmingCharacters(in: .whitespacesAndNewlines)
        let fallback = "未选择后端"
        guard let rawName = name, !rawName.isEmpty else {
            return (fallback, " ", false)
        }
        guard let range = rawName.range(of: " on ", options: [.caseInsensitive]) else {
            return (rawName, " ", false)
        }
        let primary = String(rawName[..<range.lowerBound])
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let secondary = String(rawName[range.lowerBound...])
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return (primary.isEmpty ? rawName : primary, secondary.isEmpty ? " " : secondary, !secondary.isEmpty)
    }

    private var statusIcon: String {
        switch model.connectionStatus {
        case .online: "checkmark.circle.fill"
        case .local: "internaldrive.fill"
        case .checking: "clock"
        case .offline: "exclamationmark.triangle.fill"
        case .unknown: "circle.dashed"
        }
    }

    private var statusColor: Color {
        switch model.connectionStatus {
        case .online: .green
        case .local: .blue
        case .checking: .orange
        case .offline: .red
        case .unknown: .secondary
        }
    }
}

private enum HeaderMetrics {
    static let controlHeight: CGFloat = 34
    static let controlSpacing: CGFloat = 8
    static let statusWidth: CGFloat = 70
    static let modeWidth: CGFloat = 116
    static let manageWidth: CGFloat = 70
    static let cornerRadius: CGFloat = 8
}

private struct HeaderStatusLabel: View {
    var text: String
    var color: Color

    var body: some View {
        Text(text)
            .font(.subheadline.weight(.semibold))
            .lineLimit(1)
            .minimumScaleFactor(0.9)
            .frame(width: HeaderMetrics.statusWidth, height: HeaderMetrics.controlHeight)
            .background(color.opacity(0.12), in: RoundedRectangle(cornerRadius: HeaderMetrics.cornerRadius, style: .continuous))
            .foregroundStyle(color)
    }
}

private struct HeaderActionLabel: View {
    var title: String
    var systemImage: String
    var imageScale: Image.Scale = .medium

    var body: some View {
        Label {
            Text(title)
                .lineLimit(1)
                .minimumScaleFactor(0.9)
        } icon: {
            Image(systemName: systemImage)
                .imageScale(imageScale)
        }
        .font(.body.weight(.semibold))
        .frame(width: HeaderMetrics.modeWidth, height: HeaderMetrics.controlHeight)
        .background(Color.primary.opacity(0.06), in: RoundedRectangle(cornerRadius: HeaderMetrics.cornerRadius, style: .continuous))
        .foregroundStyle(Color.accentColor)
    }
}

private struct HeaderTextButtonLabel: View {
    var title: String

    var body: some View {
        Text(title)
            .font(.body.weight(.semibold))
            .lineLimit(1)
            .minimumScaleFactor(0.9)
            .frame(width: HeaderMetrics.manageWidth, height: HeaderMetrics.controlHeight)
            .background(Color.primary.opacity(0.06), in: RoundedRectangle(cornerRadius: HeaderMetrics.cornerRadius, style: .continuous))
            .foregroundStyle(Color.accentColor)
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

struct StorageManagementView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var expandedCacheCategories = Set<String>()
    @State private var expandedCacheAlbums = Set<String>()

    private var cacheGroups: [StorageCacheCategoryGroup] {
        let courseByID = model.courses.reduce(into: [String: CourseItem]()) { partialResult, item in
            partialResult[item.id] = item
        }
        let categoryGroups = Dictionary(grouping: model.activeDeviceVideoCacheRecords) { record in
            categoryTitle(for: courseByID[record.courseID])
        }
        return categoryGroups.keys.sorted(by: model.sortsCategoryBefore).map { categoryTitle in
            let records = categoryGroups[categoryTitle] ?? []
            let albumGroups = Dictionary(grouping: records) { record in
                albumTitle(for: courseByID[record.courseID])
            }
            let albums = albumGroups.keys.sorted(by: model.sortsCollectionBefore).map { albumTitle in
                StorageCacheAlbumGroup(
                    categoryTitle: categoryTitle,
                    title: albumTitle,
                    records: sortedRecords(albumGroups[albumTitle] ?? [])
                )
            }
            return StorageCacheCategoryGroup(title: categoryTitle, albums: albums)
        }
    }

    var body: some View {
        NavigationStack {
            List {
                Section("课程资料") {
                    HStack {
                        Label("\(model.courses.count) 门课程", systemImage: "books.vertical")
                        Spacer()
                        if model.isSyncingCourseLibrary {
                            ProgressView()
                        }
                    }
                    Button {
                        model.startCourseLibrarySync(allowOnlineConnection: true)
                    } label: {
                        Label(model.isSyncingCourseLibrary ? "正在同步" : "同步课程资料", systemImage: "arrow.triangle.2.circlepath")
                    }
                    .disabled(model.activeEndpoint == nil || model.connectionStatus == .checking || model.isSyncingCourseLibrary)
                }

                Section(MobileDeviceText.videoCacheTitle) {
                    if model.activeDeviceVideoCacheRecords.isEmpty {
                        ContentUnavailableView(
                            "没有本机视频缓存",
                            systemImage: "internaldrive",
                            description: Text("在课程页点击缓存后，视频会保存到当前设备。")
                        )
                        .listRowSeparator(.hidden)
                    } else {
                        ForEach(cacheGroups) { category in
                            DisclosureGroup(isExpanded: cacheCategoryExpansionBinding(for: category.title)) {
                                ForEach(category.albums) { album in
                                    DisclosureGroup(isExpanded: cacheAlbumExpansionBinding(for: album)) {
                                        ForEach(album.records) { record in
                                            StorageCacheRow(record: record) {
                                                model.removeDeviceVideoCache(record)
                                            }
                                        }
                                    } label: {
                                        StorageCacheGroupLabel(
                                            title: album.title,
                                            count: album.records.count,
                                            byteCount: album.byteCount,
                                            systemImage: "rectangle.stack"
                                        )
                                    }
                                }
                            } label: {
                                StorageCacheGroupLabel(
                                    title: category.title,
                                    count: category.recordCount,
                                    byteCount: category.byteCount,
                                    systemImage: "folder"
                                )
                            }
                        }
                    }
                }
            }
            .navigationTitle("本机存储")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("关闭") { dismiss() }
                }
            }
        }
    }

    private func cacheCategoryExpansionBinding(for title: String) -> Binding<Bool> {
        Binding {
            expandedCacheCategories.contains(title)
        } set: { isExpanded in
            if isExpanded {
                expandedCacheCategories.insert(title)
            } else {
                expandedCacheCategories.remove(title)
            }
        }
    }

    private func cacheAlbumExpansionBinding(for album: StorageCacheAlbumGroup) -> Binding<Bool> {
        let key = album.expansionKey
        return Binding {
            expandedCacheAlbums.contains(key)
        } set: { isExpanded in
            if isExpanded {
                expandedCacheAlbums.insert(key)
            } else {
                expandedCacheAlbums.remove(key)
            }
        }
    }

    private func categoryTitle(for item: CourseItem?) -> String {
        let value = item?.collectionGroupTitle?.trimmingCharacters(in: .whitespacesAndNewlines)
        return value?.isEmpty == false ? value! : "未分类"
    }

    private func albumTitle(for item: CourseItem?) -> String {
        item?.collectionDisplayName ?? "未归档"
    }

    private func sortedRecords(_ records: [DeviceVideoCacheRecord]) -> [DeviceVideoCacheRecord] {
        records.sorted { left, right in
            left.courseTitle.localizedStandardCompare(right.courseTitle) == .orderedAscending
        }
    }
}

private struct StorageCacheRow: View {
    var record: DeviceVideoCacheRecord
    var delete: () -> Void

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            VStack(alignment: .leading, spacing: 5) {
                Text(record.courseTitle)
                    .font(.callout.weight(.medium))
                    .lineLimit(2)
                HStack(spacing: 8) {
                    Label(record.sizeLabel, systemImage: "internaldrive")
                    Text(record.cachedAt, style: .date)
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }
            Spacer()
            Button(role: .destructive) {
                delete()
            } label: {
                Image(systemName: "trash")
            }
            .buttonStyle(.borderless)
            .accessibilityLabel("删除缓存")
        }
        .swipeActions {
            Button("删除", role: .destructive) {
                delete()
            }
        }
    }
}

private struct StorageCacheCategoryGroup: Identifiable {
    var title: String
    var albums: [StorageCacheAlbumGroup]

    var id: String { title }

    var recordCount: Int {
        albums.reduce(0) { $0 + $1.records.count }
    }

    var byteCount: Int64 {
        albums.reduce(0) { $0 + $1.byteCount }
    }
}

private struct StorageCacheAlbumGroup: Identifiable {
    var categoryTitle: String
    var title: String
    var records: [DeviceVideoCacheRecord]

    var id: String { expansionKey }

    var expansionKey: String {
        "\(categoryTitle)|\(title)"
    }

    var byteCount: Int64 {
        records.reduce(0) { $0 + $1.byteCount }
    }
}

private struct StorageCacheGroupLabel: View {
    var title: String
    var count: Int
    var byteCount: Int64
    var systemImage: String

    var body: some View {
        HStack(spacing: 10) {
            Label(title, systemImage: systemImage)
                .font(.body.weight(.medium))
                .lineLimit(2)
            Spacer(minLength: 12)
            VStack(alignment: .trailing, spacing: 2) {
                Text("\(count) 个")
                Text(ByteCountFormatter.string(fromByteCount: byteCount, countStyle: .file))
            }
            .font(.caption.monospacedDigit())
            .foregroundStyle(.secondary)
        }
    }
}
