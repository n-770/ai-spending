# OpenRouter Spend

A personal macOS menu-bar app (macOS 13+, built for this Mac's architecture). It reads the regular inference key from `OPENROUTER_API_KEY`, or from `~/.hermes/.env` if not set. It sends the key only as a bearer token to OpenRouter's read-only `GET https://openrouter.ai/api/v1/key`. It does not store or display the key, use a management key, change spending limits, or modify existing cron jobs.

The numbers are **this key's OpenRouter credit usage**, not account-wide spending; external BYOK usage is separate and not added. Today, week (Monday start), and month are UTC. Values may lag provider accounting. Invalid or absent fields show Unknown. The menu gives the last successful update; refresh failures retain old values and flag them as potentially stale. Polling is every minute while the app and Mac are awake, plus on wake and manually. It does not run during sleep.

Notifications are requested on first launch; allow them in macOS settings. The app sends at most one notification per $5 and $10 threshold per UTC day (even after restart). They monitor only, not cap or stop usage. If notifications are disabled, no alerts are recorded as sent. Start at Login is optional and off unless explicitly enabled in the menu; macOS may require login-item approval. Ad-hoc signed only: no developer signature or notarization. macOS may warn if the app is moved or downloaded; use Privacy & Security to approve only if you trust it.

## Run, build, test

Open `build/OpenRouter Spend.app`. To rebuild, run `./build.sh` with Apple Command Line Tools. To test without XCTest (which requires full Xcode on this machine):

```
swiftc Sources/SpendCore/Usage.swift Tests/main.swift -o /tmp/openrouter-spend-tests && /tmp/openrouter-spend-tests
```

For a live read-only connectivity and field-validation check that prints no key or amounts:

```
'build/OpenRouter Spend.app/Contents/MacOS/OpenRouterSpend' --check
```

The live check requires a valid regular key and network. Do not share your key or `.env` file. Notifications and login depend on macOS permissions. The app is a personal build, not a notarized distributable.

Reference: https://openrouter.ai/docs/api_reference/limits
# ai-spending
