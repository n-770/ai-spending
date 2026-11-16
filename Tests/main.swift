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

// Source selection respects precedence and never falls back after a Keychain error.
let selectedKeychain = try selectKey(keychain: { "keychain" }, environment: { "environment" }, hermes: { "hermes" })
precondition(selectedKeychain.status == .keychain && selectedKeychain.key == "keychain")
let selectedEnvironment = try selectKey(keychain: { nil }, environment: { "environment" }, hermes: { "hermes" })
precondition(selectedEnvironment.status == .environment && selectedEnvironment.key == "environment")
let selectedHermes = try selectKey(keychain: { nil }, environment: { nil }, hermes: { "hermes" })
precondition(selectedHermes.status == .hermes && selectedHermes.key == "hermes")
let selectedMissing = try selectKey(keychain: { nil }, environment: { nil }, hermes: { nil })
precondition(selectedMissing.status == .missing && selectedMissing.key == nil)
var fallbackCalled = false
do { _ = try selectKey(keychain: { throw KeychainReadError.invalidItem }, environment: { fallbackCalled = true; return "fallback" }, hermes: { nil }); fatalError("unexpected fallback") } catch {}
precondition(!fallbackCalled)
do { _ = try selectKey(keychain: { nil }, environment: { nil }, hermes: { throw KeychainReadError.invalidItem }); fatalError("unreadable fallback treated as missing") } catch {}

// Menu reports the credential source without displaying the credential itself.
precondition(KeyStatus.unknown.menuLine == "API key: Checking…")
precondition(KeyStatus.missing.menuLine == "API key: Not configured")
precondition(KeyStatus.error.menuLine == "API key: Status unavailable")
precondition(KeyStatus.keychain.menuLine == "API key: Configured (Keychain)")
precondition(KeyStatus.environment.menuLine == "API key: Configured (environment)")
precondition(KeyStatus.hermes.menuLine == "API key: Configured (Hermes)")
precondition(KeyStatus.missing.actionTitle == "Set OpenRouter API Key…")
precondition(KeyStatus.keychain.actionTitle == "Change OpenRouter API Key…")
precondition(KeyStatus.environment.actionTitle == "Change OpenRouter API Key…")
precondition(KeyStatus.error.actionTitle == "Set or Change OpenRouter API Key…")
precondition(KeyStatus.unknown.actionTitle == "Set or Change OpenRouter API Key…")
precondition(KeyStatus.keychain.dialogText.contains("replaces"))
precondition(KeyStatus.environment.dialogText.contains("not changed"))
precondition(KeyStatus.error.dialogText.contains("retained"))

// Forecast line is read-only and permissive: a bad or absent file must not break the menu.
func moneyText(_ n: Double?) -> String { n.map { String(format: "$%.2f", $0) } ?? "Unknown" }
let modelForecast = try SpendForecast.parse(Data("""
{"projected_total":102.83,"low":81.7,"high":122.83,"horizon_days":14,"period_end":"2026-11-30","method":"timesfm3-mean","stale_days":0}
""".utf8))
precondition(modelForecast.horizonDays == 14 && modelForecast.fromModel)
precondition(modelForecast.projected == 102.83 && modelForecast.low == 81.7 && modelForecast.high == 122.83)
let modelLine = modelForecast.menuLine(money: moneyText)
precondition(modelLine.hasPrefix("Projected "), modelLine)
precondition(modelLine.contains("$102.83") && modelLine.contains("range"), modelLine)
precondition(modelLine.contains("$81.70") && modelLine.contains("$122.83"), modelLine)
let paceForecast = try SpendForecast.parse(Data("""
{"projected_total":38.4,"low":null,"high":null,"horizon_days":14,"period_end":"2026-11-30","method":"pace-naive-28d","stale_days":0}
""".utf8))
precondition(!paceForecast.fromModel)
precondition(paceForecast.menuLine(money: moneyText).hasSuffix("(pace)"))
let staleForecast = try SpendForecast.parse(Data("""
{"projected_total":10,"low":9,"high":12,"horizon_days":5,"period_end":"2026-11-30","method":"timesfm3-mean","stale_days":3}
""".utf8))
precondition(staleForecast.menuLine(money: moneyText).contains("3d old"))
let earlyForecast = try SpendForecast.parse(Data("""
{"projected_total":4.2,"low":null,"high":null,"horizon_days":9,"period_end":"2026-11-30","method":"pace-naive-28d","stale_days":0,"preliminary":true}
""".utf8))
precondition(earlyForecast.preliminary)
precondition(earlyForecast.menuLine(money: moneyText).hasSuffix("· preliminary"))
// Inconsistent bounds fall back to the pace wording instead of printing a nonsense range.
let badBounds = try SpendForecast.parse(Data("""
{"projected_total":10,"low":20,"high":12,"horizon_days":5,"period_end":"2026-11-30","method":"timesfm3-mean","stale_days":0}
""".utf8))
precondition(badBounds.menuLine(money: moneyText).hasSuffix("(pace)"))
for json in ["{}", "{\"horizon_days\":3,\"period_end\":\"2026-11-30\"}",
             "{\"projected_total\":\"9\",\"horizon_days\":3,\"period_end\":\"2026-11-30\"}",
             "{\"projected_total\":9,\"horizon_days\":3,\"period_end\":\"2026-11\"}"] {
    do { _ = try SpendForecast.parse(Data(json.utf8)); fatalError("invalid forecast accepted: \(json)") } catch {}
}
precondition(SpendForecast.dayLabel("not-a-day") == nil)

print("PASS: parsing, key identity, threshold retry, refresh races, UTC day, Keychain errors, key replacement, key status, and forecast line")
