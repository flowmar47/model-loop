# Plan: Enhance model-loop documentation and public skill repo
_Locked via model-loop — Cursor + Ohms. Reviewer: claude (`fable`, effort `xhigh`). Round 1 REVISE incorporated._

## Goal
A stranger can clone https://github.com/flowmar47/model-loop, install it as a skill directory, and run `/model-loop` without this chat. An agent following `SKILL.md` can find `scripts/rival.py` and pin `--model` / `--effort`. The four-phase protocol does not change.

## Approach
1. **`rival.py` pins (already started; finish before docs land):** `start|resume --model` / `--effort`. Pass-through: `claude`/`agy` get `--model` and `--effort`; `cursor` gets `--model` only; `codex` gets `-m` only. Persist pins in session state so resume replays them. Also in this step (Round 1):
   - Add `--model` to `REQUIRED_HELP` for every bench; add `--effort` for `agy` and `claude` only.
   - Validate effort strings in `apply_pins`: agy `low|medium|high`; claude `low|medium|high|xhigh|max` (from installed `--help` 2026-08-26). Unknown values raise `RivalError` (so `xhigh` on agy fails in the adapter, not as a silent CLI ignore).
   - Print effective `model` and `effort` on the round JSON stdout.
   - Tests: existing `build_argv` pin tests; a start-then-resume test that stubs `run_command` and asserts resume argv still carries stored pins; tests that agy rejects `xhigh` and that cursor/codex still reject `--effort`.
2. **README.md** — Human entry. Four-phase table, safety (review/inspect read-only; build is write), “invoking harness is the planner,” HTTPS **and** SSH clone into `~/.agents/skills/model-loop`, then per-harness symlinks. Name only `reviewer` / `builder` / `inspect` and point at `SKILL.md` for the full tunables table — do not duplicate it. Do not copy claudex-loop prose.
3. **SKILL.md (surgical):** Tell the agent to run `python3 <skill-dir>/scripts/rival.py` where `<skill-dir>` is the directory of the `SKILL.md` it loaded. Show a resolved-path example (`python3 ~/.agents/skills/model-loop/scripts/rival.py …`), not a fenced `$SKILL_DIR` command that a literal agent executes with the variable unset. Document `--model` / `--effort`. Link `CONTEXT.md`. Do not retell phases, change hard rules, or rewrite the description triggers. `~/.agents/skills/model-loop` stays the README clone default only.
4. **CONTEXT.md** — Glossary only. Terms: planner, rival, bench, harness, skill directory. Format: `CONTEXT-FORMAT.md`.
5. **adapters.md** — Remove stale version pins. `rival.py doctor` and `--help` beat the page. Document model/effort pass-through, including: cursor `--model` is **unverified against an installed binary** (dangling symlink on the author machine — confirm with `agent --help`); `--effort` is deliberately unsupported on cursor and codex because those CLIs do not expose `--effort` in `--help` (codex has generic `-c`, not an effort flag — do not invent `model_reasoning_effort`). Note that spawned CLIs inherit the planner env (a dead `ANTHROPIC_BASE_URL` fails claude).
6. **CI** — `.github/workflows/test.yml`: on push and pull_request, ubuntu-latest, `python3 scripts/test_rival.py`. No extra linters.
7. **GitHub listing** — Topics: `agent-skills`, `claude-code`, `codex-cli`, `cursor`. No homepage URL.
8. **LICENSE** — Unchanged.

## Key decisions & tradeoffs
- No Claude marketplace plugin this round (`skills/model-loop/` nest would break clone-as-skill-root).
- Skill directory = folder of this `SKILL.md`, not cwd and not a hardcoded home path.
- SKILL.md surgical only — protocol stays.
- `rival.py` pins are first-class (user-requested; also needed for this review).
- Codex `--effort` stays rejected. Wiring an undocumented `-c` key would be an unverified API. Document the refusal.
- CI is tests only.
- README does not own the tunables table.

## Toolchain
- `writing-great-skills` — constrain SKILL.md edits (no protocol rewrite, progressive disclosure).
- `documentation-templates` — README structure only; do not invent a new template language.
- `create-skill` — SKILL.md still has name + description; description stays ≤1024 chars.

## Assumptions
Confirmed ledger (Phase 0) plus web recon: public skills are a directory with `SKILL.md` at the root; Claude plugin layout is a different product; `${CLAUDE_SKILL_DIR}` is Claude-only so must not be the sole path rule.

Round 1 CLI checks (this machine, 2026-08-26): `claude --effort` = `low, medium, high, xhigh, max`; `agy --effort` = `low|medium|high`; `codex exec --help` has `-m`/`--model` and generic `-c`, no `--effort`. Cursor CLI (`agent`) is still a dangling symlink.

## Risks / open questions
- GitHub topics require `gh repo edit --add-topic` (API), not a file in git.
- Cursor `--model` pass-through remains unverified until someone with a working `agent` binary runs `--help`.
- Planner env (e.g. `ANTHROPIC_BASE_URL=http://127.0.0.1:8787` with nothing listening) can fail a claude round before any plan critique exists.

## Out of scope
- Protocol rewrite, fifth rival, marketplace plugin, homepage, extra linters, rewriting LICENSE.
- Codex reasoning-effort via `-c` (unverified key; rejected in Round 1).

## Proof
From the skill / repo root:

```bash
python3 scripts/test_rival.py
python3 scripts/rival.py doctor --bench claude
```

Doctor must show claude `ok` and `--effort` must be among the flags it requires for claude. Tests must pass, including the resume-replays-pins stub test and agy-rejects-`xhigh`. README must include HTTPS clone, phases, the planner rule, and must **not** contain the full SKILL.md tunables table. `SKILL.md` must tell the agent to substitute the skill directory (resolved-path example present) and must not present `$SKILL_DIR` as a command to run unchanged. `CONTEXT.md` exists and defines planner, rival, bench, harness, skill directory. A successful `rival.py start|resume` JSON object includes `model` and `effort` keys.
