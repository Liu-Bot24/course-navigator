import Darwin
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
        var components = URLComponents()
        components.scheme = "http"
        components.host = urlComponentsHost
        components.port = port
        return components.url?.absoluteString ?? "http://\(hostName):\(port)"
    }

    static func serviceID(name: String, type: String, domain: String) -> String {
        "\(name)|\(type)|\(domain)"
    }

    private var urlComponentsHost: String {
        hostName.contains(":") && !hostName.hasPrefix("[") ? "[\(hostName)]" : hostName
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
        guard let hostName = Self.preferredHostName(
            hostName: service.hostName,
            addressHosts: service.addresses?.compactMap(Self.hostName(fromAddressData:)) ?? []
        ) else { return }
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

    static func preferredHostName(hostName: String?, addressHosts: [String]) -> String? {
        let usableAddressHosts = addressHosts
            .compactMap(normalizedHostName)
            .filter(isUsableDeviceHost)

        if let ipv4Host = usableAddressHosts.first(where: isIPv4Host) {
            return ipv4Host
        }
        if let addressHost = usableAddressHosts.first {
            return addressHost
        }
        guard
            let fallbackHost = normalizedHostName(hostName ?? ""),
            isUsableDeviceHost(fallbackHost)
        else {
            return nil
        }
        return fallbackHost
    }

    static func normalizedHostName(_ rawHost: String) -> String? {
        var host = rawHost.trimmingCharacters(in: .whitespacesAndNewlines)
        if host.hasSuffix(".") {
            host.removeLast()
        }
        if host.hasPrefix("[") && host.hasSuffix("]") {
            host.removeFirst()
            host.removeLast()
        }
        return host.isEmpty ? nil : host
    }

    static func isUsableDeviceHost(_ host: String) -> Bool {
        let lowercasedHost = host.lowercased()
        if lowercasedHost == "localhost"
            || lowercasedHost == "::1"
            || lowercasedHost == "0:0:0:0:0:0:0:1"
            || lowercasedHost == "0.0.0.0"
            || lowercasedHost == "::"
            || lowercasedHost == "0:0:0:0:0:0:0:0"
        {
            return false
        }
        if lowercasedHost.hasPrefix("127.")
            || lowercasedHost.hasPrefix("169.254.")
            || lowercasedHost.hasPrefix("fe80:")
        {
            return false
        }
        return true
    }

    static func isIPv4Host(_ host: String) -> Bool {
        let parts = host.split(separator: ".", omittingEmptySubsequences: false)
        guard parts.count == 4 else { return false }
        return parts.allSatisfy { part in
            guard let value = Int(part), value >= 0, value <= 255 else { return false }
            return String(value) == String(part)
        }
    }

    private static func hostName(fromAddressData data: Data) -> String? {
        data.withUnsafeBytes { rawBuffer -> String? in
            guard let baseAddress = rawBuffer.baseAddress else { return nil }
            let family = baseAddress.assumingMemoryBound(to: sockaddr.self).pointee.sa_family
            switch Int32(family) {
            case AF_INET:
                var address = baseAddress.assumingMemoryBound(to: sockaddr_in.self).pointee.sin_addr
                var buffer = [CChar](repeating: 0, count: Int(INET_ADDRSTRLEN))
                guard inet_ntop(AF_INET, &address, &buffer, socklen_t(INET_ADDRSTRLEN)) != nil else {
                    return nil
                }
                return string(fromNullTerminatedBuffer: buffer)
            case AF_INET6:
                var address = baseAddress.assumingMemoryBound(to: sockaddr_in6.self).pointee.sin6_addr
                var buffer = [CChar](repeating: 0, count: Int(INET6_ADDRSTRLEN))
                guard inet_ntop(AF_INET6, &address, &buffer, socklen_t(INET6_ADDRSTRLEN)) != nil else {
                    return nil
                }
                return string(fromNullTerminatedBuffer: buffer)
            default:
                return nil
            }
        }
    }

    private static func string(fromNullTerminatedBuffer buffer: [CChar]) -> String {
        let bytes = buffer.prefix { $0 != 0 }.map { UInt8(bitPattern: $0) }
        return String(decoding: bytes, as: UTF8.self)
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
