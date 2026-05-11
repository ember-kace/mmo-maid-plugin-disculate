# Changelog

All notable changes to Disculate are documented here. Format adapted from [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [SemVer](https://semver.org/).

Per the GSD handoff's semver policy ("major for breaking changes"), the first public release ships as **0.1.0**. The version reaches 1.0.0 after the post-deploy SDK assumption probe (see [SDK-ASSUMPTIONS.md](SDK-ASSUMPTIONS.md)) confirms or supersedes every defensive try/except.

## [0.2.0] — 2026-05-11

Post-launch tailored audit fixes. No KV schema change; existing config entries continue to work.

Includes the semver realignment described above (pre-release manifest was tagged 1.0.0; renamed to 0.1.0 retroactively and this revision ships as 0.2.0). Test count: 175 → 192.

### Added
- Reason codes `WANT_POWER`, `WANT_MOD`, `WANT_COMPARE`, `WANT_BITWISE`, `WANT_EXPLICIT_MULT` — emitted in place of generic `UNSUPPORTED_NODE` / `PARSE_ERROR` when the user makes a common calculator-keyboard mistake (e.g. `2^3`, `5 % 3`, `1 < 2`, `1 & 2`, `2(3)`, `2pi`). Each comes with a specific hint pointing at the supported syntax.
- Reason code `OK` — replaces the previous magic-string "ok" tag value on the `calc_eval` metric. Now centralized in [lib/reasons.py](lib/reasons.py).
- `FunctionSpec` registry in [lib/functions.py](lib/functions.py) — adding a math function is now a single new entry. HELP_TEXT auto-generates from this registry plus `CONSTANTS`, plus `MAX_INPUT_LEN` and `EVAL_BUDGET_SECONDS` from their canonical modules.
- New tests: mod sign consistency across int/float operands; post-binop nan/inf catch; format boundary at `1e-7`; cooldown fallback when ephemeral subsystem raises.

### Changed
- `mod(a, b)` always follows sign-of-divisor convention regardless of operand types. Previously `mod(-7, 3)` returned 2 (Python `%`) and `mod(-7.0, 3)` returned -1.0 (`math.fmod`).
- Percent regex tightened with negative lookahead `(?!\s*[\w.\(])`. `5%2`, `5%pi`, and `5%(3+1)` no longer get rewritten as percent — they now surface the `WANT_MOD` hint instead of confusing `PARSE_ERROR`. Trailing `%` (`50%`, `100% + 5`, `200 * 5%`) is unchanged.
- nan/inf result check centralized in `evaluator._eval`. Previously only Pow checked its result; now every operator and function call goes through the same finite guard, catching cases like `1e308 + 1e308` → `+inf`.
- Format boundary fixed: `1e-7` at precision 6 now renders as scientific notation, not `"0"`. Previously the boundary was `10 ** (-precision - 1)`, an off-by-one that lost values at exactly the precision floor.
- Result embed footer (angle mode) now appears only when the expression actually used a trig function. Non-trig `/calc` results show no footer.
- HELP_TEXT generated from the FUNCTIONS registry so it can't drift when functions are added. `MAX_INPUT_LEN` and `EVAL_BUDGET_SECONDS` interpolated from their source modules.
- `UNSUPPORTED_NAME` hint now mentions "case-sensitive" so `Pi` users get a clearer pointer at `pi`.
- `_safe_pow` constants `_POW_INT_EXP_LIMIT = 64`, `_POW_INT_BASE_LIMIT = 1_000_000` extracted with a rationale comment. No behavior change.
- `config_change` metric tag schema unified — every path emits both `result` and `field`. Previously the not-admin and invalid-config paths used different keys than the success path.

### Fixed
- T1-01: `1e1000` no longer evaluates to `+inf`. ast.parse produces `Constant(value=inf)` for overflowing literals; the validator now rejects non-finite float literals with reason `OVERFLOW`.
- T1-02: `1e308 + 1e308`, `0 * 1e308 * 10`, etc. no longer leak `NaN` / `+inf` to users. The centralized finite check catches them.
- T1-03: `mod(-7, 3)` and `mod(-7.0, 3)` now return the same answer (2 and 2.0).
- T1-04: `5 % 3` → "Use mod(a, b) for modulo. Trailing `%` means percent (e.g. `50%` = 0.5)." instead of `PARSE_ERROR`.
- T1-05: `2 ^ 3` → "Use ** for power, not ^." `1 < 2` → "Comparisons aren't supported." `1 & 2` → "Bitwise operators aren't supported."
- T2-01: `1e-7` at default precision renders as `1e-7`, not `0`.
- T2-02: Footer noise on `/calc 2+2` removed.
- T3-02: `2(3)`, `2pi`, `3 (5)`, `2 pi` → "Use `*` for multiplication, e.g. `2 * (3)` or `2 * pi`."

## [0.1.0] — 2026-05-11

Initial public release.

### Added
- `/calc expression:<text> [ephemeral:<bool>]` — public slash command. Evaluates a math expression and posts the result as an embed. Default response is visible to the channel; `ephemeral:true` hides it from everyone but the invoker.
- `/calc-config` — admin-only (MANAGE_GUILD). Sets per-server defaults for decimal precision (0–10), angle mode (`rad`/`deg`), and scientific-notation threshold (1–20).
- `/calc-help` — lists supported operators, functions, and constants.
- Operators: `+`, `-`, `*`, `/`, `//`, `**`, unary `+`/`-`, parentheses.
- Trailing-`%` percent sugar (`50%` → `0.5`).
- Functions: `abs`, `round`, `floor`, `ceil`, `min`, `max`, `mod`, `pow`, `sqrt`, `exp`, `log`, `log10`, `log2`, `ln`, `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `atan2`, `sinh`, `cosh`, `tanh`.
- Constants: `pi`, `e`, `tau`.
- Per-user cooldown (2 seconds, ephemeral-backed).
- Defense-in-depth DoS guards: 120-char input cap, 32-deep AST, 200-node AST, pow operand guard, 200 ms wall-clock budget.
- Three bounded-cardinality metrics: `calc_eval`, `calc_latency_ms`, `config_change`.
- Documentation: CLAUDE.md, AUDIT-REPORT.md, SDK-ASSUMPTIONS.md, RUNBOOK.md, ARCHITECTURE.md.
- Build tooling: `tools/build_bundle.py` (deterministic zip with allowlist guard), `tools/run_audit.py` (manifest, imports, no_eval, todo_markers, plugin_run, pytest, bundle gates).
- 175 unit / handler / failure-injection / adversarial tests.

### Security
- No `eval`, `exec`, or `compile` is ever called on user input. Parser uses `ast.parse` + manual AST walker with strict node allowlist. Audit gate enforces.
- Every user-visible string is normalized (NFKC), stripped of bidi/control characters, scrubbed of markdown and `@everyone`/`@here` patterns, and clipped to embed limits.
- All responses set `allowed_mentions: {"parse": []}` to defeat mention injection.
