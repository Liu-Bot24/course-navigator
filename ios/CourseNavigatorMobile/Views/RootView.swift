import SwiftUI

struct RootView: View {
    @Environment(AppModel.self) private var model
    @State private var showingDevices = false
    @State private var didOfferInitialBackendSetup = false

    var body: some View {
        @Bindable var model = model
        NavigationSplitView {
            CourseSidebar(
                selectedCourseID: $model.selectedCourseID,
                showingDevices: $showingDevices
            )
        } detail: {
            if model.isBackendOnline {
                CourseDetail()
            } else {
                BackendRequiredView(showingDevices: $showingDevices)
            }
        }
        .sheet(isPresented: $showingDevices) {
            BackendSettingsView()
        }
        .onAppear {
            offerInitialBackendSetupIfNeeded()
        }
        .onChange(of: model.connectionStatus) { _, _ in
            offerInitialBackendSetupIfNeeded()
        }
        .onChange(of: model.selectedCourseID) { _, _ in
            Task { await model.refreshSelectedCourse() }
        }
        .alert("需要处理", isPresented: Binding(
            get: { model.errorMessage != nil },
            set: { if !$0 { model.errorMessage = nil } }
        )) {
            Button("好", role: .cancel) { model.errorMessage = nil }
        } message: {
            Text(model.errorMessage ?? "")
        }
    }

    private func offerInitialBackendSetupIfNeeded() {
        guard Self.shouldOfferInitialBackendSetup(
            didOffer: didOfferInitialBackendSetup,
            isShowingDevices: showingDevices,
            endpointCount: model.endpoints.count,
            connectionStatus: model.connectionStatus
        ) else { return }
        didOfferInitialBackendSetup = true
        showingDevices = true
    }

    static func shouldOfferInitialBackendSetup(
        didOffer: Bool,
        isShowingDevices: Bool,
        endpointCount: Int,
        connectionStatus: ConnectionStatus
    ) -> Bool {
        guard !didOffer, !isShowingDevices else { return false }
        switch connectionStatus {
        case .online, .checking:
            return false
        case .unknown:
            return endpointCount == 0
        case .offline:
            return true
        }
    }
}

struct BackendRequiredView: View {
    @Environment(AppModel.self) private var model
    @Binding var showingDevices: Bool

    var body: some View {
        VStack(spacing: 18) {
            Image(systemName: statusIcon)
                .font(.system(size: 44, weight: .semibold))
                .foregroundStyle(statusColor)

            VStack(spacing: 8) {
                Text(title)
                    .font(.title2.weight(.semibold))
                Text(model.activeEndpoint?.name ?? "未选择后端")
                    .font(.headline)
                if let endpoint = model.activeEndpoint {
                    Text(endpoint.baseURL)
                        .font(.callout.monospaced())
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                        .multilineTextAlignment(.center)
                }
                Text(detail)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }

            ViewThatFits(in: .horizontal) {
                HStack(spacing: 10) {
                    retryButton
                    backendButton
                }
                VStack(spacing: 10) {
                    retryButton
                    backendButton
                }
            }
        }
        .padding(28)
        .frame(maxWidth: 520)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .navigationTitle("连接")
    }

    private var retryButton: some View {
        Button {
            Task { await model.refreshAll() }
        } label: {
            Label(model.connectionStatus == .checking ? "连接中" : "重新连接", systemImage: "arrow.clockwise")
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(.borderedProminent)
        .disabled(model.connectionStatus == .checking)
    }

    private var backendButton: some View {
        Button {
            showingDevices = true
        } label: {
            Label("后端设备", systemImage: "server.rack")
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(.bordered)
    }

    private var title: String {
        switch model.connectionStatus {
        case .checking:
            "正在连接电脑后端"
        case .unknown:
            "等待电脑后端"
        case .offline:
            "电脑后端未连接"
        case .online:
            "电脑后端已连接"
        }
    }

    private var detail: String {
        switch model.connectionStatus {
        case .offline(let message):
            message
        case .checking:
            "正在检查当前设备。"
        case .unknown:
            "选择一台电脑后端开始。"
        case .online(let name):
            name
        }
    }

    private var statusIcon: String {
        switch model.connectionStatus {
        case .online:
            "checkmark.circle.fill"
        case .checking:
            "clock"
        case .offline:
            "exclamationmark.triangle.fill"
        case .unknown:
            "dot.radiowaves.left.and.right"
        }
    }

    private var statusColor: Color {
        switch model.connectionStatus {
        case .online:
            .green
        case .checking:
            .orange
        case .offline:
            .red
        case .unknown:
            .secondary
        }
    }
}
