import Foundation
import CoreFoundation
public enum SpendError: Error { case invalidResponse, wrongKey }
public struct Usage {
    public let daily: Double?, weekly: Double?, monthly: Double?
    public static func parse(_ data: Data) throws -> Usage {
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any], let obj = root["data"] as? [String: Any] else { throw SpendError.invalidResponse }
        guard let management = obj["is_management_key"] as? NSNumber, CFGetTypeID(management) == CFBooleanGetTypeID(), !management.boolValue else { throw SpendError.wrongKey }
        if let p = obj["is_provisioning_key"] {
            guard let flag = p as? NSNumber, CFGetTypeID(flag) == CFBooleanGetTypeID(), !flag.boolValue else { throw SpendError.wrongKey }
        }
        func number(_ key: String) -> Double? {
            guard let n = obj[key] as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID(), n.doubleValue.isFinite, n.doubleValue >= 0 else { return nil }
            return n.doubleValue
        }
        return Usage(daily: number("usage_daily"), weekly: number("usage_weekly"), monthly: number("usage_monthly"))
    }
}
public final class KeyReplacement {
    private let verify: (String, @escaping (Bool) -> Void) -> Void
    private let save: (String) -> Bool
    public init(verify: @escaping (String, @escaping (Bool) -> Void) -> Void, save: @escaping (String) -> Bool) {
        self.verify = verify; self.save = save
    }
    public func submit(_ key: String, completion: @escaping (Bool) -> Void) {
        guard key.hasPrefix("sk-or-v1-"), key.count > "sk-or-v1-".count else { completion(false); return }
        verify(key) { valid in completion(valid && self.save(key)) }
    }
}
// Access on the main queue; a failed submission remains eligible for retry.
public final class AlertState {
    private var pending: Set<String> = []
    public init() {}
    public func begin(day: String, daily: Double?, sent: Set<Int>) -> [Int] {
        let eligible = thresholds(daily: daily, sent: sent).filter { !pending.contains("\(day):\($0)") }
        for threshold in eligible { pending.insert("\(day):\(threshold)") }
        return eligible
    }
    public func complete(day: String, threshold: Int, accepted: Bool) -> Bool {
        guard pending.remove("\(day):\(threshold)") != nil else { return false }
        return accepted
    }
}
public func utcDay(_ date: Date) -> String {
    let f = DateFormatter(); f.calendar = Calendar(identifier: .gregorian); f.locale = Locale(identifier: "en_US_POSIX"); f.timeZone = TimeZone(secondsFromGMT: 0); f.dateFormat = "yyyy-MM-dd"; return f.string(from: date)
}
public func thresholds(daily: Double?, sent: Set<Int>) -> [Int] {
    guard let daily else { return [] }; return [5, 10].filter { daily >= Double($0) && !sent.contains($0) }
}

// Main-queue state for refreshes and the complete key-entry transaction.
public final class RefreshGate {
    public struct Token { fileprivate let revision: Int; fileprivate let day: String }
    private var revision = 0
    private var refreshing = false
    private var enteringKey = false
    public init() {}
    public func beginRefresh(day: String) -> Token? {
        guard !refreshing && !enteringKey else { return nil }
        refreshing = true
        return Token(revision: revision, day: day)
    }
    public func finishRefresh(_ token: Token) { refreshing = false }
    public func isCurrent(_ token: Token, day: String) -> Bool {
        token.revision == revision && token.day == day && !enteringKey
    }
    public func beginKeyEntry() -> Bool {
        guard !refreshing && !enteringKey else { return false }
        enteringKey = true
        return true
    }
    public func endKeyEntry(changed: Bool) {
        if changed { revision += 1 }
        enteringKey = false
    }
}
public enum KeychainReadError: Error { case status(Int32), invalidItem }
public func keychainSelection(status: Int32, value: String?) throws -> String? {
    if status == -25300 { return nil } // errSecItemNotFound
    guard status == 0 else { throw KeychainReadError.status(status) }
    guard let value, !value.isEmpty else { throw KeychainReadError.invalidItem }
    return value
}
