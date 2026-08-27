# Bench adapters

`scripts/rival.py` is the source of truth. This file exists so an agent can recover
when the script is missing, and so a human can see what will run. Flags below were
verified against the CLIs installed when this skill was authored (agy 1.1.19,
Cursor CLI docs 2026-08, Claude Code 2.1.243, Codex 0.149.1). Re-run `rival.py doctor`
after upgrades; do not trust this page over `--help`.

Never pin `--model` / `-m` unless the user asked. Never resume with `--continue` or
`--last`. Always keep an explicit session id in the state file.

Timeouts: 10 minutes per round. Codex `exec` reads stdin *in addition to* a prompt
argument — under a non-TTY driver that hangs forever unless stdin is closed
(`< /dev/null` / `stdin=DEVNULL`).

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
codex exec -s read-only --json -o /tmp/verdict.txt "$(cat prompt.txt)" \
  < /dev/null
# resume (resume rejects -s; force read-only via -c):
codex exec resume "$ID" -c sandbox_mode="read-only" --json \
  -o /tmp/verdict.txt "$(cat prompt.txt)" < /dev/null
```

Session id: JSONL line `{"type":"thread.started","thread_id":"..."}`.
Last message: `-o` file. `--yolo` is **not** a current `codex exec` flag
(0.149.1); do not use it.

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
  -o /tmp/build.txt - < prompt.txt
# resume:
codex exec resume "$ID" --dangerously-bypass-approvals-and-sandbox --json \
  -o /tmp/build.txt - < prompt.txt
```

Run from the repo root (`resume` has no `-C`).

## Doctor checks

`rival.py doctor` confirms each binary exists, `--help` contains the flags the
adapter needs, and (where cheap) that the CLI is authenticated. A dangling
`~/.local/bin/agent` symlink is a Cursor CLI miss — reinstall with
`curl https://cursor.com/install -fsS | bash` only if the user asks.
