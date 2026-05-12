# Changelog

All notable changes to Disculate are documented here. Format adapted from [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [SemVer](https://semver.org/).

Per the GSD handoff's semver policy ("major for breaking changes"), the first public release ships as **0.1.0**. The version reaches 1.0.0 after the post-deploy SDK assumption probe (see [SDK-ASSUMPTIONS.md](SDK-ASSUMPTIONS.md)) confirms or supersedes every defensive try/except.

## [0.2.6] — 2026-05-12

User-visible UX fix surfaced by a real `/calc` in production: `1000 * (1 + 7%)  10` (missing operator between `)` and `10`) returned a generic `parse_error` with no helpful pointer. The v0.2.0 implicit-multiplication detection caught `2(3)` and `2pi` but didn't catch the symmetric `)<digit>` / `)<letter>` cases.

### Changed
- `lib/parser.py:_IMPLICIT_MULT_RE` extended from `\d\s*\(|\d\s*[A-Za-z_]` to `\d\s*\(|\d\s*[A-Za-z_]|\)\s*\d|\)\s*[A-Za-z_]`. Now also matches `(1+1) 10`, `(1+1)10`, `(1+1) pi`, and `(1+1)pi` — emitting `WANT_EXPLICIT_MULT` ("Use `*` for multiplication") instead of a generic `parse_error`.
- `tests/test_handlers.py:test_calc_implicit_multiplication_emits_want_explicit_mult` parametrize list grew from 3 → 6 cases.

### Verified
- SDK assumption **A11** (`embed.thumbnail` forwarded by SDK) — confirmed live by a `/calc-help` invocation in the test guild after v0.2.5 shipped. The Disculate avatar renders top-right; the negative case (error embed has no thumbnail) also confirmed in the same screenshot.

## [0.2.5] — 2026-05-12

Branded the result, help, and config-updated embeds. The Disculate maid-chibi avatar now appears in the top-right corner so cards immediately read as "Disculate" rather than as a generic embed.

### Added
- `assets/disculate.webp` (3.3 KB, 128×128) — the Disculate brand asset, committed to the repo. Sourced from `mmomaid-disculate-128x128.jpg`, converted to WebP via Pillow at quality 88. Lives under `assets/` which is **not** in the bundle allowlist — Discord fetches it directly from `raw.githubusercontent.com` at render time, so the binary doesn't bloat the plugin zip.
- `lib/embed.py:BRAND_THUMBNAIL_URL` — single source of truth for the brand image URL. Pinned to the `main` branch of this repo. Rebranding = replace the asset in place; the URL never changes, Discord re-fetches within ~minutes.
- `lib/embed.py:build_result_embed`, `build_help_embed`, and `build_config_embed` (on the "updated" path only) now include `thumbnail = {"url": BRAND_THUMBNAIL_URL}` in their output. Discord renders this as an ~80×80 image top-right of the embed.
- `manifest.json:icon_url` set to the same URL. Marketplace listing now carries the same visual identity as the in-Discord cards.
- Six new tests in `tests/test_handlers.py`: three positive (result / help / config-updated carry the thumbnail), three negative (error / cooldown / config-current do NOT).
- New SDK assumption A11 in `SDK-ASSUMPTIONS.md` — the SDK forwards `embed.thumbnail` to Discord. Probe by running `/calc 2+2` after install and confirming the avatar renders.

### Notes
- **Error, cooldown, and config-current embeds stay plain.** Red errors with a friendly maid in the corner felt off-tone; the cooldown notice is too small to absorb a thumbnail without looking lopsided; the read-only config view is informational rather than success.
- **Bundle size unchanged** — `assets/` deliberately stays outside `INCLUDED_FILES`. The marketplace zip is still 12 files / ~20 KB.
- Test count: 208 → 214.

## [0.2.4] — 2026-05-12

Adds a "Steps" field to the `/calc` result card that shows the worked-out math — every intermediate computation, in order — for any expression with two or more operations. Zero behaviour change for trivial expressions: `/calc 2+2` still shows just the header-hero result with no extra clutter.

### Added
- `lib/walker.py:BinOpStep` and `CallStep` — frozen-shape dataclasses representing one binary-operation or function-call step in an evaluation trace. Each entry carries the already-evaluated operands, operator symbol (or function name + args), and the computed result.
- `lib/walker.py:_OP_SYMBOLS` — map from `ast.Add` / `ast.Sub` / `ast.Mult` / `ast.Div` / `ast.FloorDiv` / `ast.Pow` to the user-syntax operator strings (`+`, `-`, `*`, `/`, `//`, `**`). Used when emitting BinOp trace entries so the displayed step matches the expression's notation.
- `lib/walker.py:run` and `lib/walker.py:run_safe` accept an optional `trace=[...]` parameter. When non-None, the walker appends a `BinOpStep` or `CallStep` for every successful BinOp / function call in inner-first order. UnaryOp / Constant / Name lookups don't emit steps (no meaningful computation to show).
- `lib/embed.py:format_steps` — renders a trace as a numbered string using `format_result` for value rendering, so the trace and the final answer use the same precision / scientific-threshold / thousands-separator settings. Capped at 30 lines with a `… (N more)` overflow line.
- `lib/embed.py:build_result_embed` accepts an optional `steps_text=...` parameter. When provided, adds a full-width `Steps` field below the result hero.

### Changed
- `plugin.py:cmd_calc` allocates a trace list, passes it to `run_safe`, and (smart-auto) renders the Steps field only when `len(trace) >= 2`. For `2+2`, `sqrt(2)`, or `min(3, 1, 4)` the trace has fewer than 2 entries and the Steps field is suppressed automatically.

### Notes
- **Faithful-to-AST rendering**: percent preprocessing happens before the walker runs, so `50%` shows in the trace as `50 / 100 = 0.5`, not `50% = 0.5`. Constants like `pi` are inlined as their numeric value at the moment they're read (no symbolic `pi → 3.141593` step is emitted). Both behaviours are intentional and documented in `CLAUDE.md`.
- The error path discards the trace — error embeds never carry a Steps field, even if some sub-steps completed before the failure.
- Test count: 197 → 208.

## [0.2.3] — 2026-05-12

Visual polish for `/calc` result and `/calc-help` embeds. Zero behavior change; same math, same SDK contract.

### Changed
- **Result embed (`/calc`)**: redesigned with the "header hero" layout. The expression sits small and monospaced on top, the result drops below as a large `##` markdown header. Discord renders embed-internal `##` as a true heading (post-2023 markdown), so the answer now visually dominates the card instead of competing with the expression for emphasis.
- **Help embed (`/calc-help`)**: refactored from a single dense description blob into a Discord-native field grid. Each function category (Basic, Roots / Exp / Log, Trig, Hyperbolic) is now its own inline embed field; the "Notes" caveats block is a full-width field below. Operators / Percent / Constants stay in the description as a compact intro. Footer condenses the limits and `/calc-config` pointer onto one line.
- **Error embed**: dropped the redundant `"Calc error"` title. The red color accent and `reason: <code>` footer already establish the embed as an error; the hint becomes the primary content. Also dropped the `"Input:"` label — the backticked expression speaks for itself.

### Added
- `tests/test_handlers.py:test_help_embed_uses_field_grid` — locks the new field-grid layout so future drift is caught (every category appears as an inline field; Notes is non-inline; categories carry the inline flag).

### Notes
- `_build_help_text()` (returned a single string) became `_build_help_payload()` (returns `{description, fields, footer_text}` so the embed assembler stays a thin formatter). All content still derives from `FUNCTIONS` + `CONSTANTS` + canonical limits (`parser.MAX_INPUT_LEN`, `walker.BUDGET_SECONDS`) — adding a math function still auto-populates the help.
- Color discipline unchanged: gold for success (result, config-updated), red for errors, slate for neutral notices (help, cooldown, config-current).
- Test count 196 → 197.

## [0.2.2] — 2026-05-12

Hotfix. Every `/calc` invocation in production returned "Expression is empty" — production logs revealed the SDK delivers slash command arguments at `event["command_options"]`, not `event["options"]` (the latter is what the SDK doc's example showed, and what we believed). `_user_id` was likewise reading `event["member"]["user"]["id"]` instead of the actual top-level `event["user_id"]`, so every cooldown was bucketed under `cd:calc:unknown`.

### Fixed
- `plugin._options` now reads `event["command_options"]` first, falling back to `event["options"]` and `event["data"]["options"]` for defensiveness. Confirms by regression test using a verbatim production-log payload.
- `plugin._user_id` reads top-level `event["user_id"]` first; nested shapes remain as fallbacks. Cooldowns now bucket per real user.
- `plugin._is_admin` reads top-level `event["permissions"]` first; nested `event["member"]["permissions"]` remains as a fallback.

### Changed
- `tests/fakectx.py:slash_event` and `make_event` updated to produce the observed SDK shape (flat `user_id` / `permissions` / `command_options`). Tests now validate the real-world shape, not the SDK doc's example.
- `SDK-ASSUMPTIONS.md`: A2, A5, and A7 marked WRONG and resolved. Added a lesson note that the SDK doc's examples are not reliable until empirically validated.

### Added
- `tests/test_handlers.py:test_calc_with_real_sdk_event_shape_evaluates_expression` locks the production payload shape against future drift.

## [0.2.1] — 2026-05-11

Refactor to satisfy the MMO Maid marketplace validator's substring-based pattern scanner. Zero behavior change for users; same 195-test suite passes; bundle size effectively unchanged.

The marketplace rejected v0.2.0 with `lib/evaluator.py: contains blocked pattern 'eval(' — this is not allowed in marketplace plugins`. Root cause: our recursive `_eval(...)` walker function and the `_record_eval(...)` metric helper both contained the literal substring `eval(`. The platform's validator does substring matching, not AST parsing, so it didn't distinguish our custom-named function from the dangerous builtin. Our local audit gate uses AST parsing and correctly never matched our identifiers — which is why the issue surfaced at upload rather than at audit.

### Changed
- Renamed `lib/evaluator.py` → `lib/walker.py` and every `eval`-rooted identifier inside it: `evaluate` → `run`, `_eval` → `_walk`, `evaluate_safe` → `run_safe`, `EvalError` → `WalkError`, `EVAL_BUDGET_SECONDS` → `BUDGET_SECONDS`.
- Renamed `plugin._record_eval` → `plugin._record_metric`. The metric **name** `"calc_eval"` is unchanged — it's a string literal without trailing `(`, so it doesn't trip the scanner, and keeping it preserves any downstream dashboard wiring.
- Rewrote `lib/parser.py` module docstring to describe the safety guarantee without using the literal substrings `eval()`/`exec()`/`compile()`.
- Renamed `tests/test_evaluator.py` → `tests/test_walker.py`; the test-only `_eval` helper → `_run`; `test_cooldown_check_raises_proceeds_with_eval` → `test_cooldown_check_raises_proceeds_with_calc`.
- `manifest.json` version bumped 0.2.0 → 0.2.1.

### Added
- `tools/run_audit.py:check_blocked_substrings` gate — substring scan over the bundle's `INCLUDED_FILES`, blocking `eval(`, `exec(`, and `__import__(`. Initially included `compile(`/`getattr(`/`globals(`/etc., but `compile(` false-positived on the ubiquitous `re.compile(...)` idiom; trimmed the list to the genuinely dangerous primitives that have no common idiomatic safe use. Reintroduction now fails locally via `py tools/run_audit.py` instead of at upload.
- The pre-existing AST-based gate is renamed `check_no_eval_compile_exec_ast` (was `check_no_eval_compile_exec`) and remains in place as a more-precise companion check. The two gates are complementary: the substring gate mirrors the marketplace; the AST gate catches calls the marketplace might miss.

### Lesson recorded for future audits
When the local audit and the platform's validator use different matching strategies, the local audit is at best an under-approximation of what the platform will accept. Mirror the platform's strategy when possible.

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
