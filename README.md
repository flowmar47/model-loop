# model-loop

Cross-harness plan hardening. The agent you invoke this skill **in** is the planner. A *different* CLI — AGY, Cursor CLI (`agent`), Codex, or Claude Code — attacks the locked plan. Then the models swap: one builds, the other inspects. Whoever made the thing never grades the thing.

Adapted from [claudex-loop](https://github.com/chaseai-yt/claudex-loop) (MIT).

## Install

Recommended shared installation across supported agent harnesses:

```bash
npx skills add https://github.com/flowmar47/model-loop --global --all
```

For a manual fallback, clone once and link only the harnesses you use:

```bash
git clone https://github.com/flowmar47/model-loop.git ~/.agents/skills/model-loop
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

Read-only controls prevent a rival from editing files; they do not prevent data transmission. The selected external provider can receive `PLAN.md` and any repository material its rival CLI reads. Model Loop discloses this boundary with reviewer selection before the first rival round.

## Tunables

Pass on the slash command, e.g. `/model-loop reviewer=codex inspect=off`.

| Var | Default | Meaning |
|-----|---------|---------|
| `reviewer` | ask | `agy` / `cursor` / `claude` / `codex` |
| `builder` | ask at Phase 3 | `this` / `agy` / `cursor` / `claude` / `codex` |
| `inspect` | `on` | `off` = skip post-build inspection (logged) |

The rest (`MAX_ROUNDS`, research depth, file names, …) live in [SKILL.md](SKILL.md).

Doctor checks required flags and each CLI's cheap authentication probe; it does not call a model:

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
