import SwiftUI
import UIKit

@main
struct CourseNavigatorMobileApp: App {
    @Environment(\.scenePhase) private var scenePhase
    @State private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .task {
                    updateIdleTimerProtection()
                    await model.bootstrap()
                }
                .onChange(of: model.shouldKeepDeviceAwake) { _, _ in
                    updateIdleTimerProtection()
                }
                .onChange(of: scenePhase) { _, phase in
                    updateIdleTimerProtection()
                    guard phase == .active else { return }
                    Task { await model.refreshAfterForegroundActivation() }
                }
        }
    }

    private func updateIdleTimerProtection() {
        UIApplication.shared.isIdleTimerDisabled = scenePhase == .active && model.shouldKeepDeviceAwake
    }
}
