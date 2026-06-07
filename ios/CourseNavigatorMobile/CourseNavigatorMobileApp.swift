import SwiftUI

@main
struct CourseNavigatorMobileApp: App {
    @State private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .task {
                    await model.bootstrap()
                }
        }
    }
}
