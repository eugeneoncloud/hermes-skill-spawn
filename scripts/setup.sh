#!/usr/bin/env bash
# hermes-skill-onboard — interactive setup
#
# Prompts for required credentials, writes them to .env in the skill root,
# and syncs them into ~/.hermes/.env so the shared Slack scripts work too.
#
# Usage: bash scripts/setup.sh

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HERMES_ENV="$HOME/.hermes/.env"
SKILL_ENV="$SKILL_DIR/.env"

# ─── Helpers ──────────────────────────────────────────────────────────────────

green()  { printf '\033[0;32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[0;33m%s\033[0m\n' "$*"; }
red()    { printf '\033[0;31m%s\033[0m\n' "$*"; }
bold()   { printf '\033[1m%s\033[0m\n' "$*"; }
dim()    { printf '\033[2m%s\033[0m' "$*"; }

_read_existing() {
    # Read a variable from a file, return empty string if not found
    local file="$1" var="$2"
    if [[ -f "$file" ]]; then
        grep -m1 "^${var}=" "$file" 2>/dev/null | cut -d'=' -f2- | tr -d '"'"'" || true
    fi
}

_upsert_env() {
    # Set or replace a variable in a file
    local file="$1" var="$2" value="$3"
    if grep -q "^${var}=" "$file" 2>/dev/null; then
        sed -i "s|^${var}=.*|${var}=${value}|" "$file"
    else
        printf '\n%s=%s\n' "$var" "$value" >> "$file"
    fi
}

