import AppKit
import Foundation
import Security
import ServiceManagement
import UserNotifications

// Keep the bundle identifier and legacy sources so existing settings continue to work.
let keyQuery: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "com.personal.openrouter-spend", kSecAttrAccount as String: "openrouter-api-key"]
func keychainKey() throws -> String? {
    var query = keyQuery; query[kSecReturnData as String] = true; query[kSecMatchLimit as String] = kSecMatchLimitOne
    var result: CFTypeRef?
    let status = SecItemCopyMatching(query as CFDictionary, &result)
    let value = (result as? Data).flatMap { String(data: $0, encoding: .utf8) }
    return try keychainSelection(status: status, value: value)
}
func saveKey(_ key: String) -> Bool {
    let data = Data(key.utf8)
    let status = SecItemUpdate(keyQuery as CFDictionary, [kSecValueData as String: data] as CFDictionary)
    if status == errSecSuccess { return true }
    guard status == errSecItemNotFound else { return false }
    var query = keyQuery; query[kSecValueData as String] = data; query[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
    return SecItemAdd(query as CFDictionary, nil) == errSecSuccess
}
func loadKey() throws -> (key: String?, status: KeyStatus) {
    try selectKey(keychain: keychainKey, environment: {
        guard let s = ProcessInfo.processInfo.environment["OPENROUTER_API_KEY"]?.trimmingCharacters(in: .whitespacesAndNewlines), !s.isEmpty else { return nil }
        return s
    }, hermes: {
        let path = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".hermes/.env")
        let text: String
        do { text = try String(contentsOf: path, encoding: .utf8) }
        catch let error as NSError where error.domain == NSCocoaErrorDomain && error.code == NSFileReadNoSuchFileError { return nil }
        for line in text.components(separatedBy: .newlines) where line.hasPrefix("OPENROUTER_API_KEY=") {
            let s = String(line.dropFirst("OPENROUTER_API_KEY=".count)).trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: CharacterSet(charactersIn: "\"'"))
            if !s.isEmpty { return s }
        }
        return nil
    })
}
final class NoRedirects: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
}
let apiSession = URLSession(configuration: .ephemeral, delegate: NoRedirects(), delegateQueue: nil)
func requestUsage(key: String? = nil, onSelection: ((KeyStatus) -> Void)? = nil, _ completion: @escaping (Result<Usage, Error>) -> Void) {
    let selected: String?
    do {
        if let key { selected = key }
        else { let result = try loadKey(); selected = result.key; onSelection?(result.status) }
    } catch { onSelection?(.error); completion(.failure(error)); return }
    guard let key = selected else { completion(.failure(NSError(domain: "Missing inference key", code: 1))); return }
    var req = URLRequest(url: URL(string: "https://openrouter.ai/api/v1/key")!, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 15)
    req.setValue("Bearer " + key, forHTTPHeaderField: "Authorization")
    apiSession.dataTask(with: req) { data, response, error in
        if let error { completion(.failure(error)); return }
        guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode), let data else { completion(.failure(NSError(domain: "OpenRouter HTTP error", code: (response as? HTTPURLResponse)?.statusCode ?? 0))); return }
        do { completion(.success(try Usage.parse(data))) } catch { completion(.failure(error)) }
    }.resume()
}

