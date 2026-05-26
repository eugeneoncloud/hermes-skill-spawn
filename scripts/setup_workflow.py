#!/usr/bin/env python3
"""
hermes-skill-onboard — deterministic provisioning script.

Called by hermes agent after brainstorming with the user. Creates:
  1. Slack channel
  2. Workspace directory + reports/ subdirectory
  3. Per-skill deliver.py (from deliver_template.py)
  4. Cron job

Usage:
  python setup_workflow.py \\
    --skill-name <name> \\
    --channel-name <name> \\
    --schedule "<cron>" \\
    --description "<goal>" \\
    [--workspace ~/.hermes/workspace] \\
    [--slack-scripts <path>]

Outputs JSON to stdout.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
HERMES_HOME = Path.home() / ".hermes"
HERMES_AGENT_DIR = HERMES_HOME / "hermes-agent"
SLACK_SCRIPTS_DEFAULT = HERMES_HOME / "skills" / "productivity" / "slack" / "scripts"
DELIVER_TEMPLATE = SCRIPT_DIR / "deliver_template.py"

# .env lookup order: skill root first, then global hermes .env
_ENV_PATHS = [SKILL_DIR / ".env", HERMES_HOME / ".env"]


# ---------------------------------------------------------------------------
# .env loader
# ---------------------------------------------------------------------------

def _load_env() -> dict[str, str]:
    """Parse KEY=VALUE pairs from the first .env file that exists."""
    for path in _ENV_PATHS:
        if path.exists():
            env: dict[str, str] = {}
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                env[key.strip()] = val.strip().strip('"').strip("'")
            if env:
                return env
    return {}


# ---------------------------------------------------------------------------
# Slack helpers
# ---------------------------------------------------------------------------

def _get_slack_token() -> str | None:
    """Load SLACK_BOT_TOKEN from .env (skill root → ~/.hermes/.env)."""
    env = _load_env()
    token = env.get("SLACK_BOT_TOKEN")
    if token:
        return token
    # Fallback: try slack_auth.py (reads ~/.hermes/.env directly)
    sys.path.insert(0, str(SLACK_SCRIPTS_DEFAULT))
    try:
        from slack_auth import get_slack_token
        return get_slack_token()
    except Exception as e:
        _err(f"Could not load slack_auth: {e}")
        return None


def _slack_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _slack_post(token: str, endpoint: str, payload: dict) -> dict:
    import urllib.request
    url = f"https://slack.com/api/{endpoint}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=_slack_headers(token))
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _slack_get(token: str, endpoint: str, params: dict) -> dict:
    import urllib.parse
    import urllib.request
    qs = urllib.parse.urlencode(params)
    url = f"https://slack.com/api/{endpoint}?{qs}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _sanitize_channel_name(name: str) -> str:
    """Slack channel names: lowercase, alphanumeric + hyphens, max 80 chars."""
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9\-]", "-", name)
    name = re.sub(r"-{2,}", "-", name).strip("-")
    return name[:80]


def create_slack_channel(token: str, channel_name: str) -> tuple[str, str]:
    """
    Create Slack channel. Returns (channel_id, channel_name).
    If name_taken, fetches and returns the existing channel's ID.
    """
    safe_name = _sanitize_channel_name(channel_name)
    resp = _slack_post(token, "conversations.create", {"name": safe_name, "is_private": False})

    if resp.get("ok"):
        ch = resp["channel"]
        return ch["id"], ch["name"]

    if resp.get("error") == "name_taken":
        # Fetch the existing channel
        list_resp = _slack_get(token, "conversations.list", {
            "limit": 200,
            "types": "public_channel,private_channel",
        })
        for ch in list_resp.get("channels", []):
            if ch.get("name") == safe_name:
                return ch["id"], ch["name"]
        raise RuntimeError(f"Channel '{safe_name}' name_taken but not found in list")

    raise RuntimeError(f"conversations.create failed: {resp.get('error', resp)}")


def invite_bot_to_channel(token: str, channel_id: str) -> None:
    """Invite the bot user itself to the channel (needed for private channels)."""
    auth_resp = _slack_get(token, "auth.test", {})
    bot_user_id = auth_resp.get("user_id")
    if not bot_user_id:
        return  # can't determine bot ID, skip
    resp = _slack_post(token, "conversations.invite", {
        "channel": channel_id,
        "users": bot_user_id,
    })
    # already_in_channel is fine
    if not resp.get("ok") and resp.get("error") not in ("already_in_channel", "cant_invite_self"):
        _warn(f"Could not invite bot to channel: {resp.get('error')}")


# ---------------------------------------------------------------------------
# Workspace + deliver.py
# ---------------------------------------------------------------------------

def create_workspace(workspace_root: Path, skill_name: str) -> Path:
    """Create workspace and reports subdirectory. Returns workspace path."""
    workspace = workspace_root / skill_name
    (workspace / "reports").mkdir(parents=True, exist_ok=True)
    return workspace


def generate_deliver_script(
    workspace: Path,
    skill_name: str,
    channel_id: str,
    channel_name: str,
    slack_scripts: Path,
) -> Path:
    """Read deliver_template.py, fill placeholders, write to workspace/deliver.py."""
    template = DELIVER_TEMPLATE.read_text(encoding="utf-8")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    skill_env_path = str(SKILL_DIR / ".env")

    deliver_script = template.replace("{SKILL_NAME}", skill_name)
    deliver_script = deliver_script.replace("{CHANNEL_ID}", channel_id)
    deliver_script = deliver_script.replace("{CHANNEL_NAME}", channel_name)
    deliver_script = deliver_script.replace("{SLACK_SCRIPTS}", str(slack_scripts))
    deliver_script = deliver_script.replace("{GENERATED_AT}", now_str)
    deliver_script = deliver_script.replace("{SKILL_ENV_PATH}", skill_env_path)

    out_path = workspace / "deliver.py"
    out_path.write_text(deliver_script, encoding="utf-8")
    out_path.chmod(0o755)
    return out_path


# ---------------------------------------------------------------------------
# Cron job
# ---------------------------------------------------------------------------

CRON_PROMPT_TEMPLATE = """\
TASK: Run {skill_name} — {description}

