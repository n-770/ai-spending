import Foundation
func parse(_ s: String) throws -> Usage { try Usage.parse(Data(s.utf8)) }
let empty = try parse("{\"data\":{\"is_management_key\":false}}")
precondition(empty.daily == nil && empty.weekly == nil && empty.monthly == nil)
let valid = try parse("{\"data\":{\"is_management_key\":false,\"usage_daily\":5.2,\"usage_weekly\":9,\"usage_monthly\":12}}")
precondition(valid.daily == 5.2 && valid.weekly == 9 && valid.monthly == 12)
let bad = try parse("{\"data\":{\"is_management_key\":false,\"usage_daily\":true,\"usage_weekly\":-1,\"usage_monthly\":\"2\"}}")
precondition(bad.daily == nil && bad.weekly == nil && bad.monthly == nil)
for json in ["{\"data\":{}}", "{\"data\":{\"is_management_key\":0}}", "{\"data\":{\"is_management_key\":true}}", "{\"data\":{\"is_management_key\":false,\"is_provisioning_key\":true}}"] { do { _ = try parse(json); fatalError("unverified key accepted") } catch {} }
precondition(thresholds(daily: 10, sent: [5]) == [10])
precondition(thresholds(daily: nil, sent: []).isEmpty)
precondition(utcDay(Date(timeIntervalSince1970: 0)) == "1970-01-01")
let state = AlertState()
precondition(state.begin(day: "2026-01-01", daily: 5, sent: []) == [5])
precondition(state.begin(day: "2026-01-01", daily: 5, sent: []).isEmpty)
precondition(state.complete(day: "2026-01-01", threshold: 5, accepted: false) == false)
precondition(state.begin(day: "2026-01-01", daily: 5, sent: []) == [5])
precondition(state.complete(day: "2026-01-01", threshold: 5, accepted: true))
precondition(!state.complete(day: "2026-01-01", threshold: 5, accepted: true))
precondition(state.begin(day: "2026-01-01", daily: 5, sent: [5]).isEmpty)
precondition(state.begin(day: "2026-01-02", daily: 10, sent: []) == [5, 10])
precondition(state.begin(day: "2026-01-02", daily: 10, sent: []).isEmpty)
precondition(state.complete(day: "2026-01-02", threshold: 10, accepted: true))
precondition(!state.complete(day: "2026-01-02", threshold: 5, accepted: false))
precondition(state.begin(day: "2026-01-02", daily: 10, sent: [10]) == [5])
precondition(utcDay(Date(timeIntervalSince1970: 86399)) == "1970-01-01")
precondition(utcDay(Date(timeIntervalSince1970: 86400)) == "1970-01-02")
var savedKey = "previous"
var verifyCallback: ((Bool) -> Void)?
let replacement = KeyReplacement(verify: { _, done in verifyCallback = done }, save: { savedKey = $0; return true })
replacement.submit("sk-or-v1-test") { _ in }
precondition(savedKey == "previous")
verifyCallback?(false)
precondition(savedKey == "previous")
replacement.submit("sk-or-v1-test") { _ in }
verifyCallback?(true)
precondition(savedKey == "sk-or-v1-test")
var rejectedManagement = false
replacement.submit("sk-or-admin-test") { rejectedManagement = !$0 }
precondition(rejectedManagement && savedKey == "sk-or-v1-test")


// A modal key entry blocks timer refreshes, and invalidates older results.
let gate = RefreshGate()
let old = gate.beginRefresh(day: "2026-01-01")!
precondition(gate.beginKeyEntry() == false)
gate.finishRefresh(old)
precondition(gate.beginKeyEntry())
precondition(gate.beginRefresh(day: "2026-01-01") == nil)
gate.endKeyEntry(changed: true)
precondition(!gate.isCurrent(old, day: "2026-01-01"))
let crossing = gate.beginRefresh(day: "2026-01-01")!
precondition(!gate.isCurrent(crossing, day: "2026-01-02"))
gate.finishRefresh(crossing)
precondition(gate.beginRefresh(day: "2026-01-02") != nil)

// Only missing Keychain entries allow fallback; other failures remain errors.
let missingSelection = try keychainSelection(status: -25300, value: nil)
precondition(missingSelection == nil)
do { _ = try keychainSelection(status: -25308, value: nil); fatalError("locked Keychain fell back") } catch {}
do { _ = try keychainSelection(status: 0, value: nil); fatalError("invalid Keychain item fell back") } catch {}
let presentSelection = try keychainSelection(status: 0, value: "test")
precondition(presentSelection == "test")

print("PASS: parsing, key identity, threshold retry, refresh races, UTC day, Keychain errors, and key replacement")
