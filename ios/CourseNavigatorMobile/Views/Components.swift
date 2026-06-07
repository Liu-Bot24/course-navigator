import SwiftUI

struct StatusBadge: View {
    var text: String
    var color: Color
    var minWidth: CGFloat?
    var height: CGFloat?

    init(text: String, color: Color, minWidth: CGFloat? = nil, height: CGFloat? = nil) {
        self.text = text
        self.color = color
        self.minWidth = minWidth
        self.height = height
    }

    var body: some View {
        Text(text)
            .font(.caption.weight(.medium))
            .lineLimit(1)
            .fixedSize(horizontal: true, vertical: false)
            .padding(.horizontal, 8)
            .padding(.vertical, height == nil ? 4 : 0)
            .frame(minWidth: minWidth)
            .frame(height: height)
            .background(color.opacity(0.14), in: Capsule())
            .foregroundStyle(color)
    }
}

extension View {
    @ViewBuilder
    func adaptiveSegmentedPickerStyle() -> some View {
        modifier(AdaptiveSegmentedPickerStyle())
    }

    @ViewBuilder
    func urlInputHints() -> some View {
        #if os(iOS)
        self
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()
            .keyboardType(.URL)
        #else
        self
        #endif
    }

    @ViewBuilder
    func decimalInputHints() -> some View {
        #if os(iOS)
        self.keyboardType(.decimalPad)
        #else
        self
        #endif
    }

    @ViewBuilder
    func plainTextInputHints() -> some View {
        #if os(iOS)
        self
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()
        #else
        self
        #endif
    }

    @ViewBuilder
    func videoSourceInputHints(isRemote: Bool) -> some View {
        if isRemote {
            self.urlInputHints()
        } else {
            self.plainTextInputHints()
        }
    }

    @ViewBuilder
    func inlineNavigationTitle() -> some View {
        #if os(iOS)
        self.navigationBarTitleDisplayMode(.inline)
        #else
        self
        #endif
    }
}

private struct AdaptiveSegmentedPickerStyle: ViewModifier {
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

    @ViewBuilder
    func body(content: Content) -> some View {
        #if os(iOS)
        if horizontalSizeClass == .compact {
            content.pickerStyle(.menu)
        } else {
            content.pickerStyle(.segmented)
        }
        #else
        content.pickerStyle(.segmented)
        #endif
    }
}

#Preview {
    StatusBadge(text: "已连接", color: .green)
}
