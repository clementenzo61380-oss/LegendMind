#!/usr/bin/env bash
# Installe PROSPECTOR comme service macOS (launchd).
# L'app démarre automatiquement à l'ouverture de ta session et redémarre si elle plante.
#
# Usage :  bash scripts/install_launchd.sh
set -euo pipefail

LABEL="com.prospector.app"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/prospector"

# ─── Vérifications préalables ────────────────────────────────────────────────
if [[ "$(uname)" != "Darwin" ]]; then
  echo "❌ Ce script est réservé à macOS (launchd)." >&2
  exit 1
fi

if [[ ! -x "$PYTHON" ]]; then
  echo "❌ Environnement virtuel introuvable : $PYTHON" >&2
  echo "   Lance d'abord :  python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt" >&2
  exit 1
fi

if [[ ! -f "$PROJECT_DIR/.env" ]]; then
  echo "⚠️  Pas de fichier .env — copie .env.example et remplis ta clé Anthropic :"
  echo "   cp .env.example .env"
  exit 1
fi

mkdir -p "$LOG_DIR" "$HOME/Library/LaunchAgents"

# ─── Génération du plist ─────────────────────────────────────────────────────
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>

    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>$PROJECT_DIR/app.py</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>

    <key>EnvironmentVariables</key>
    <dict>
        <!-- Pas de rechargement à chaud en mode service -->
        <key>RELOAD</key>
        <string>false</string>
    </dict>

    <!-- Démarre à l'ouverture de session et redémarre en cas de plantage -->
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>$LOG_DIR/prospector.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/prospector.err.log</string>
</dict>
</plist>
EOF

# ─── (Re)chargement du service ───────────────────────────────────────────────
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo ""
echo "✅ PROSPECTOR installé comme service launchd."
echo ""
echo "   Interface  : http://127.0.0.1:8000"
echo "   Logs       : $LOG_DIR/prospector.log"
echo "   Plist      : $PLIST"
echo ""
echo "   Commandes utiles :"
echo "   - Statut       : launchctl list | grep prospector"
echo "   - Redémarrer   : launchctl kickstart -k gui/$(id -u)/$LABEL"
echo "   - Désinstaller : bash scripts/uninstall_launchd.sh"
