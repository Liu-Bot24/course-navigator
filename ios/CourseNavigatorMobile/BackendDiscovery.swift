import Foundation

struct DiscoveredBackend: Identifiable, Hashable {
    var serviceName: String
    var serviceType: String
    var serviceDomain: String
    var name: String
    var hostName: String
    var port: Int

    var id: String {
        Self.serviceID(name: serviceName, type: serviceType, domain: serviceDomain)
    }

    var baseURL: String {
        "http://\(hostName):\(port)"
    }

    static func serviceID(name: String, type: String, domain: String) -> String {
        "\(name)|\(type)|\(domain)"
    }
}

final class BackendDiscovery: NSObject, ObservableObject {
    @Published private(set) var backends: [DiscoveredBackend] = []
    @Published private(set) var isScanning = false
    @Published private(set) var errorMessage: String?

    private let browser = NetServiceBrowser()
    private var resolvingServices: [NetService] = []

    override init() {
        super.init()
        browser.delegate = self
    }

    func start() {
        browser.stop()
        resolvingServices.forEach { $0.stop() }
        errorMessage = nil
        backends = []
        resolvingServices = []
        isScanning = true
        browser.searchForServices(ofType: "_coursenav._tcp.", inDomain: "local.")
    }

    func stop() {
        browser.stop()
        resolvingServices.forEach {
            $0.stop()
            $0.delegate = nil
        }
        resolvingServices = []
        isScanning = false
    }

    private func addResolved(_ service: NetService) {
        guard service.port > 0 else { return }
        let rawHost = service.hostName?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard !rawHost.isEmpty else { return }
        let hostName = rawHost.hasSuffix(".") ? String(rawHost.dropLast()) : rawHost
        let displayName = service.name.isEmpty ? "Course Navigator" : service.name
        let backend = DiscoveredBackend(
            serviceName: service.name,
            serviceType: service.type,
            serviceDomain: service.domain,
            name: displayName,
            hostName: hostName,
            port: service.port
        )

        if let index = backends.firstIndex(where: { $0.id == backend.id }) {
            backends[index] = backend
        } else {
            backends.append(backend)
            backends.sort {
                $0.name.localizedStandardCompare($1.name) == .orderedAscending
            }
        }
    }

    private func removeService(_ service: NetService) {
        let serviceID = DiscoveredBackend.serviceID(
            name: service.name,
            type: service.type,
            domain: service.domain
        )
        backends.removeAll { $0.id == serviceID }
        resolvingServices
            .filter { DiscoveredBackend.serviceID(name: $0.name, type: $0.type, domain: $0.domain) == serviceID }
            .forEach {
                $0.stop()
                $0.delegate = nil
            }
        resolvingServices.removeAll {
            DiscoveredBackend.serviceID(name: $0.name, type: $0.type, domain: $0.domain) == serviceID
        }
    }
}

extension BackendDiscovery: NetServiceBrowserDelegate {
    func netServiceBrowserWillSearch(_ browser: NetServiceBrowser) {
        isScanning = true
    }

    func netServiceBrowserDidStopSearch(_ browser: NetServiceBrowser) {
        isScanning = false
    }

    func netServiceBrowser(_ browser: NetServiceBrowser, didNotSearch errorDict: [String: NSNumber]) {
        errorMessage = "无法扫描局域网后端"
        isScanning = false
    }

    func netServiceBrowser(_ browser: NetServiceBrowser, didFind service: NetService, moreComing: Bool) {
        service.delegate = self
        resolvingServices.append(service)
        service.resolve(withTimeout: 5)
    }

    func netServiceBrowser(_ browser: NetServiceBrowser, didRemove service: NetService, moreComing: Bool) {
        removeService(service)
    }
}

extension BackendDiscovery: NetServiceDelegate {
    func netServiceDidResolveAddress(_ sender: NetService) {
        addResolved(sender)
        resolvingServices.removeAll { $0 === sender }
    }

    func netService(_ sender: NetService, didNotResolve errorDict: [String: NSNumber]) {
        resolvingServices.removeAll { $0 === sender }
    }
}
