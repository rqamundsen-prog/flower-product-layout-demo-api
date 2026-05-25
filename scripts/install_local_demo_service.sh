#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${FLOWER_RUNTIME_DIR:-$HOME/flower-server}"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python)}"
CLOUDFLARED_BIN="${CLOUDFLARED_BIN:-$(command -v cloudflared)}"
NPX_BIN="${NPX_BIN:-$(command -v npx || true)}"
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

if [[ -z "$NPX_BIN" ]]; then
  echo "npx not found" >&2
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

cat > "$RUNTIME_DIR/scripts/run_gateway_sync.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail

cd "$RUNTIME_DIR"
STATE_FILE="$RUNTIME_DIR/logs/current_gateway_origin.txt"
CONFIG_PATH="$RUNTIME_DIR/cloudflare/wrangler.toml"

current_tunnel_url() {
  grep -hEo 'https://[a-zA-Z0-9.-]+\\.trycloudflare\\.com' "$RUNTIME_DIR"/logs/cloudflared.*.log 2>/dev/null | tail -n 1
}

while true; do
  origin_url="\$(current_tunnel_url || true)"
  previous_url=""
  if [[ -f "\$STATE_FILE" ]]; then
    previous_url="\$(cat "\$STATE_FILE")"
  fi

  if [[ -n "\$origin_url" && "\$origin_url" != "\$previous_url" ]]; then
    if curl --noproxy '*' -fsS -m 20 "\$origin_url/api/health" >/dev/null; then
      "$NPX_BIN" wrangler kv key put origin "\$origin_url" --config "\$CONFIG_PATH" --binding FLOWER_DEMO_CONFIG --remote
      printf '%s' "\$origin_url" > "\$STATE_FILE"
      echo "Updated fixed gateway origin to \$origin_url"
    else
      echo "Tunnel URL found but not healthy: \$origin_url" >&2
    fi
  fi

  sleep 60
done
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
echo
echo "Fixed gateway URL:"
echo "https://flower-product-layout-demo-api.rqamundsen-prog.workers.dev"
echo
echo "Fixed gateway health:"
curl -sS -m 20 https://flower-product-layout-demo-api.rqamundsen-prog.workers.dev/api/health || true
EOF

chmod +x "$RUNTIME_DIR/scripts/run_api.sh" "$RUNTIME_DIR/scripts/run_tunnel.sh" "$RUNTIME_DIR/scripts/run_gateway_sync.sh" "$RUNTIME_DIR/scripts/demo_status.sh"

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

cat > "$RUNTIME_DIR/ops/launchd/com.flower.demo-gateway-sync.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.flower.demo-gateway-sync</string>
  <key>ProgramArguments</key>
  <array>
    <string>$RUNTIME_DIR/scripts/run_gateway_sync.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$RUNTIME_DIR</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$RUNTIME_DIR/logs/gateway-sync.out.log</string>
  <key>StandardErrorPath</key>
  <string>$RUNTIME_DIR/logs/gateway-sync.err.log</string>
</dict>
</plist>
EOF

cp "$RUNTIME_DIR/ops/launchd/com.flower.demo-api.plist" "$LAUNCH_AGENTS_DIR/com.flower.demo-api.plist"
cp "$RUNTIME_DIR/ops/launchd/com.flower.demo-tunnel.plist" "$LAUNCH_AGENTS_DIR/com.flower.demo-tunnel.plist"
cp "$RUNTIME_DIR/ops/launchd/com.flower.demo-gateway-sync.plist" "$LAUNCH_AGENTS_DIR/com.flower.demo-gateway-sync.plist"

launchctl bootout "gui/$USER_ID" "$LAUNCH_AGENTS_DIR/com.flower.demo-api.plist" 2>/dev/null || true
launchctl bootout "gui/$USER_ID" "$LAUNCH_AGENTS_DIR/com.flower.demo-tunnel.plist" 2>/dev/null || true
launchctl bootout "gui/$USER_ID" "$LAUNCH_AGENTS_DIR/com.flower.demo-gateway-sync.plist" 2>/dev/null || true
launchctl bootstrap "gui/$USER_ID" "$LAUNCH_AGENTS_DIR/com.flower.demo-api.plist"
launchctl bootstrap "gui/$USER_ID" "$LAUNCH_AGENTS_DIR/com.flower.demo-tunnel.plist"
launchctl bootstrap "gui/$USER_ID" "$LAUNCH_AGENTS_DIR/com.flower.demo-gateway-sync.plist"

for _ in {1..30}; do
  if curl --noproxy '*' -fsS -m 2 http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "Installed launchd services from $RUNTIME_DIR"
"$RUNTIME_DIR/scripts/demo_status.sh"
