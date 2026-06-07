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
                    if model.endpoints.isEmpty {
                        Label("还没有保存后端设备", systemImage: "server.rack")
                            .foregroundStyle(.secondary)
                        Text("启动电脑后端后等待局域网发现，或手动填写脚本打印的地址。")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    } else {
                        Picker("连接设备", selection: activeEndpointBinding) {
                            ForEach(model.endpoints) { endpoint in
                                Text(endpointPickerTitle(for: endpoint)).tag(Optional(endpoint.id))
                            }
                        }
                        if let activeEndpoint = model.activeEndpoint {
                            EndpointAddressText(activeEndpoint.baseURL)
                        }
                    }
                    Button {
                        Task { await model.refreshAll() }
                    } label: {
                        Label("测试连接", systemImage: "wifi")
                    }
                    .disabled(model.activeEndpoint == nil || model.connectionStatus == .checking)
                }

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
                                connectEndpoint(endpointID)
                            } label: {
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(backend.name)
                                        .font(.headline)
                                    EndpointAddressText(backend.baseURL)
                                }
                            }
                        }
                    }

                    Button {
                        discovery.start()
                    } label: {
                        Label("重新扫描", systemImage: "arrow.clockwise")
                    }
                    .disabled(discovery.isScanning)

                    if let errorMessage = discovery.errorMessage {
                        Text(errorMessage)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }

                Section("添加或更新") {
                    TextField("名称（可选）", text: $draft.name)
                    TextField("后端地址，例如 http://电脑局域网IP:18000", text: $draft.baseURL)
                        .urlInputHints()
                    if let draftAddressWarning {
                        Text(draftAddressWarning)
                            .font(.caption)
                            .foregroundStyle(.orange)
                    }
                    Button {
                        saveDraft()
                    } label: {
                        Label("保存并连接", systemImage: "checkmark")
                    }
                    .disabled(!canSaveDraft)
                }

                Section("已保存设备") {
                    if model.endpoints.isEmpty {
                        Label("暂无已保存设备", systemImage: "tray")
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(model.endpoints) { endpoint in
                            Button {
                                connectEndpoint(endpoint.id)
                            } label: {
                                HStack(spacing: 10) {
                                    VStack(alignment: .leading, spacing: 4) {
                                        Text(endpoint.name)
                                            .font(.headline)
                                        EndpointAddressText(endpoint.baseURL)
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
                                    Task { await model.deleteEndpoint(endpoint) }
                                }
                                Button("编辑") {
                                    draft = endpoint
                                }
                                .tint(.blue)
                            }
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
            .refreshable {
                discovery.start()
                await model.refreshAll()
            }
        }
    }

    private var activeEndpointBinding: Binding<UUID?> {
        Binding {
            model.activeEndpointID
        } set: { id in
            guard let id else {
                Task { await model.selectEndpoint(nil) }
                return
            }
            connectEndpoint(id)
        }
    }

    private var canSaveDraft: Bool {
        draft.normalizedBaseURL != nil
            && draft.isUsableOnCurrentDevice
    }

    private var draftAddressWarning: String? {
        let trimmedBaseURL = draft.baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedBaseURL.isEmpty else { return nil }
        if draft.hasUnsupportedBackendPath {
            return "后端地址只需要电脑根地址；可以粘贴 /api 开头的地址，但不要填写其它路径。"
        }
        guard draft.normalizedBaseURL != nil else {
            return "后端地址需要是 http/https 地址，例如 http://电脑局域网IP:18000。"
        }
        if draft.isWildcardBaseURL {
            return "不要填写 0.0.0.0；这是电脑后端的监听地址。请填写脚本打印的局域网 IP。"
        }
        if draft.isLinkLocalBaseURL {
            return "不要填写 169.254 或 fe80 开头的地址；请确认电脑和手机在同一 Wi-Fi 后使用局域网地址。"
        }
        #if targetEnvironment(simulator)
        return nil
        #else
        return draft.isLoopbackBaseURL
            ? "iPhone/iPad 上不能使用 127.0.0.1 或 localhost；请填写电脑脚本打印的局域网地址。"
            : nil
        #endif
    }

    private func saveDraft() {
        guard canSaveDraft else {
            model.errorMessage = draftAddressWarning ?? "请填写有效的电脑后端地址"
            return
        }
        let endpoint = BackendEndpoint(
            id: draft.id,
            name: normalizedDraftName,
            baseURL: draft.baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        )
        let endpointID = model.saveEndpoint(endpoint, mergeByBaseURL: true)
        draft = BackendEndpoint(name: "", baseURL: "")
        connectEndpoint(endpointID)
    }

    private var normalizedDraftName: String {
        let name = draft.name.trimmingCharacters(in: .whitespacesAndNewlines)
        if !name.isEmpty {
            return name
        }
        guard let url = draft.normalizedBaseURL, let host = url.host else {
            return "电脑后端"
        }
        if let port = url.port {
            return "\(host):\(port)"
        }
        return host
    }

    private func endpointPickerTitle(for endpoint: BackendEndpoint) -> String {
        let address = endpointShortAddress(endpoint)
        let name = endpoint.name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { return address }
        return name == address ? name : "\(name) · \(address)"
    }

    private func endpointShortAddress(_ endpoint: BackendEndpoint) -> String {
        guard let url = endpoint.normalizedBaseURL, let host = url.host else {
            return endpoint.baseURL
        }
        if let port = url.port {
            return "\(host):\(port)"
        }
        return host
    }

    private func connectEndpoint(_ endpointID: UUID) {
        Task {
            await model.selectEndpoint(endpointID)
            if model.isBackendOnline {
                dismiss()
            }
        }
    }
}

private struct EndpointAddressText: View {
    var address: String

    init(_ address: String) {
        self.address = address
    }

    var body: some View {
        Text(address)
            .font(.caption.monospaced())
            .foregroundStyle(.secondary)
            .lineLimit(1)
            .truncationMode(.middle)
            .textSelection(.enabled)
    }
}
