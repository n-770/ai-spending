import AppKit
import Foundation
import ServiceManagement
import UserNotifications

func loadKey() -> String? {
    if let s = ProcessInfo.processInfo.environment["OPENROUTER_API_KEY"]?.trimmingCharacters(in: .whitespacesAndNewlines), !s.isEmpty { return s }
    let path = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".hermes/.env")
    guard let text = try? String(contentsOf: path, encoding: .utf8) else { return nil }
    for line in text.components(separatedBy: .newlines) where line.hasPrefix("OPENROUTER_API_KEY=") {
        let s = String(line.dropFirst("OPENROUTER_API_KEY=".count)).trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: CharacterSet(charactersIn: "\"'"))
        if !s.isEmpty { return s }
    }
    return nil
}
func requestUsage(_ completion: @escaping (Result<Usage, Error>) -> Void) {
    guard let key = loadKey() else { completion(.failure(NSError(domain: "Missing inference key", code: 1))); return }
    var req = URLRequest(url: URL(string: "https://openrouter.ai/api/v1/key")!, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 15)
    req.setValue("Bearer " + key, forHTTPHeaderField: "Authorization")
    URLSession.shared.dataTask(with: req) { data, response, error in
        if let error { completion(.failure(error)); return }
        guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode), let data else { completion(.failure(NSError(domain: "OpenRouter HTTP error", code: (response as? HTTPURLResponse)?.statusCode ?? 0))); return }
        do { completion(.success(try Usage.parse(data))) } catch { completion(.failure(error)) }
    }.resume()
}

final class App: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    var latest: Usage?; var updated: Date?; var error: String?; var busy = false
    var timer: Timer?
    func applicationDidFinishLaunching(_ notification: Notification) {
        item.button?.title = "OR $—"
        UNUserNotificationCenter.current().delegate = self
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
        buildMenu(); refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in self?.refresh() }
        NSWorkspace.shared.notificationCenter.addObserver(self, selector: #selector(woke), name: NSWorkspace.didWakeNotification, object: nil)
    }
    @objc func woke() { refresh() }
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
        line("Provider charges may lag; excludes other keys and BYOK.", menu)
        menu.addItem(.separator())
        let refresh = NSMenuItem(title: busy ? "Refreshing…" : "Refresh now", action: #selector(refreshAction), keyEquivalent: "r"); refresh.target = self; refresh.isEnabled = !busy; menu.addItem(refresh)
        let login = NSMenuItem(title: "Start at Login", action: #selector(toggleLogin), keyEquivalent: ""); login.target = self; login.state = SMAppService.mainApp.status == .enabled ? .on : .off; menu.addItem(login)
        let quit = NSMenuItem(title: "Quit", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"); menu.addItem(quit)
        item.menu = menu
        item.button?.title = "OR \(money(latest?.daily))" + (error != nil || (updated.map { Date().timeIntervalSince($0) > 120 } ?? false) ? " !" : "")
    }
    @objc func refreshAction() { refresh() }
    func refresh() {
        guard !busy else { return }; busy = true; buildMenu()
        requestUsage { [weak self] result in DispatchQueue.main.async {
            guard let self else { return }; self.busy = false
            switch result {
            case .success(let usage): self.latest = usage; self.updated = Date(); self.error = nil; self.notify(usage.daily)
            case .failure(let e):
                if let e = e as? SpendError, case .wrongKey = e { self.error = "Not a verified regular key" }
                else { self.error = "Could not refresh" }
            }
            self.buildMenu()
        }}
    }
    func notify(_ daily: Double?) {
        UNUserNotificationCenter.current().getNotificationSettings { settings in
            guard settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional else { return }
            DispatchQueue.main.async { self.sendAlerts(daily) }
        }
    }
    func sendAlerts(_ daily: Double?) {
        let day = utcDay(Date()); let defaults = UserDefaults.standard
        if defaults.string(forKey: "alertDay") != day { defaults.set(day, forKey: "alertDay"); defaults.set([], forKey: "alertsSent") }
        var sent = Set(defaults.array(forKey: "alertsSent") as? [Int] ?? [])
        for threshold in thresholds(daily: daily, sent: sent) {
            sent.insert(threshold); defaults.set(Array(sent), forKey: "alertsSent")
            let content = UNMutableNotificationContent(); content.title = "OpenRouter daily spending"; content.body = "This key has reached $\(threshold) today (UTC). Charges may lag."; content.sound = .default
            UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: "\(day)-\(threshold)", content: content, trigger: nil))
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
