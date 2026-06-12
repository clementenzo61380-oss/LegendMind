#!/usr/bin/env bash
# Désinstalle le service launchd PROSPECTOR (l'app et les données restent intactes).
#
# Usage :  bash scripts/uninstall_launchd.sh
set -euo pipefail

LABEL="com.prospector.app"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [[ ! -f "$PLIST" ]]; then
  echo "ℹ️  Service non installé ($PLIST absent) — rien à faire."
  exit 0
fi

launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
rm -f "$PLIST"

echo "✅ Service PROSPECTOR désinstallé."
echo "   L'app reste utilisable manuellement avec :  python app.py"
