# model-loop

Cross-harness plan hardening. The agent you invoke this skill **in** is the planner. A *different* CLI — AGY, Cursor CLI (`agent`), Codex, or Claude Code — attacks the locked plan read-only. Then the models swap: one builds, the other inspects. Whoever made the thing never grades the thing.

Adapted from [claudex-loop](https://github.com/chaseai-yt/claudex-loop) (MIT).

## Install

Canonical copy (any harness that reads `~/.agents/skills`):

```bash
git clone git@github.com:flowmar47/model-loop.git ~/.agents/skills/model-loop
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
