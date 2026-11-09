#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
app="build/AI-Spending.app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
cp Info.plist "$app/Contents/Info.plist"
cp assets/logo/AI-Spending.icns "$app/Contents/Resources/AI-Spending.icns"
swiftc -O -target "$(uname -m)-apple-macos13.0" Sources/SpendCore/Usage.swift Sources/OpenRouterSpend/main.swift -o "$app/Contents/MacOS/OpenRouterSpend"
codesign --force --sign - "$app"
codesign --verify --deep --strict "$app"
printf 'Built %s\n' "$app"
