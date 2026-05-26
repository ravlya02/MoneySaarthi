---
description: Create a spec file and feature branch for the next MoneySaarthi step
argument-hint: "Step number and feature name e.g. 2 tax-engine"
allowed-tools: Read, Write, Glob, Bash(git:*)
---

You are a senior developer building MoneySaarthi — an AI-driven personal finance,
tax & investment advisory platform for India. Always follow the rules in CLAUDE.md.

User input: $ARGUMENTS

## Step 1 — Check working directory is clean
Run `git status` and check for uncommitted, unstaged, or untracked files.
If any exist, stop immediately and tell the user to commit or stash changes
before proceeding.
DO NOT CONTINUE until the working directory is clean.

## Step 2 — Parse the arguments
From $ARGUMENTS extract:

1. `step_number` — zero-padded to 2 digits: 2 → 02, 11 → 11

2. `feature_title` — human readable title in Title Case
   - Example: "Tax Engine" or "Onboarding Form"

3. `feature_slug` — git and file safe slug
   - Lowercase, kebab-case
   - Only a-z, 0-9 and -
   - Maximum 40 characters
   - Example: tax-engine, onboarding-form

4. `branch_name` — format: `feature/<feature_slug>`
   - Example: `feature/tax-engine`

If you cannot infer these from $ARGUMENTS, ask the user to clarify before
proceeding.

## Step 3 — Check branch name is not taken
Run `git branch` to list existing branches.
If `branch_name` is already taken, append a number:
`feature/tax-engine-01`, `feature/tax-engine-02` etc.

## Step 4 — Switch to main and pull latest
Run:
```
git checkout main
git pull origin main
```

## Step 5 — Create and switch to the feature branch
Run:
```
git checkout -b <branch_name>
```

## Step 6 — Research the codebase
Read these files before writing the spec:
- `CLAUDE.md` — architecture, guardrails, conventions
- `documents/architecture.md` — authoritative design reference (§A–§E)
- `app/main.py` — existing FastAPI app and router mounts
- `app/db/schema.sql` — full database schema
- `app/db/policies.sql` — RLS policies
- `app/models/intake.py`, `app/models/reports.py` — Pydantic models
- All files in `.claude/specs/` — avoid duplicating existing specs

Check `CLAUDE.md` to confirm the requested step is not already implemented.
If it is, warn the user and stop.

## Step 7 — Write the spec
Generate a spec document with this exact structure:

---
# Spec: <feature_title>

## Overview
One paragraph describing what this feature does and why it exists at this
stage of the MoneySaarthi roadmap.

## Depends on
Which previous steps this feature requires to be complete.

## Architecture phase
Which phase from CLAUDE.md this belongs to: Capture / Compute / Render.

## Routes
Every new FastAPI route needed:
- `METHOD /path` — description — access level (public/authenticated)

If no new routes: state "No new routes".

## Database changes
Any new tables, columns, or constraints needed.
Always verify against `app/db/schema.sql` before writing this.
If none: state "No database changes".

## Pydantic models
- **Create:** list new models with their file path
- **Modify:** list existing models and what changes

## Templates
- **Create:** list new Jinja2 templates with their path
- **Modify:** list existing templates and what changes

## Engine / AI changes
Any changes to the deterministic engine (`app/engine/`) or AI subsystem
(`app/ai/`). Be explicit about what is computed vs what Gemini narrates.

## Files to change
Every file that will be modified.

## Files to create
Every new file that will be created.

## New dependencies
Any new pip packages to add to `requirements.txt`. If none: state "No new
dependencies".

## Rules for implementation
Specific constraints Claude must follow. Always include:
- Use `Decimal` for all money math — never float
- Tax rules must live in `app/engine/tax/rules.py`, keyed by assessment year
- Gemini writes narrative only; it must never compute or invent a rupee figure
- After Gemini responds, run the numeric-consistency check in `app/ai/validation.py`
- RLS is enforced on every table; derive `user_id` from the Supabase JWT only
- `service_role` key is used only in the background worker — never in templates
- Plotly figures are built server-side, serialized with `pio.to_json`, hydrated
  client-side with `Plotly.newPlot` — no iframes or static images
- All templates extend `app/templates/base.html`

## Definition of done
A specific testable checklist. Each item must be verifiable by running the app
or the test suite (`tests/`).
---

## Step 8 — Save the spec
Save to: `.claude/specs/<step_number>-<feature_slug>.md`

## Step 9 — Report to the user
Print a short summary in this exact format:
```
Branch:    <branch_name>
Spec file: .claude/specs/<step_number>-<feature_slug>.md
Title:     <feature_title>
```

Then tell the user:
"Review the spec at `.claude/specs/<step_number>-<feature_slug>.md`
then enter Plan Mode with Shift+Tab twice to begin implementation."

Do not print the full spec in chat unless explicitly asked.
