# Bench adapters

`scripts/rival.py` is the source of truth. This file exists so an agent can recover
when the script is missing, and so a human can see what will run. Re-run
`rival.py doctor` and the CLI's own `--help` after upgrades; do not trust this
page over either.

Never pin `--model` / `-m` unless the user asked. Never resume with `--continue` or
`--last`. Always keep an explicit session id in the state file.

Timeouts: 10 minutes per round by default; `rival.py --timeout <seconds>` accepts 30 through
3600 seconds, and agy's `--print-timeout` is derived from it. Codex `exec` reads stdin *in addition to* a prompt
argument — under a non-TTY driver that hangs forever unless stdin is closed
(`< /dev/null` / `stdin=DEVNULL`).

Spawned CLIs inherit the planner's environment. A dead
`ANTHROPIC_BASE_URL=http://127.0.0.1:8787` (nothing listening) fails Claude with
connection refused. Retry cleanly:

```bash
env -u ANTHROPIC_BASE_URL -u OPENAI_BASE_URL python3 ~/.agents/skills/model-loop/scripts/rival.py …
```

## Model and effort pass-through

`rival.py start|resume` accept `--model` and `--effort`. They persist in the
session state so resume replays them.

Resume trusts the recorded bench and exact session id, then resolves that bench's current
executable. The stored `binary` value is provenance only and is never executed on resume.

| Bench    | Model flag | Effort |
|----------|------------|--------|
| `agy`    | `--model`  | `--effort` `low\|medium\|high` (snapshot 2026-08-26) |
| `claude` | `--model`  | `--effort` `low\|medium\|high\|xhigh\|max` (snapshot 2026-08-26) |
| `cursor` | `--model`  | none — `--effort` is rejected. **Unverified against an installed binary** (author machine has a dangling `agent` symlink). Confirm with `agent --help`. |
| `codex`  | `-m`       | none — `--effort` is rejected on purpose. `codex exec --help` has `-m`/`--model` and generic `-c`, not `--effort`. Do not invent `model_reasoning_effort`. |

Unknown effort values fail in the adapter (`RivalError`) with the snapshot date.
If your CLI's `--help` lists a new value, update the enum in `rival.py`.

## Review / inspect (read-only)

### agy

```bash
agy -p --mode plan --sandbox --output-format json --print-timeout 10m \
  "$(cat prompt.txt)"
# resume:
agy -p --conversation "$ID" --mode plan --sandbox --output-format json \
  --print-timeout 10m "$(cat prompt.txt)"
```

Session id: JSON `conversation_id`. Last message: JSON `response`.
Do **not** pass `--dangerously-skip-permissions`.

### cursor (Cursor CLI = `agent`, not the `cursor` IDE)

```bash
agent -p --mode ask --sandbox enabled --trust --output-format json \
  "$(cat prompt.txt)"
# resume:
agent -p --resume "$ID" --mode ask --sandbox enabled --trust \
  --output-format json "$(cat prompt.txt)"
```

Session id: JSON `session_id`. Last message: JSON `result`.
Do **not** pass `--force` / `--yolo` on review.

### claude

```bash
claude -p --permission-mode plan --output-format json \
  --disable-slash-commands --no-chrome "$(cat prompt.txt)"
# resume:
claude -p --resume "$ID" --permission-mode plan --output-format json \
  --disable-slash-commands --no-chrome "$(cat prompt.txt)"
```

Session id: JSON `session_id`. Last message: JSON `result`.
Do **not** pass `--dangerously-skip-permissions`.

### codex

```bash
codex exec -s read-only --json -o /tmp/review-round-1.last.txt "$(cat prompt.txt)" \
  < /dev/null
# resume (resume rejects -s; force read-only via -c):
codex exec resume "$ID" -c sandbox_mode="read-only" --json \
  -o /tmp/review-round-2.last.txt "$(cat prompt.txt)" < /dev/null
```

Session id: JSONL line `{"type":"thread.started","thread_id":"..."}`.
Last message: a fresh `-o` file for every round. Existing last-message artifacts are preserved,
and the runner requires a new `--out` path instead of deleting them. Do not use `--yolo` on
`codex exec`.

## Build (write)

### agy

```bash
agy -p --dangerously-skip-permissions --output-format json --print-timeout 10m \
  "$(cat prompt.txt)"
```

### cursor

```bash
agent -p --force --trust --output-format json "$(cat prompt.txt)"
```

### claude

```bash
claude -p --dangerously-skip-permissions --output-format json \
  "$(cat prompt.txt)"
```

### codex

```bash
codex exec --dangerously-bypass-approvals-and-sandbox --json \
  -o /tmp/build-round-1.last.txt - < prompt.txt
# resume:
codex exec resume "$ID" --dangerously-bypass-approvals-and-sandbox --json \
  -o /tmp/build-round-2.last.txt - < prompt.txt
```

Run from the repo root (`resume` has no `-C`).

## Doctor checks

`rival.py doctor` confirms each binary exists, `--help` contains the flags the
adapter needs (including `--model`, and `--effort` on agy/claude), and (where
cheap) that the CLI returns its known-good authenticated state. A bench is `ok` only when
both its flags and authentication probe pass. On a full sweep the top-level `ok` means
at least one bench is usable as a rival; pass `--bench <alias>` to gate on a
specific one (exits non-zero on failure). A dangling `~/.local/bin/agent` symlink is a
Cursor CLI miss. After user authorization, use Cursor's official installer if that rival is
needed; the runner never executes an installer.
