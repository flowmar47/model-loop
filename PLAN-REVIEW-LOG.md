# Plan Review Log: Enhance model-loop documentation and public skill repo

Started 2026-08-26 (local). Planner: Cursor. Reviewer: claude. Pin: model=fable effort=xhigh. MAX_ROUNDS=5.
Run directory: `.git/model-loop`
Skill: /Users/ohms/modelloop (also ~/.agents/skills/model-loop → this checkout)

Doctor (kickoff): agy 1.1.21 ok; cursor CLI dangling; claude 2.1.243 logged_in; codex 0.149.1 logged_in.

Phases 0–1 complete — plan locked with the user (scope = public-skill pass, no plugin; skill-dir script path; surgical SKILL.md; cosmetics accepted via escape hatch).

## Round 1 — claude (failed before verdict)

`rival.py start --bench claude --role review --model fable --effort xhigh` exited 1 after ~185s.

Session `4ec1cd0c-1418-49ec-99ab-8cdb6cb8cedd` assistant text: `API Error: Connection refused — a firewall or proxy may be blocking it (ConnectionRefused)`.

Cause (this machine): inherited `ANTHROPIC_BASE_URL=http://127.0.0.1:8787`; port 8787 is not listening (`curl` exit 7). No `--out` / `--state` written (adapter refuses to persist a failed round).

Retry: same start command with `ANTHROPIC_BASE_URL` and `OPENAI_BASE_URL` unset so fable hits first-party Claude (auth: claude.ai, max). Not a blind retry.

## Round 1 — claude (fable xhigh) — VERDICT: REVISE

Session `63c07ff3-4e30-490f-b1b2-2efd97dda073`. Out: `.git/model-loop/review-round-1.txt`.

Full critique:

Review complete. I read `PLAN.md`, the review log, `SKILL.md`, `README.md`, `adapters.md`, `CONTEXT-FORMAT.md`, and the already-implemented step-1 code in `scripts/rival.py` / `scripts/test_rival.py`, and verified the plan's flag assumptions against the installed CLIs. The plan's shape is good — scope is tight, out-of-scope is explicit, and several of its riskiest claims check out (`claude` has `--model`/`--effort`; `agy` has both; `codex exec resume` accepts `-m`, so pinned-model resume will not break). But the verification story has holes the plan's own Proof section would sail past.

**Confirmed flaws:**

1. **Doctor is blind to the new pin flags.** `REQUIRED_HELP` in `scripts/rival.py:33-60` was not extended with `--model` (all benches) or `--effort` (claude/agy), so the plan's proof — "doctor must show claude ok" — proves nothing about the feature step 1 exists to deliver; a CLI upgrade that drops or renames these flags passes doctor and fails at round time. **Fix:** add `--model` and (for claude/agy) `--effort` to `REQUIRED_HELP`.

2. **"Persist pins so resume keeps them" has zero test coverage.** All new tests exercise `build_argv` only; nothing tests that `run_round` writes `model`/`effort` into state or that `resume` replays them (`scripts/rival.py:398-399, 467-468`). The proof command passes while the named requirement is unverified. **Fix:** add a test that stubs `run_command`, runs start-then-resume, and asserts the resume argv contains the stored pins.

3. **Effort values are not validated, and the fail-loud claim is unverified.** `agy --help` enumerates `low|medium|high`; `apply_pins` forwards any string. The plan asserts "passing xhigh to agy should fail loud" but no one has confirmed agy exits non-zero rather than ignoring it. **Fix:** either validate effort per bench in `apply_pins` or run `agy -p --effort xhigh` once, confirm non-zero exit, and cite it in `adapters.md`.

4. **Wrong premise on codex effort.** The plan treats codex as "no effort flag," but codex supports reasoning effort via `-c model_reasoning_effort=...` (config-override mechanism confirmed in `codex exec resume --help`; the exact key is unverified training knowledge). Rejecting `--effort` for codex is a silent capability downgrade unless stated. **Fix:** wire `-c model_reasoning_effort="<effort>"` for codex, or document in `adapters.md` why effort is deliberately unsupported there.

5. **`$SKILL_DIR` is a copy-paste trap.** A fenced command `python3 "$SKILL_DIR/scripts/rival.py"` will be executed verbatim by literal-minded agents with the variable unset, expanding to `/scripts/rival.py`. **Fix:** SKILL.md should instruct the agent to substitute the actual directory containing the SKILL.md it loaded (prose rule plus a resolved-path example), not show an env-var-shaped command.

