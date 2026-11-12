#!/usr/bin/env bash
# Smoke test of a built binary: start it, wait for /health, check the page, stop it.
#   packaging/smoke.sh path/to/AutonomousAgent[.exe]
set -euo pipefail
BIN="$1"
PORT="${SMOKE_PORT:-8799}"
HOME_DIR="$(mktemp -d)"
export AGENT_HOME="$HOME_DIR" AGENT_NO_BROWSER=1 AGENT_NO_TERMINAL=1 AGENT_PORT="$PORT"
unset AGENT_PROVIDER GROQ_API_KEY OPENAI_API_KEY OPENROUTER_API_KEY || true
"$BIN" > "$HOME_DIR/launcher.log" 2>&1 &
PID=$!
ok=""
for _ in $(seq 1 90); do
  if curl -fsS "http://127.0.0.1:$PORT/health" -o "$HOME_DIR/health.json"; then ok=1; break; fi
  sleep 1
done
cat "$HOME_DIR/launcher.log" || true
stop() {
  kill "$PID" 2>/dev/null || true
  if command -v taskkill >/dev/null 2>&1; then taskkill //F //T //IM "$(basename "$BIN")" >/dev/null 2>&1 || true; fi
}
if [ -z "$ok" ]; then stop; echo "FAIL: /health did not answer"; exit 1; fi
cat "$HOME_DIR/health.json"; echo
grep -q '"status": "ok"' "$HOME_DIR/health.json"
grep -q '"provider": "mock"' "$HOME_DIR/health.json"
test "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/")" = 200
test -f "$HOME_DIR/.env" && test -d "$HOME_DIR/workspace" && test -f "$HOME_DIR/permissions.yaml"
stop
echo "smoke OK"