final class App: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    let alerts = AlertState()
    let refreshGate = RefreshGate()
    var latest: Usage?; var updated: Date?; var error: String?; var busy = false; var keyBusy = false
    var notificationStatus = "Checking…"; var notificationMessage: String?
    var keyStatus: KeyStatus = .unknown
    var keyRevision = 0
    var timer: Timer?
    func applicationDidFinishLaunching(_ notification: Notification) {
        item.button?.title = "OR $—"
        UNUserNotificationCenter.current().delegate = self
        checkNotifications(); buildMenu(); refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in self?.checkNotifications(); self?.refresh() }
        NSWorkspace.shared.notificationCenter.addObserver(self, selector: #selector(woke), name: NSWorkspace.didWakeNotification, object: nil)
    }
    @objc func woke() { checkNotifications(); refresh() }
    func money(_ n: Double?) -> String { n.map { String(format: "$%.2f", $0) } ?? "Unknown" }
    func line(_ s: String, _ menu: NSMenu) { let i = NSMenuItem(title: s, action: nil, keyEquivalent: ""); i.isEnabled = false; menu.addItem(i) }
    func buildMenu() {
        let menu = NSMenu()
        line("OpenRouter · this key only", menu)
        line("Today (UTC): \(money(latest?.daily))", menu)
        line("Week (UTC Monday): \(money(latest?.weekly))", menu)
        line("Month (UTC): \(money(latest?.monthly))", menu)
        if let updated { line("Last success: \(DateFormatter.localizedString(from: updated, dateStyle: .short, timeStyle: .medium))", menu) } else { line("No successful update yet", menu) }
        if let error { line("Error: \(error) · values may be stale", menu) }
        else if let updated, Date().timeIntervalSince(updated) > 120 { line("Stale: last update over 2 minutes ago", menu) }
        line("Notifications: \(notificationStatus)", menu)
        if let notificationMessage { line(notificationMessage, menu) }
        line("Provider charges may lag; excludes other keys and BYOK.", menu)
        line(keyStatus.menuLine, menu)
        menu.addItem(.separator())
        let refresh = NSMenuItem(title: busy ? "Refreshing…" : "Refresh now", action: #selector(refreshAction), keyEquivalent: "r"); refresh.target = self; refresh.isEnabled = !busy && !keyBusy; menu.addItem(refresh)
        let key = NSMenuItem(title: keyBusy ? "Verifying key…" : keyStatus.actionTitle, action: #selector(setKey), keyEquivalent: ""); key.target = self; key.isEnabled = !keyBusy && !busy; menu.addItem(key)
        let test = NSMenuItem(title: "Test notification", action: #selector(testNotification), keyEquivalent: ""); test.target = self; menu.addItem(test)
        let login = NSMenuItem(title: "Start at Login", action: #selector(toggleLogin), keyEquivalent: ""); login.target = self; login.state = SMAppService.mainApp.status == .enabled ? .on : .off; menu.addItem(login)
        if SMAppService.mainApp.status == .requiresApproval { line("Login item requires approval in System Settings", menu) }
        let quit = NSMenuItem(title: "Quit", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"); menu.addItem(quit)
        item.menu = menu
        item.button?.title = "OR \(money(latest?.daily))" + (error != nil || (updated.map { Date().timeIntervalSince($0) > 120 } ?? false) ? " !" : "")
    }
    @objc func refreshAction() { refresh() }
    func refresh() {
        let requestDay = utcDay(Date())
        guard let token = refreshGate.beginRefresh(day: requestDay) else { return }; busy = true; buildMenu()
        requestUsage(onSelection: { [weak self] status in self?.keyStatus = status; self?.buildMenu() }) { [weak self] result in DispatchQueue.main.async {
            guard let self else { return }; self.busy = false; self.refreshGate.finishRefresh(token)
            guard self.refreshGate.isCurrent(token, day: utcDay(Date())) else { self.buildMenu(); self.refresh(); return }
            switch result {
            case .success(let usage): self.latest = usage; self.updated = Date(); self.error = nil; self.notify(usage.daily, day: requestDay)
            case .failure(let e):
                if let e = e as? SpendError, case .wrongKey = e { self.error = "Not a verified regular key" }
                else if e is KeychainReadError { self.error = "Keychain unavailable or invalid; unlock or check access" }
                else if self.keyStatus == .error { self.error = "Key source unavailable" }
                else { self.error = "Could not refresh" }
            }
            self.buildMenu()
        }}
    }
    @objc func setKey() {
        guard refreshGate.beginKeyEntry() else { return }
        keyBusy = true; buildMenu()
        let dialog = NSAlert(); dialog.messageText = keyStatus.actionTitle.replacingOccurrences(of: "…", with: ""); dialog.informativeText = keyStatus.dialogText
        let field = NSSecureTextField(frame: NSRect(x: 0, y: 0, width: 360, height: 24)); dialog.accessoryView = field
        dialog.addButton(withTitle: "Verify and Save"); dialog.addButton(withTitle: "Cancel")
        NSApp.activate(ignoringOtherApps: true)
        guard dialog.runModal() == .alertFirstButtonReturn else { field.stringValue = ""; refreshGate.endKeyEntry(changed: false); keyBusy = false; buildMenu(); return }
        let candidate = field.stringValue.trimmingCharacters(in: .whitespacesAndNewlines); field.stringValue = ""
        let replacement = KeyReplacement(verify: { key, done in requestUsage(key: key) { result in if case .success = result { done(true) } else { done(false) } } }, save: saveKey)
        replacement.submit(candidate) { [weak self] success in DispatchQueue.main.async {
            guard let self else { return }; self.keyBusy = false; self.refreshGate.endKeyEntry(changed: success)
            if success { self.keyRevision += 1; self.latest = nil; self.updated = nil; self.error = nil; self.refresh() }
            else { self.error = "Key verification or Keychain save failed; previous key retained"; self.buildMenu() }
        }}
    }
    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification, withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound])
    }
    func checkNotifications() {
        UNUserNotificationCenter.current().getNotificationSettings { settings in DispatchQueue.main.async {
            switch settings.authorizationStatus {
            case .authorized, .provisional: self.notificationStatus = settings.alertSetting == .enabled ? "Allowed" : "Allowed, alerts disabled"
            case .denied: self.notificationStatus = "Denied — enable in System Settings"
            case .notDetermined: self.notificationStatus = "Not requested"
            default: self.notificationStatus = "Unavailable"
            }
            self.buildMenu()
        }}
    }
    @objc func testNotification() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { granted, error in
            guard granted, error == nil else { DispatchQueue.main.async { self.notificationMessage = "Test notification not authorized"; self.checkNotifications() }; return }
            let content = UNMutableNotificationContent(); content.title = "AI Spending test"; content.body = "Notifications are working if you can see this."; content.sound = .default
            UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)) { error in DispatchQueue.main.async {
                self.notificationMessage = error == nil ? "Test submitted to macOS" : "Test notification submission failed"
                self.checkNotifications()
            }}
        }
    }
    func notify(_ daily: Double?, day: String) {
        let revision = keyRevision
        UNUserNotificationCenter.current().getNotificationSettings { settings in
            guard (settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional), settings.alertSetting == .enabled else { return }
            DispatchQueue.main.async {
                guard self.keyRevision == revision, utcDay(Date()) == day else { return }
                self.sendAlerts(daily, day: day)
            }
        }
    }
    func sendAlerts(_ daily: Double?, day: String) {
        guard utcDay(Date()) == day else { return }
        let defaults = UserDefaults.standard
        if defaults.string(forKey: "alertDay") != day { defaults.set(day, forKey: "alertDay"); defaults.set([], forKey: "alertsSent") }
        let sent = Set(defaults.array(forKey: "alertsSent") as? [Int] ?? [])
        for threshold in alerts.begin(day: day, daily: daily, sent: sent) {
            let content = UNMutableNotificationContent(); content.title = "OpenRouter daily spending"; content.body = "This key has reached $\(threshold) today (UTC). Charges may lag."; content.sound = .default
            UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: "\(day)-\(threshold)", content: content, trigger: nil)) { error in DispatchQueue.main.async {
                let accepted = self.alerts.complete(day: day, threshold: threshold, accepted: error == nil)
                if accepted && defaults.string(forKey: "alertDay") == day && utcDay(Date()) == day {
                    var sent = Set(defaults.array(forKey: "alertsSent") as? [Int] ?? []); sent.insert(threshold); defaults.set(Array(sent), forKey: "alertsSent")
                } else if error != nil { self.notificationMessage = "Alert submission failed; retry on refresh"; self.buildMenu() }
            }}
        }
    }
    @objc func toggleLogin() {
        do { if SMAppService.mainApp.status == .enabled { try SMAppService.mainApp.unregister() } else { try SMAppService.mainApp.register() } }
        catch { self.error = "Login setting could not be changed" }
        buildMenu()
    }
}

if CommandLine.arguments.contains("--check") {
    let sem = DispatchSemaphore(value: 0)
    var succeeded = false
    requestUsage { result in
        switch result { case .success(let u): succeeded = true; print("LIVE: regular key verified; daily=\(u.daily == nil ? "unknown" : "valid"), weekly=\(u.weekly == nil ? "unknown" : "valid"), monthly=\(u.monthly == nil ? "unknown" : "valid")"); case .failure: print("LIVE: refresh failed") }
        sem.signal()
    }
    if sem.wait(timeout: .now() + 20) == .timedOut { print("LIVE: timeout"); exit(1) }
    exit(succeeded ? 0 : 1)
}
let app = NSApplication.shared
let delegate = App(); app.delegate = delegate; app.setActivationPolicy(.accessory); app.run()
