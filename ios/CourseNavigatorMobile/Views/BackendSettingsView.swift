import SwiftUI

struct BackendSettingsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @StateObject private var discovery = BackendDiscovery()
    @State private var draft = BackendEndpoint(name: "", baseURL: "")

    var body: some View {
        NavigationStack {
            Form {
                Section("当前后端") {
                    Picker("连接设备", selection: activeEndpointBinding) {
                        ForEach(model.endpoints) { endpoint in
                            Text(endpoint.name).tag(Optional(endpoint.id))
                        }
                    }
                    Button {
                        Task { await model.refreshAll() }
                    } label: {
                        Label("测试连接", systemImage: "wifi")
                    }
                }

                BackendCapabilitySection(
                    modelSettings: model.modelSettings,
                    onlineASRSettings: model.onlineASRSettings,
                    errorMessage: model.backendCapabilityError
                )

                Section("局域网发现") {
                    if discovery.backends.isEmpty {
                        HStack {
                            if discovery.isScanning {
                                ProgressView()
                            } else {
                                Image(systemName: "dot.radiowaves.left.and.right")
                                    .foregroundStyle(.secondary)
                            }
                            Text(discovery.isScanning ? "正在扫描电脑后端" : "没有发现可用后端")
                                .foregroundStyle(.secondary)
                        }
                    } else {
                        ForEach(discovery.backends) { backend in
                            Button {
                                let endpoint = BackendEndpoint(name: backend.name, baseURL: backend.baseURL)
                                let endpointID = model.saveEndpoint(endpoint, mergeByBaseURL: true)
                                Task { await model.selectEndpoint(endpointID) }
                            } label: {
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(backend.name)
                                        .font(.headline)
                                    Text(backend.baseURL)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                            }
                        }
                    }

                    Button {
                        discovery.start()
                    } label: {
                        Label("重新扫描", systemImage: "arrow.clockwise")
                    }

                    if let errorMessage = discovery.errorMessage {
                        Text(errorMessage)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }

                Section("添加或更新") {
                    TextField("名称", text: $draft.name)
                    TextField("后端地址，例如 http://192.168.6.160:18000", text: $draft.baseURL)
                        .urlInputHints()
                    Button {
                        saveDraft()
                    } label: {
                        Label("保存并连接", systemImage: "checkmark")
                    }
                    .disabled(draft.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || draft.normalizedBaseURL == nil)
                }

                Section("已保存设备") {
                    ForEach(model.endpoints) { endpoint in
                        Button {
                            Task { await model.selectEndpoint(endpoint.id) }
                        } label: {
                            HStack(spacing: 10) {
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(endpoint.name)
                                        .font(.headline)
                                    Text(endpoint.baseURL)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                                Spacer()
                                if model.activeEndpointID == endpoint.id {
                                    Image(systemName: "checkmark.circle.fill")
                                        .foregroundStyle(.green)
                                }
                            }
                        }
                        .buttonStyle(.plain)
                        .swipeActions {
                            Button("删除", role: .destructive) {
                                model.deleteEndpoint(endpoint)
                            }
                            Button("编辑") {
                                draft = endpoint
                            }
                            .tint(.blue)
                        }
                    }
                }

                Section("电脑端要求") {
                    Label("电脑后端需要用局域网地址启动，而不是只监听 127.0.0.1。", systemImage: "desktopcomputer")
                    Label("iPhone/iPad 首次访问会请求本地网络权限。", systemImage: "iphone")
                }
            }
            .navigationTitle("后端设备")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("关闭") { dismiss() }
                }
            }
            .onAppear {
                discovery.start()
            }
            .onDisappear {
                discovery.stop()
            }
        }
    }

    private var activeEndpointBinding: Binding<UUID?> {
        Binding {
            model.activeEndpointID
        } set: { id in
            Task { await model.selectEndpoint(id) }
        }
    }

    private func saveDraft() {
        let endpoint = BackendEndpoint(
            id: draft.id,
            name: draft.name.trimmingCharacters(in: .whitespacesAndNewlines),
            baseURL: draft.baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        )
        let endpointID = model.saveEndpoint(endpoint, mergeByBaseURL: true)
        draft = BackendEndpoint(name: "", baseURL: "")
        Task { await model.selectEndpoint(endpointID) }
    }
}

struct BackendCapabilitySection: View {
    var modelSettings: ModelSettings?
    var onlineASRSettings: OnlineASRSettings?
    var errorMessage: String?

    var body: some View {
        Section("后端能力") {
            if let errorMessage {
                Label(errorMessage, systemImage: "exclamationmark.triangle")
                    .foregroundStyle(.secondary)
            } else if let modelSettings {
                CapabilityRow(
                    title: "学习地图",
                    subtitle: modelSettings.profile(for: modelSettings.learningModelID)?.model ?? modelSettings.learningModelID,
                    isReady: modelSettings.profile(for: modelSettings.learningModelID)?.hasAPIKey == true
                )
                CapabilityRow(
                    title: "字幕翻译",
                    subtitle: modelSettings.profile(for: modelSettings.translationModelID)?.model ?? modelSettings.translationModelID,
                    isReady: modelSettings.profile(for: modelSettings.translationModelID)?.hasAPIKey == true
                )
                CapabilityRow(
                    title: "ASR 校正",
                    subtitle: modelSettings.profile(for: modelSettings.asrModelID)?.model ?? modelSettings.asrModelID,
                    isReady: modelSettings.profile(for: modelSettings.asrModelID)?.hasAPIKey == true
                )
                CapabilityRow(
                    title: "在线 ASR",
                    subtitle: onlineASRSettings?.providerLabel ?? "未读取",
                    isReady: onlineASRSettings?.isReady == true
                )
                HStack {
                    Text("可用模型档案")
                    Spacer()
                    Text("\(modelSettings.configuredProfileCount)/\(modelSettings.profiles.count)")
                        .foregroundStyle(.secondary)
                }
            } else {
                Label("连接后读取模型和字幕能力", systemImage: "cpu")
                    .foregroundStyle(.secondary)
            }
        }
    }
}

struct CapabilityRow: View {
    var title: String
    var subtitle: String
    var isReady: Bool

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: isReady ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                .foregroundStyle(isReady ? .green : .orange)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                Text(subtitle.isEmpty ? "未配置" : subtitle)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer()
            StatusBadge(text: isReady ? "可用" : "需配置", color: isReady ? .green : .orange)
        }
    }
}