STEP 1: Load skill
- Load skill: {skill_name}

STEP 2: Execute
{description}
Produce a complete, detailed report in markdown format. Be thorough and specific.

STEP 3: Save output (REQUIRED)
Capture the current timestamp first:
  REPORT_TS=$(date +%Y%m%d_%H%M)
  REPORT_FILE="{workspace}/reports/${{REPORT_TS}}.md"

Write the full report to that file:
  cat > "$REPORT_FILE" << 'REPORT_EOF'
[insert your complete report here — every section, all data, full markdown]
REPORT_EOF

STEP 4: Deliver (REQUIRED — do not skip)
Run the delivery script to create a canvas and notify #{channel_name}:
  python {workspace}/deliver.py "$REPORT_FILE"

CRITICAL:
- Complete BOTH steps 3 and 4 on every single run.
- The canvas notification goes to #{channel_name} — do not post elsewhere.
- Do NOT include execution logs, step summaries, or "task completed" messages in the Slack notification.
"""


def create_cron_job(
    skill_name: str,
    channel_name: str,
    schedule: str,
    description: str,
    workspace: Path,
) -> dict:
    """
    Create a hermes cron job by importing cronjob_tools directly.
    Falls back to subprocess `hermes cron create` if import fails.
    """
    prompt = CRON_PROMPT_TEMPLATE.format(
        skill_name=skill_name,
        description=description,
        workspace=str(workspace),
        channel_name=channel_name,
    )
    job_name = f"{skill_name} — {description[:50]}"
    deliver = f"slack:#{channel_name}"

    # Try direct Python import first (no subprocess overhead, better error msgs)
    try:
        sys.path.insert(0, str(HERMES_AGENT_DIR))
        from tools.cronjob_tools import cronjob
        result_json = cronjob(
            action="create",
            schedule=schedule,
            name=job_name,
            prompt=prompt,
            skills=[skill_name],
            deliver=deliver,
            enabled_toolsets=["web", "search", "terminal", "file"],
        )
        result = json.loads(result_json)
        if not result.get("success"):
            raise RuntimeError(result.get("error", "unknown cronjob error"))
        return result
    except ImportError:
        pass  # fall through to subprocess

    # Subprocess fallback
    prompt_file = Path(f"/tmp/hermes_cron_prompt_{skill_name}.txt")
    prompt_file.write_text(prompt, encoding="utf-8")
    try:
        out = subprocess.check_output(
            [
                "hermes", "cron", "create",
                "--schedule", schedule,
                "--name", job_name,
                "--skill", skill_name,
                "--deliver", deliver,
                "--prompt", prompt,
            ],
            text=True,
            stderr=subprocess.STDOUT,
        )
        # hermes cron create prints "Created job: <id>" — parse it
        for line in out.splitlines():
            if line.startswith("Created job:"):
                job_id = line.split(":", 1)[-1].strip()
                return {"success": True, "job_id": job_id, "name": job_name}
        raise RuntimeError(f"Unexpected hermes cron output:\n{out}")
    finally:
        prompt_file.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _err(msg: str) -> None:
    print(f"[setup_workflow] ERROR: {msg}", file=sys.stderr)


def _warn(msg: str) -> None:
    print(f"[setup_workflow] WARN: {msg}", file=sys.stderr)


def _out(data: dict) -> None:
    print(json.dumps(data, indent=2, default=str))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="hermes-skill-onboard provisioning script")
    p.add_argument("--skill-name", required=True, help="Installed hermes skill name")
    p.add_argument("--channel-name", required=True, help="Slack channel to create")
    p.add_argument("--schedule", required=True, help="Cron expression (UTC)")
    p.add_argument("--description", required=True, help="What the cron job should do")
    p.add_argument("--workspace", default=str(HERMES_HOME / "workspace"),
                   help="Root workspace directory (default: ~/.hermes/workspace)")
    p.add_argument("--slack-scripts", default=str(SLACK_SCRIPTS_DEFAULT),
                   help="Path to slack scripts directory")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    slack_scripts = Path(args.slack_scripts)
    workspace_root = Path(args.workspace).expanduser()

    # Step 1: Slack token
    token = _get_slack_token()
    if not token:
        _out({"success": False, "error": "No Slack token found. Check your .env or auth config."})
        return 1

    # Step 2: Create Slack channel
    try:
        channel_id, channel_name = create_slack_channel(token, args.channel_name)
    except Exception as e:
        _out({"success": False, "error": f"Channel creation failed: {e}"})
        return 1

    # Step 3: Invite bot
    invite_bot_to_channel(token, channel_id)

    # Step 4: Create workspace
    try:
        workspace = create_workspace(workspace_root, args.skill_name)
    except Exception as e:
        _out({"success": False, "error": f"Workspace creation failed: {e}"})
        return 1

    # Step 5: Generate deliver.py
    try:
        deliver_script = generate_deliver_script(
            workspace=workspace,
            skill_name=args.skill_name,
            channel_id=channel_id,
            channel_name=channel_name,
            slack_scripts=slack_scripts,
        )
    except Exception as e:
        _out({"success": False, "error": f"deliver.py generation failed: {e}"})
        return 1

    # Step 6: Create cron job
    try:
        cron_result = create_cron_job(
            skill_name=args.skill_name,
            channel_name=channel_name,
            schedule=args.schedule,
            description=args.description,
            workspace=workspace,
        )
    except Exception as e:
        _out({"success": False, "error": f"Cron job creation failed: {e}"})
        return 1

    _out({
        "success": True,
        "skill_name": args.skill_name,
        "channel_id": channel_id,
        "channel_name": channel_name,
        "workspace": str(workspace),
        "deliver_script": str(deliver_script),
        "job_id": cron_result.get("job_id"),
        "schedule": args.schedule,
        "next_run_at": cron_result.get("next_run_at"),
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
