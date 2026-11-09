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
print("PASS: unknown/valid/invalid fields, key identity, threshold dedupe, UTC day")
