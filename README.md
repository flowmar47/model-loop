# model-loop

Cross-harness plan hardening. The agent you invoke this skill **in** is the planner. A *different* CLI — AGY, Cursor CLI (`agent`), Codex, or Claude Code — attacks the locked plan. Then the models swap: one builds, the other inspects. Whoever made the thing never grades the thing.

Adapted from [claudex-loop](https://github.com/chaseai-yt/claudex-loop) (MIT).

## Install

Clone this repo as a skill directory (HTTPS or SSH):

```bash
git clone https://github.com/flowmar47/model-loop.git ~/.agents/skills/model-loop
# or: git clone git@github.com:flowmar47/model-loop.git ~/.agents/skills/model-loop
```

Then symlink into the harness you use:

```bash
ln -sfn ~/.agents/skills/model-loop ~/.cursor/skills/model-loop
ln -sfn ~/.agents/skills/model-loop ~/.claude/skills/model-loop
ln -sfn ~/.agents/skills/model-loop ~/.codex/skills/model-loop
ln -sfn ~/.agents/skills/model-loop ~/.pi/agent/skills/model-loop
ln -sfn ~/.agents/skills/model-loop ~/.gemini/skills/model-loop   # AGY
```

## Use

In Cursor, Claude Code, Codex, Pi, or AGY:

```
/model-loop
/model-loop reviewer=codex
```

You are the planner. Pick a rival that is not this harness. No code is written until you sign off the converged `PLAN.md`.

## Phases

| Phase | Who | What |
|-------|-----|------|
| 0 Recon | This session | Scout the repo (or research if greenfield); assumptions ledger |
| 1 Interrogate | You ↔ this session | Lock load-bearing decisions; write `PLAN.md` |
| 2 Review | Rival CLI | Read-only attack on the plan; this session arbitrates |
| 3 Build (optional) | This session or a spawned CLI | Implement; a *different* bench inspects |

## Safety

Review and inspect are read-only via each CLI's plan/sandbox mode. Build is write. The spawned builder never commits.

## Tunables

Pass on the slash command, e.g. `/model-loop reviewer=codex inspect=off`.

| Var | Default | Meaning |
|-----|---------|---------|
| `reviewer` | ask | `agy` / `cursor` / `claude` / `codex` |
| `builder` | ask at Phase 3 | `this` / `agy` / `cursor` / `claude` / `codex` |
| `inspect` | `on` | `off` = skip post-build inspection (logged) |

The rest (`MAX_ROUNDS`, research depth, file names, …) live in [SKILL.md](SKILL.md).

Doctor (checks rival CLIs; does not call models):

```bash
python3 ~/.agents/skills/model-loop/scripts/rival.py doctor
```

## Rivals

| Alias    | Binary                         |
|----------|--------------------------------|
| `agy`    | `agy`                          |
| `cursor` | `agent` (not the `cursor` IDE) |
| `claude` | `claude`                       |
| `codex`  | `codex`                        |

## License

MIT. Protocol portions adapted from claudex-loop, © Chase AI.
