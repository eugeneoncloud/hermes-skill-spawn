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
└── scripts/
    ├── setup_workflow.py      ← deterministic orchestrator
    └── deliver_template.py    ← template for generated deliver.py

~/.hermes/workspace/<skill-name>/       ← created by setup_workflow.py
├── deliver.py                          ← generated from deliver_template.py
└── reports/                            ← output files from each cron run
    └── YYYYMMDD_HHMM.md
```

## Usage

### Trigger via Slack

Send hermes a message like:

```
install this skill and run it daily: https://github.com/owner/my-skill
```

hermes will guide you through the brainstorm and set everything up.

### Manual setup (direct script)

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

### Test deliver.py in isolation

After setup, you can test the delivery pipeline without running the full cron agent:

```bash
echo "# Test Report\n\nSome content here." > /tmp/test_report.md
python ~/.hermes/workspace/my-skill/deliver.py /tmp/test_report.md
```

This creates a canvas in the skill's Slack channel and sends a notification with the canvas link.

## Cron Job Prompt Template

The setup script generates a structured cron prompt that tells the agent exactly what to do:

```
TASK: Run <skill-name> — <description>

STEP 1: Load skill: <skill-name>

STEP 2: Execute
<description>
Produce a complete, detailed report in markdown format.

STEP 3: Save output (REQUIRED)
Save the full report to: ~/.hermes/workspace/<skill>/reports/YYYYMMDD_HHMM.md

STEP 4: Deliver (REQUIRED — do not skip)
Run: python ~/.hermes/workspace/<skill>/deliver.py <report_file>
```

The agent handles skill execution and file writing. `deliver.py` handles everything after that deterministically.

## Delivery Notification Format

Each successful run posts to the Slack channel:

```
📋 <skill-name> Report Updated
📅 2026-05-27 09:00 UTC
🔗 <https://eugeneoncloud.slack.com/docs/T09M25MA56E/FXXXXXXXX|View Canvas>
```

If canvas creation fails, the script falls back to posting the report summary inline.

## Dependencies

- `~/.hermes/skills/productivity/slack/scripts/slack_auth.py` — Slack token
- `~/.hermes/skills/productivity/slack/scripts/create-canvas.py` — Canvas creation
- `~/.hermes/skills/productivity/slack/scripts/send-message.py` — Notification
- hermes-agent's `tools/cronjob_tools.py` — Cron job creation (imported directly)

## Idempotency

- **Channel creation**: if the channel name already exists, the script fetches the existing channel ID and continues
- **Workspace**: directories are created with `exist_ok=True`
- **deliver.py**: always regenerated (overwrites previous version)
- **Cron job**: always creates a new job; does not deduplicate
