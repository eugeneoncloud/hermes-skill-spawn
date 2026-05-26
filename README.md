# hermes-skill-onboard

Automates the full lifecycle of wiring a GitHub-hosted hermes skill into a Slack-backed cron delivery pipeline.

## What it does

When a user shares a GitHub skill URL in Slack, hermes:
1. Installs the skill via `hermes skills install`
2. Reads the skill's description and brainstorms the setup with the user
3. Creates a dedicated Slack channel
4. Generates a per-skill `deliver.py` script in `~/.hermes/workspace/<skill-name>/`
5. Creates a cron job that runs on the chosen schedule

Each cron run follows a deterministic pattern:
- Agent runs the skill and saves the full report to `~/.hermes/workspace/<skill-name>/reports/YYYYMMDD_HHMM.md`
- `deliver.py` creates a Slack canvas from the report file
- `deliver.py` sends a clean 3-line notification to the channel with the canvas link

## File Structure

```
~/.hermes/skills/productivity/hermes-skill-onboard/
├── SKILL.md                   ← loaded by hermes agent
├── README.md                  ← this file
├── .env.example               ← credential template (commit this, not .env)
├── .env                       ← your credentials (created by setup.sh, gitignored)
└── scripts/
    ├── setup.sh               ← interactive credential setup
    ├── setup_workflow.py      ← deterministic provisioning orchestrator
    └── deliver_template.py    ← template for generated deliver.py

~/.hermes/workspace/<skill-name>/       ← created by setup_workflow.py
├── deliver.py                          ← generated from deliver_template.py
└── reports/                            ← output files from each cron run
    └── YYYYMMDD_HHMM.md
```

## Setup

### 1. Configure credentials

Run the interactive setup script. It will prompt for your Slack tokens, validate them, and write them to `.env`:

```bash
bash ~/.hermes/skills/productivity/hermes-skill-onboard/scripts/setup.sh
```

What it asks for:

| Variable | Where to find it | Format |
|---|---|---|
| `SLACK_BOT_TOKEN` | api.slack.com/apps → Your App → OAuth & Permissions → Bot User OAuth Token | `xoxb-...` |
| `SLACK_APP_TOKEN` | api.slack.com/apps → Your App → Basic Information → App-Level Tokens | `xapp-...` |

The script writes to two places:
- `~/.hermes/skills/productivity/hermes-skill-onboard/.env` — skill-local config
- `~/.hermes/.env` — global hermes config (required by shared Slack scripts)

### 2. Verify

```bash
python3 ~/.hermes/skills/productivity/slack/scripts/slack_auth.py
```

Expected output: `✅ Authentication test passed!`

## Usage

### Trigger via Slack

Send hermes a message like:

```
install this skill and run it daily: https://github.com/owner/my-skill
```

hermes will guide you through the brainstorm and set everything up.

### Manual provisioning

```bash
python ~/.hermes/skills/productivity/hermes-skill-onboard/scripts/setup_workflow.py \
  --skill-name my-skill \
  --channel-name my-skill-reports \
  --schedule "0 9 * * 1-5" \
  --description "Daily morning analysis of X for trading decisions"
```

Output (JSON):
```json
{
  "success": true,
  "skill_name": "my-skill",
  "channel_id": "C0XXXXXXXXX",
  "channel_name": "my-skill-reports",
  "workspace": "/home/ubuntu/.hermes/workspace/my-skill",
  "deliver_script": "/home/ubuntu/.hermes/workspace/my-skill/deliver.py",
  "job_id": "abc123def456",
  "schedule": "0 9 * * 1-5",
  "next_run_at": "2026-05-27T09:00:00+00:00"
}
```

### Test the delivery pipeline in isolation

After setup, you can verify the canvas + notification flow without running the full cron:

```bash
echo "# Test Report\n\nSome content here." > /tmp/test_report.md
python ~/.hermes/workspace/my-skill/deliver.py /tmp/test_report.md
```

Expected: canvas created in `#my-skill-reports`, clean 3-line notification posted with canvas link.

## Credential Loading

Both `setup_workflow.py` and the generated `deliver.py` use the same lookup order:

1. `~/.hermes/skills/productivity/hermes-skill-onboard/.env` (skill root)
2. `~/.hermes/.env` (global hermes fallback)

`SLACK_BOT_TOKEN` is required. `SLACK_APP_TOKEN` is required for socket mode / event subscriptions.

The workspace URL and team ID are never hardcoded — `deliver.py` calls `auth.test` at runtime to derive them.

## Cron Job Prompt Structure

The setup script generates a structured prompt baked into the cron job:

```
TASK: Run <skill-name> — <description>

STEP 1: Load skill: <skill-name>
STEP 2: Execute — produce a complete report in markdown
STEP 3: Save output to ~/.hermes/workspace/<skill>/reports/YYYYMMDD_HHMM.md
STEP 4: Run python ~/.hermes/workspace/<skill>/deliver.py <report_file>
```

The agent executes steps 1–3. `deliver.py` handles step 4 deterministically.

## Delivery Notification Format

Each successful run posts to the Slack channel:

```
📋 <skill-name> Report Updated
📅 2026-05-27 09:00 UTC
🔗 <https://<workspace>.slack.com/docs/<team_id>/FXXXXXXXX|View Canvas>
```

If canvas creation fails, the script falls back to posting an inline excerpt.

## Dependencies

- `~/.hermes/skills/productivity/slack/scripts/slack_auth.py` — token fallback
- `~/.hermes/skills/productivity/slack/scripts/create-canvas.py` — canvas creation
- `~/.hermes/skills/productivity/slack/scripts/send-message.py` — notification
- hermes-agent `tools/cronjob_tools.py` — cron job creation (imported directly, falls back to `hermes cron create` CLI)

## Idempotency

- **Channel creation**: if name already exists, fetches existing channel ID and continues
- **Workspace**: created with `exist_ok=True`
- **deliver.py**: always regenerated (overwrites previous)
- **Cron job**: always creates a new job; does not deduplicate
