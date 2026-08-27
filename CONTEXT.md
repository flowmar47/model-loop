# model-loop

Words this skill uses for who plans, who reviews, and where the files live.

## Terms

**Planner**
The invoking harness session. It interviews, writes `PLAN.md`, arbitrates, and (if asked) builds.
Not: "rival", "reviewer"

**Rival**
The spawned CLI that reviews or inspects. Must be a different bench from the planner.
Not: "planner"

**Bench**
One of the four spawnable CLIs: `agy`, `cursor` (`agent`), `claude`, `codex`.
Not: "harness" (Pi is a harness but not a bench)

**Harness**
The agent runtime that loaded this skill (Cursor, Claude Code, Codex, AGY, Pi, …).
Not: "bench"

**Skill directory**
The folder that contains this skill's `SKILL.md`. Scripts live at `<skill-dir>/scripts/`.
Not: "cwd", "repo root" (those may coincide after clone, but they are not the definition)
