---
name: hermes-skill-onboard
description: Use when the user shares a GitHub skill URL and wants to set up automated reports, summaries, or recurring tasks. Installs the skill, creates a dedicated Slack channel, generates a deterministic delivery script, and provisions a cron job that saves reports to workspace and delivers them as Slack canvases.
version: 1.0.0
author: hermes
metadata:
  hermes:
    tags: [skills, cron, slack, automation, canvas, onboarding, setup]
    related_skills: [slack, cronjob]
---

# Hermes Skill Onboard

Automates the full provisioning lifecycle when a user wants to put a GitHub skill to work on a recurring schedule: install → brainstorm → create Slack channel → create workspace → generate deliver script → create cron job.

## When to Use

- User shares a GitHub URL (e.g. `https://github.com/owner/repo`) and asks to "set up", "automate", or "schedule" it
- User says "run this skill daily", "create a weekly report with X", or similar
- User wants a new skill wired into Slack with canvas delivery

Do NOT use for: one-off skill runs, skill browsing/search, or editing existing cron jobs.

---

## Execution Flow

Follow these steps **in order**. Do not skip or reorder.

### Step 1 — Install the skill

```bash
hermes skills install <github-url>
```

If the install fails, report the error to the user and stop. Do not proceed.

After install, find and read the skill's `SKILL.md` or `README.md` to understand what it does. The installed path will be under `~/.hermes/skills/`.

### Step 2 — Brainstorm with the user (via Slack)

Reply with a short structured message:

```
I've installed **<skill-name>**. Here's what it does:
> <1–2 line summary from the skill's README/SKILL.md>

To wire it up with automated delivery, I need a few details:

1. **Schedule** — How often should this run? (e.g. "daily 9am", "weekdays 8am SGT", "every Friday 5pm")
2. **Channel name** — What should I call the new Slack channel? (default: `<skill-name>`)
3. **Focus** — Any specific instructions for each run? Or just use the skill's defaults?

Reply with your answers and I'll set everything up.
```

Wait for the user's reply before proceeding.

### Step 3 — Confirm parameters and run the setup script

Once the user has answered, confirm back with:

```
Got it. Here's what I'll create:
- 📺 Slack channel: #<channel-name>
- ⏰ Schedule: <human schedule> (<cron expression>)
- 🎯 Task: <description>
- 📁 Workspace: ~/.hermes/workspace/<skill-name>/

Should I proceed?
```

After the user confirms, run:

```bash
python ~/.hermes/skills/productivity/hermes-skill-onboard/scripts/setup_workflow.py \
  --skill-name "<skill-name>" \
  --channel-name "<channel-name>" \
  --schedule "<cron-expression>" \
  --description "<user's stated goal in one sentence>"
```

### Step 4 — Parse output and report back

The script outputs JSON. Parse it and report to the user:

```
✅ All set! Here's what was created:

- **Channel**: #<channel_name> (ID: <channel_id>)
- **Workspace**: `<workspace>`
- **Cron job**: `<job_id>` — runs <schedule_display>
- **First run**: <next_run_at>
- **Delivery script**: `<deliver_script>`

Each run will:
1. Execute the <skill_name> skill
2. Save the report to `<workspace>/reports/`
3. Create a Slack canvas and post the link to #<channel_name>
```

If the script exits non-zero or returns `"success": false`, report the error and offer to retry.

---

## Schedule Conversion Reference

| User says | Cron expression |
|-----------|----------------|
| daily 9am | `0 9 * * *` |
| daily 9am SGT (UTC+8) | `0 1 * * *` |
| weekdays 8am SGT | `0 0 * * 1-5` |
| twice daily 9am & 3pm | `0 9,15 * * *` |
| every Friday 5pm SGT | `0 9 * * 5` |
| weekly Monday 9am SGT | `0 1 * * 1` |

Always convert timezone to UTC when building the cron expression.

---

## Common Pitfalls

1. **Skill install fails with rate limit** — Set `GITHUB_TOKEN` env var and retry.
2. **Channel name conflicts** — Slack channel names must be lowercase, no spaces. Replace spaces with hyphens; the script handles this automatically.
3. **User says no cron needed** — Skip Step 3/4; just install the skill and confirm it's ready to use manually.
4. **User doesn't confirm** — Don't run the setup script until the user explicitly says yes or proceed.
5. **Description too vague** — Ask for clarification. The description becomes the cron job prompt — specificity matters.

---

## Verification Checklist

- [ ] `hermes skills install <url>` returned success
- [ ] Brainstorm message sent and user replied with schedule/channel/focus
- [ ] User confirmed before running setup script
- [ ] Setup script exited 0 and returned `"success": true`
- [ ] Reported channel name, job ID, and first run time to user
