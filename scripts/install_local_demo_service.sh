#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${FLOWER_RUNTIME_DIR:-$HOME/flower-server}"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python)}"
CLOUDFLARED_BIN="${CLOUDFLARED_BIN:-$(command -v cloudflared)}"
CODEX_BIN="${CODEX_BIN:-$(command -v codex || true)}"
if [[ -z "$CODEX_BIN" && -x /Applications/Codex.app/Contents/Resources/codex ]]; then
  CODEX_BIN="/Applications/Codex.app/Contents/Resources/codex"
fi
USER_ID="$(id -u)"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

if [[ -z "$PYTHON_BIN" ]]; then
  echo "python not found" >&2
  exit 1
fi

if [[ -z "$CLOUDFLARED_BIN" ]]; then
  echo "cloudflared not found" >&2
  exit 1
fi

if [[ -z "$CODEX_BIN" ]]; then
  echo "codex not found" >&2
  exit 1
fi

mkdir -p "$RUNTIME_DIR" "$LAUNCH_AGENTS_DIR"
rsync -a \
  --delete \
  --exclude '.git' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude 'logs' \
  "$SOURCE_DIR/" "$RUNTIME_DIR/"

mkdir -p "$RUNTIME_DIR/logs" "$RUNTIME_DIR/scripts" "$RUNTIME_DIR/ops/launchd"

cat > "$RUNTIME_DIR/scripts/run_api.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "$RUNTIME_DIR"
exec "$PYTHON_BIN" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
EOF

cat > "$RUNTIME_DIR/scripts/run_tunnel.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "$RUNTIME_DIR"
exec "$CLOUDFLARED_BIN" tunnel --url http://127.0.0.1:8000
EOF

cat > "$RUNTIME_DIR/scripts/demo_status.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
echo "API health:"
curl --noproxy '*' -sS -m 5 http://127.0.0.1:8000/api/health || true
echo
echo
echo "Current tunnel URL:"
grep -hEo 'https://[a-zA-Z0-9.-]+\\.trycloudflare\\.com' "$RUNTIME_DIR"/logs/cloudflared.*.log 2>/dev/null | tail -n 1 || true
echo
EOF

chmod +x "$RUNTIME_DIR/scripts/run_api.sh" "$RUNTIME_DIR/scripts/run_tunnel.sh" "$RUNTIME_DIR/scripts/demo_status.sh"

cat > "$RUNTIME_DIR/ops/launchd/com.flower.demo-api.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.flower.demo-api</string>
  <key>ProgramArguments</key>
  <array>
    <string>$RUNTIME_DIR/scripts/run_api.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$RUNTIME_DIR</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$RUNTIME_DIR/logs/api.out.log</string>
  <key>StandardErrorPath</key>
  <string>$RUNTIME_DIR/logs/api.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>CODEX_MODEL</key>
    <string>gpt-5.5</string>
    <key>CODEX_TIMEOUT_SECONDS</key>
    <string>600</string>
    <key>FLOWER_MAX_RENDERED_PAGES</key>
    <string>8</string>
    <key>CODEX_BIN</key>
    <string>$CODEX_BIN</string>
  </dict>
</dict>
</plist>
EOF

cat > "$RUNTIME_DIR/ops/launchd/com.flower.demo-tunnel.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.flower.demo-tunnel</string>
  <key>ProgramArguments</key>
  <array>
    <string>$RUNTIME_DIR/scripts/run_tunnel.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$RUNTIME_DIR</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$RUNTIME_DIR/logs/cloudflared.out.log</string>
  <key>StandardErrorPath</key>
  <string>$RUNTIME_DIR/logs/cloudflared.err.log</string>
</dict>
</plist>
EOF

cp "$RUNTIME_DIR/ops/launchd/com.flower.demo-api.plist" "$LAUNCH_AGENTS_DIR/com.flower.demo-api.plist"
cp "$RUNTIME_DIR/ops/launchd/com.flower.demo-tunnel.plist" "$LAUNCH_AGENTS_DIR/com.flower.demo-tunnel.plist"

launchctl bootout "gui/$USER_ID" "$LAUNCH_AGENTS_DIR/com.flower.demo-api.plist" 2>/dev/null || true
launchctl bootout "gui/$USER_ID" "$LAUNCH_AGENTS_DIR/com.flower.demo-tunnel.plist" 2>/dev/null || true
launchctl bootstrap "gui/$USER_ID" "$LAUNCH_AGENTS_DIR/com.flower.demo-api.plist"
launchctl bootstrap "gui/$USER_ID" "$LAUNCH_AGENTS_DIR/com.flower.demo-tunnel.plist"

echo "Installed launchd services from $RUNTIME_DIR"
"$RUNTIME_DIR/scripts/demo_status.sh"
