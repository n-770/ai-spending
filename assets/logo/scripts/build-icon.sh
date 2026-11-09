#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../../.."
swift assets/logo/scripts/render-icon.swift assets/logo/concepts/gauge-01.svg assets/logo/AI-Spending.iconset
iconutil -c icns assets/logo/AI-Spending.iconset -o assets/logo/AI-Spending.icns
