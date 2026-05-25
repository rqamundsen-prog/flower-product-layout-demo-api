#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${FLOWER_RUNTIME_DIR:-$HOME/flower-server}"
CONFIG_PATH="$PROJECT_DIR/cloudflare/wrangler.toml"
NPX_BIN="${NPX_BIN:-$(command -v npx)}"

current_tunnel_url() {
  grep -hEo 'https://[a-zA-Z0-9.-]+\.trycloudflare\.com' "$RUNTIME_DIR"/logs/cloudflared.*.log 2>/dev/null | tail -n 1
}

ORIGIN_URL="${1:-$(current_tunnel_url)}"
if [[ -z "$ORIGIN_URL" ]]; then
  echo "No current trycloudflare origin URL found." >&2
  exit 1
fi

echo "Checking origin: $ORIGIN_URL"
curl --noproxy '*' -fsS -m 20 "$ORIGIN_URL/api/health" >/dev/null

echo "Updating Cloudflare KV origin..."
"$NPX_BIN" wrangler kv key put origin "$ORIGIN_URL" --config "$CONFIG_PATH" --binding FLOWER_DEMO_CONFIG --remote

echo "Deploying fixed Cloudflare Worker gateway..."
"$NPX_BIN" wrangler deploy --config "$CONFIG_PATH"