_mask() {
    local val="$1"
    if [[ -z "$val" ]]; then echo "(not set)"; return; fi
    local len=${#val}
    if [[ $len -le 8 ]]; then echo "****"; return; fi
    echo "${val:0:8}****"
}

# ─── Header ───────────────────────────────────────────────────────────────────

echo ""
bold "╔══════════════════════════════════════════════╗"
bold "║     hermes-skill-onboard — Setup             ║"
bold "╚══════════════════════════════════════════════╝"
echo ""
echo "This script will:"
echo "  1. Check Python dependencies"
echo "  2. Collect your Slack credentials"
echo "  3. Write them to: $SKILL_ENV"
echo "  4. Sync them into: $HERMES_ENV"
echo "  5. Validate the Slack token"
echo ""

# ─── Python deps ──────────────────────────────────────────────────────────────

bold "── Python dependencies ──────────────────────────"
echo ""

PYTHON=$(command -v python3 || command -v python || true)
if [[ -z "$PYTHON" ]]; then
    red "✗ Python 3 not found. Install it and re-run."
    exit 1
fi
green "✓ Python: $($PYTHON --version)"

if $PYTHON -c "import requests" &>/dev/null; then
    green "✓ requests"
else
    yellow "  Installing requests..."
    $PYTHON -m pip install --quiet requests
    green "✓ requests (installed)"
fi

echo ""

# ─── Collect credentials ──────────────────────────────────────────────────────

bold "── Slack credentials ────────────────────────────"
echo ""
dim "  Where to find them:"; echo ""
echo "  SLACK_BOT_TOKEN  → api.slack.com/apps > Your App > OAuth & Permissions"
echo "  SLACK_APP_TOKEN  → api.slack.com/apps > Your App > Basic Information > App-Level Tokens"
echo ""

# Read existing values (skill .env takes priority, then hermes .env)
EXISTING_BOT=$(_read_existing "$SKILL_ENV" "SLACK_BOT_TOKEN")
[[ -z "$EXISTING_BOT" ]] && EXISTING_BOT=$(_read_existing "$HERMES_ENV" "SLACK_BOT_TOKEN")

EXISTING_APP=$(_read_existing "$SKILL_ENV" "SLACK_APP_TOKEN")
[[ -z "$EXISTING_APP" ]] && EXISTING_APP=$(_read_existing "$HERMES_ENV" "SLACK_APP_TOKEN")

# SLACK_BOT_TOKEN
if [[ -n "$EXISTING_BOT" ]]; then
    echo "  SLACK_BOT_TOKEN — current: $(_mask "$EXISTING_BOT")"
    printf "  New value (Enter to keep current): "
else
    printf "  SLACK_BOT_TOKEN (xoxb-...): "
fi
read -r INPUT_BOT
SLACK_BOT_TOKEN="${INPUT_BOT:-$EXISTING_BOT}"

if [[ -z "$SLACK_BOT_TOKEN" ]]; then
    red "✗ SLACK_BOT_TOKEN is required."
    exit 1
fi
echo ""

# SLACK_APP_TOKEN
if [[ -n "$EXISTING_APP" ]]; then
    echo "  SLACK_APP_TOKEN — current: $(_mask "$EXISTING_APP")"
    printf "  New value (Enter to keep current): "
else
    printf "  SLACK_APP_TOKEN (xapp-...): "
fi
read -r INPUT_APP
SLACK_APP_TOKEN="${INPUT_APP:-$EXISTING_APP}"

if [[ -z "$SLACK_APP_TOKEN" ]]; then
    yellow "  ⚠  SLACK_APP_TOKEN not provided — socket mode and event subscriptions won't work."
fi
echo ""

# ─── Write skill .env ─────────────────────────────────────────────────────────

bold "── Writing .env files ───────────────────────────"
echo ""

# Initialise skill .env from example if it doesn't exist
if [[ ! -f "$SKILL_ENV" ]]; then
    cp "$SKILL_DIR/.env.example" "$SKILL_ENV"
fi

_upsert_env "$SKILL_ENV" "SLACK_BOT_TOKEN" "$SLACK_BOT_TOKEN"
[[ -n "$SLACK_APP_TOKEN" ]] && _upsert_env "$SKILL_ENV" "SLACK_APP_TOKEN" "$SLACK_APP_TOKEN"
green "✓ Written: $SKILL_ENV"

# Sync into ~/.hermes/.env so shared slack scripts (create-canvas.py, send-message.py) work
mkdir -p "$(dirname "$HERMES_ENV")"
[[ ! -f "$HERMES_ENV" ]] && touch "$HERMES_ENV"
_upsert_env "$HERMES_ENV" "SLACK_BOT_TOKEN" "$SLACK_BOT_TOKEN"
[[ -n "$SLACK_APP_TOKEN" ]] && _upsert_env "$HERMES_ENV" "SLACK_APP_TOKEN" "$SLACK_APP_TOKEN"
green "✓ Synced:  $HERMES_ENV"

echo ""

# ─── Validate token ───────────────────────────────────────────────────────────

bold "── Validating Slack token ───────────────────────"
echo ""

VALIDATE_RESULT=$($PYTHON - <<PYEOF
import json, urllib.request
token = "$SLACK_BOT_TOKEN"
req = urllib.request.Request(
    "https://slack.com/api/auth.test",
    headers={"Authorization": f"Bearer {token}"}
)
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    if data.get("ok"):
        print("ok|" + data.get("team","?") + "|" + data.get("user","?"))
    else:
        print("err|" + data.get("error","unknown"))
except Exception as e:
    print("err|" + str(e))
PYEOF
)

STATUS="${VALIDATE_RESULT%%|*}"
REST="${VALIDATE_RESULT#*|}"

if [[ "$STATUS" == "ok" ]]; then
    TEAM="${REST%%|*}"
    USER="${REST##*|}"
    green "✓ Token valid — workspace: $TEAM, bot: $USER"
else
    red "✗ Token validation failed: $REST"
    echo "  Check the token and re-run this script."
    exit 1
fi

echo ""

# ─── Make scripts executable ──────────────────────────────────────────────────

chmod +x "$SKILL_DIR/scripts/"*.py 2>/dev/null || true

# ─── Done ─────────────────────────────────────────────────────────────────────

bold "── Done ─────────────────────────────────────────"
echo ""
green "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  Run setup_workflow.py to provision a skill pipeline:"
echo ""
echo "  python $SKILL_DIR/scripts/setup_workflow.py \\"
echo "    --skill-name <name> \\"
echo "    --channel-name <channel> \\"
echo "    --schedule \"0 9 * * 1-5\" \\"
echo "    --description \"Daily report about ...\""
echo ""
