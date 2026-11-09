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
public func utcDay(_ date: Date) -> String {
    let f = DateFormatter(); f.calendar = Calendar(identifier: .gregorian); f.locale = Locale(identifier: "en_US_POSIX"); f.timeZone = TimeZone(secondsFromGMT: 0); f.dateFormat = "yyyy-MM-dd"; return f.string(from: date)
}
public func thresholds(daily: Double?, sent: Set<Int>) -> [Int] {
    guard let daily else { return [] }; return [5, 10].filter { daily >= Double($0) && !sent.contains($0) }
}
