# AI Spending

A personal macOS menu-bar monitor (macOS 13+, built for the current Mac architecture) for one OpenRouter **regular inference key**. Hermes is optional.

## Setup

1. Build with `./build.sh`, then open `build/AI Spending.app`.
2. Choose **Set OpenRouter API Key…** in the menu, enter a regular inference key, and choose **Verify and Save**. The key is tested against OpenRouter before replacing any previously saved key. Management/provisioning keys are rejected. Network, validation, or Keychain errors leave the previous key in place.
3. Choose **Test notification** and allow macOS notifications when prompted. Check the menu's permission status and System Settings if needed. “Test submitted” means macOS accepted the request, not that it was displayed; Focus and other system settings can suppress display.
4. Optionally enable **Start at Login** in the menu and approve it in System Settings if required.

Key source precedence is the app's Keychain entry, `OPENROUTER_API_KEY` environment variable, then `~/.hermes/.env` for existing users. The latter two are fallbacks; nothing is imported automatically into Keychain. To remove a saved key, delete the generic password with service `com.personal.openrouter-spend` and account `openrouter-api-key` in Keychain Access. A fallback key may then become active. Never share keys or `.env` files.

## Usage and privacy

Today, week (Monday start), and month are UTC. Figures are this key's OpenRouter credit usage, **not account-wide spending**; external BYOK usage and other keys are excluded. Provider accounting may lag. Missing or invalid values show Unknown. Refresh runs every minute while awake, on wake, and manually. Errors retain the last values and mark them potentially stale. The monitor cannot cap or stop spending.

Alerts are attempted at $5 and $10 once per UTC day, and recorded only after macOS accepts the notification request. A failed submission can retry on refresh; acceptance does not guarantee display. Alerts are not submitted when permission or alert presentation is disabled. A crash after macOS accepts a notification but before local persistence can cause a duplicate. Alert state is shared across keys: changing keys does not reset thresholds already recorded that UTC day.

The selected key is sent as a bearer token to OpenRouter's `GET https://openrouter.ai/api/v1/key` to validate and refresh usage; OpenRouter receives that credential and request. The app does not log or display the key. A manually entered key is stored in the local macOS Keychain; legacy environment/Hermes sources remain where you configured them. Threshold state is stored in local UserDefaults; no analytics are included. macOS controls notification display and login registration.

## Migration

The app bundle is now `AI Spending.app`; the bundle identifier remains `com.personal.openrouter-spend` to retain existing preferences and notification identity where macOS permits. The executable name is unchanged. The build does **not** delete the old `OpenRouter Spend.app`, modify any existing monitor or cron job, or alter login settings. Do not run both app copies simultaneously: they share preferences and may produce duplicate alerts. If you previously enabled login for the old bundle path, review and update the login item manually. Ad-hoc signatures, moved paths, and macOS permissions may affect migration; verify notifications and login on your Mac.

## Build and test

Requires Apple Command Line Tools. The build is ad-hoc signed, not notarized; macOS may warn on a moved or downloaded build. Approve it only if you trust it.

```sh
./build.sh
swiftc Sources/SpendCore/Usage.swift Tests/main.swift -o "${TMPDIR:-/tmp}/ai-spending-core-tests"
"${TMPDIR:-/tmp}/ai-spending-core-tests"
codesign --verify --deep --strict --verbose=2 'build/AI Spending.app'
```

For an optional live read-only connectivity and field-validation check that prints neither key nor amounts:

```sh
'build/AI Spending.app/Contents/MacOS/OpenRouterSpend' --check
```

The check reads the configured runtime key and requires network access. GUI notification delivery, wake behavior, and login registration require manual verification in the target macOS session.

## Contributing

Use a branch, keep changes focused, and run the core tests and build above. Describe manual verification and any untested macOS permission/login behavior in your pull request. Never include credentials, real usage data, Keychain exports, or `.env` files in issues, logs, tests, or commits. Report security issues privately to the maintainer rather than publishing credentials or exploit details.

Reference: https://openrouter.ai/docs/api_reference/limits