6. **Cursor `--model` is undocumentable as verified.** The Cursor CLI is a dangling symlink on this machine (plan's own risk note), so `adapters.md` would assert a pass-through flag never tested against any installed binary — exactly the staleness disease step 5 is curing. **Fix:** label the cursor pin row "unverified against installed CLI; confirm with `agent --help`."

7. **Observability gap on the pin itself.** `run_round`'s stdout JSON (`scripts/rival.py:477-490`) omits model/effort, so a round's output carries no evidence of which model actually reviewed — the log's "this review is actually fable xhigh" claim rests on nothing inspectable, and a silent `--model` override on resume changes the reviewer identity with no trace. **Fix:** include effective `model`/`effort` in the printed round JSON.

8. **README tunables table recreates the drift problem.** Duplicating SKILL.md's tunables in README makes two tables that will diverge, same as the stale pins being removed from `adapters.md`. **Fix:** README names only `reviewer`/`builder`/`inspect` and links SKILL.md for the full table.

Refuted during review (no change needed): `codex exec resume` rejecting `-m` (it accepts it), and the existence of `--model`/`--effort` on claude and agy (both present).

VERDICT: REVISE

### Arbitration (planner)

- **1 accept** — `REQUIRED_HELP` must include `--model` (all) and `--effort` (agy/claude).
- **2 accept** — stub `run_command`, start then resume, assert stored pins in resume argv.
- **3 accept as adapter validation** — do not live-call `agy -p --effort xhigh`. Validate enums from this session's `--help`: agy `low|medium|high`; claude `low|medium|high|xhigh|max`. Unknown → `RivalError`.
- **4 reject wiring; accept docs** — `codex exec --help` this session has `-m`/`--model` and generic `-c`, no `--effort` and no `model_reasoning_effort`. Exact key was marked unverified by the reviewer. Keep `--effort` illegal on codex; adapters.md states why.
- **5 accept** — SKILL.md: substitute the loaded skill directory; resolved-path example; no fenced `$SKILL_DIR` command.
- **6 accept** — label cursor `--model` unverified.
- **7 accept** — round JSON includes `model` and `effort`.
- **8 accept** — README names only reviewer/builder/inspect; full table stays in SKILL.md.

`PLAN.md` revised. Round 2 resumes the same session.

## Round 2 — claude (fable xhigh) — VERDICT: APPROVED

Session `63c07ff3-4e30-490f-b1b2-2efd97dda073`. Out: `.git/model-loop/review-round-2.txt`.

Full critique in that file. Non-blocking (fold during implementation, not a new round):

1. Proof must require every fenced `rival.py` invocation to use a substitute-skill-dir marker, not only a hardcoded `~/.agents/...` example.
2. Resume-pin test must stub `resolve_binary` (or drop a fake binary on PATH) so ubuntu-latest CI works.
3. Effort `RivalError` cites the snapshot and tells the reader to update the enum if `--help` lists a new value; adapters.md records the snapshot date.
4. Unit-test `"--effort" in REQUIRED_HELP["claude"]` (doctor does not print the required set).
5. adapters.md includes the `env -u ANTHROPIC_BASE_URL -u OPENAI_BASE_URL` remedy.
6. README hedges: read-only via each CLI's plan/sandbox mode.
7. **Rejected:** adding `antigravity` topic — topics were locked in Phase 1 as `agent-skills`, `claude-code`, `codex-cli`, `cursor`.

Resolution: APPROVED after 2 review rounds (plus one infra failure before a verdict). User: this session builds.

## Act 3 — Build

BASE_COMMIT: `5169c890598562c277af1630176e474db8a6061a`
Builder: this Cursor session (not a spawned CLI).

Implemented: rival.py pins (REQUIRED_HELP, effort enums, round JSON, resume-pin test), README, surgical SKILL.md, CONTEXT.md, adapters.md, `.github/workflows/test.yml`, GitHub topics `agent-skills`, `claude-code`, `codex-cli`, `cursor` (homepage empty). LICENSE unchanged.

Proof (this session, after last Python edit):

```
python3 scripts/test_rival.py -v
Ran 23 tests in 0.004s
OK
```

`python3 scripts/rival.py doctor --bench claude` → `"ok": true`, `missing_flags: []`, claude 2.1.243 logged_in.

Non-blocking Round 2 items 1–6 folded in. Topic 7 still rejected.

## Post-build inspection — claude (fable xhigh), 2 rounds (cap)

Inspector ≠ builder. Fresh session `58b18ea2-2fd9-4394-916e-7ab1883f30c6` (not the Phase 2 thread).

Round 1 (`.git/model-loop/inspect-round-1.txt`):
1. **accept** — tests for codex `-m` and cursor `--model`.
2. **accept** — reject empty-string `--model`/`--effort`.
3. **accept** — adapters.md `env -u` example uses clone-default path, not `<skill-dir>`.
4. **accept** — `--effort` help lists both enums.
5. **reject** — non-string pins in a hand-edited state file are not a caller path (argparse yields `str | None`).

Round 2 (`.git/model-loop/inspect-round-2.txt`):
1. **accept** — `coerce_pin` now returns `value.strip()`; whitespace-only still errors.
2. **reject** — "omit the flag" on resume correctly replays the stored pin; empty string must not silently unpin.
3. **accept** — `start --model ""` returns 1 with no spawn (`test_empty_model_flag_fails_before_spawn`).

No third inspect (cap). Proof after last edit: `python3 scripts/test_rival.py` → 28 tests OK.


