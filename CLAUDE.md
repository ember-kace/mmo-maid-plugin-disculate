# CLAUDE.md — Disculate handoff

## TL;DR

- **No `eval`, `exec`, or `compile`** on user input. Ever. The parser uses `ast.parse(mode="eval")` and a manual AST walker. Adding any of those calls to `lib/` or `plugin.py` is blocked by `tools/run_audit.py`.
- **`plugin.run()` must stay at the bottom of `plugin.py`.** It's the SDK handshake — without it the worker exits before connecting. The audit's `plugin_run` gate enforces this.
- Sandbox is `--network none`, empty env, 64 MB RAM, 0.25 vCPU. The plugin makes no outbound HTTP and writes nothing to disk.
- Every external SDK call is wrapped: cooldown, metrics, respond, and KV all fail open. Look for `try/except` around `ctx.*` calls.
- Three slash commands: `/calc`, `/calc-config` (admin), `/calc-help`. All replies set `allowed_mentions: {"parse": []}`.

## What the plugin does

In-Discord calculator. `/calc expression:<text>` parses the expression with stdlib `ast.parse`, validates every node against an allowlist, walks the tree to compute a result, and posts an embed. `/calc-config` lets server admins set decimal precision, angle mode (radians/degrees), and scientific-notation threshold. `/calc-help` lists supported syntax.

## Architecture map (reading order)

| File | Purpose |
|---|---|
| `manifest.json` | Plugin id, version, capability declarations, slash command schemas. |
| `plugin.py` | Handlers for `calc`, `calc-config`, `calc-help`, plus `on_ready`. Wires the SDK ctx into the library modules. |
| `lib/reasons.py` | Reason code constants + `hint_for()` — every failure path returns one of these. |
| `lib/logctx.py` | `request_id` ContextVar seeded at handler entry. `log_info` / `log_warn` / `log_error` carry it automatically. |
| `lib/config.py` | KV-backed per-server config. Schema-versioned via `CONFIG_SCHEMA_V`; reader rejects mismatches. |
| `lib/functions.py` | Function and constant allowlist. Trig functions are wrapped for angle-mode switching. Pow has a separate guard in the evaluator. |
| `lib/parser.py` | `clean_expression` (NFKC + length + control-char reject) → `preprocess_percent` → `ast.parse` → `_validate` (node allowlist + depth + count). |
| `lib/evaluator.py` | Walks the validated tree with a wall-clock budget. Pow routes very-large int operands through `math.pow` to clamp at float overflow. |
| `lib/format.py` | int preservation, thousands separators, trailing-zero trim, scientific notation when over threshold. |
| `lib/embed.py` | `safe_text` (markdown/mention scrub) + `clip` + `enforce_total_cap`. Builders for result / error / cooldown / config / help embeds. |

## KV schema cheatsheet

| Key | Shape | TTL | Notes |
|---|---|---|---|
| `config` | `{"v": 1, "precision": int, "angle_mode": "rad"\|"deg", "scientific_threshold": int, "updated_at": int}` | none (durable) | One entry per server. `v != 1` → reader returns defaults. Bump `CONFIG_SCHEMA_V` when shape changes. |

Ephemeral keys (Redis-backed, LRU-evicted, not durable):
| Key | Shape | TTL | Notes |
|---|---|---|---|
| `cd:calc:<user_id>` | cooldown record | 2s | Per-user `/calc` cooldown. Falls open on `cooldown_check` exception. |

## SDK ambiguities

See `SDK-ASSUMPTIONS.md` for the full list. Two notable ones:

1. `ctx.interaction.respond` is called with `embeds=[...]` and `allowed_mentions={...}`. The SDK doc shows only `content=` and `components=`; this code assumes Discord-standard embed shape passes through. Probe by triggering any `/calc` and confirming the embed renders.
2. `event["member"]["permissions"]` may be int or string depending on transport. `_is_admin()` handles both. Probe by running `/calc-config` from an admin account.

## Tests and conventions

- Run: `py -m pytest tests/ -q` from project root.
- Current count: 175 tests, all green.
- Layout: one `test_<module>.py` per `lib/` module, plus `test_handlers.py`, `test_stub_contract.py`, `test_failure_injection.py`, `test_adversarial.py`.
- `tests/conftest.py` stubs `mmo_maid_sdk` so the plugin imports without the real runtime. `test_stub_contract.py` locks the stub surface to what `plugin.py` actually uses.

## Build and bundle

- Build: `py tools/build_bundle.py` → writes `build/disculate.zip` (deterministic, mtime=0).
- Audit: `py tools/run_audit.py` runs all gates (manifest, imports, no_eval, todo_markers, plugin_run, pytest, bundle).
- Bundle includes only the explicit allowlist in `tools/build_bundle.py:INCLUDED_FILES`. Tests, tools, docs, `__pycache__`, dotfiles, and `*.md` are excluded by virtue of not being on the list.

## Things that look wrong but aren't

- **`5 % 3` returns `WANT_MOD` ("Use mod(a, b) for modulo. Trailing `%` means percent.") instead of evaluating.** Disculate uses trailing `%` for percent (e.g. `50% = 0.5`). The tightened percent regex `(?!\s*[\w.\(])` deliberately leaves digit-`%`-digit alone so `BinOp(Mod)` reaches the validator, which then emits the specific hint. Workaround for users: `mod(5, 3)`.
- **`1e1000` returns OVERFLOW, not "+inf".** Python's `ast.parse` evaluates the literal and produces `Constant(value=inf)`. The validator rejects non-finite float literals so they can't seed downstream nan/inf-propagating arithmetic (finding T1-01).
- **`bool` literals are rejected.** Python's `ast.parse` represents `True`/`False` as `Constant(value=True)`. Since `isinstance(True, int)` is True, an unguarded int check would accept them. `parser._validate` explicitly checks `isinstance(v, bool)` and rejects.
- **Trailing `\x1c`-`\x1f` are NOT rejected as control chars.** Python's `str.strip()` treats them as whitespace, so they get stripped before the category check. Mid-string instances are still rejected.
- **`2(3)` returns `WANT_EXPLICIT_MULT`, not `UNSUPPORTED_NODE`.** ast.parse accepts `2(3)` as `Call(func=Constant(2), args=[Constant(3)])` — calling a number as a function. The validator surfaces this with the explicit-multiplication hint rather than a generic "not allowed" error (finding T3-02).
- **`/calc 2+2` has no footer.** Footer (angle mode) is conditional on `uses_trig(tree)`. Non-trig results omit it to reduce visual noise (finding T2-02).
- **The percent preprocessor rewrites `-50%` correctly but not `(-50)%`.** The regex requires a digit/decimal start. `-50%` becomes `-(50/100)`. `(-50)%` keeps the `%` — accepted limitation; users can write `(-50)/100` or `-50%`.
- **Cooldown failure falls open.** If `ctx.ephemeral.cooldown_check` raises, the handler proceeds with eval rather than blocking. Infra failure shouldn't block the feature for marketplace-scale.
- **HELP_TEXT auto-generates.** Editing the string directly is a footgun — `_build_help_text()` in `lib/embed.py` runs at import time and derives content from `FUNCTIONS`, `CONSTANTS`, `MAX_INPUT_LEN`, and `EVAL_BUDGET_SECONDS`. To change wording, edit the format strings in `_build_help_text` (S1 + T3-06).
- **Version is 0.2.0, not 1.0.0.** The handoff's semver policy reserves major bumps for breaking changes; the inaugural release ships as 0.1.0 and v1.0.0 comes after the post-deploy SDK-assumption probe (S3).

## User preferences (Paul)

- Plan-first → Implement → Audit. Already done for v1; for changes, re-plan before coding.
- Terse with file:line citations. `lib/parser.py:60` beats "in the parser around line 60."
- No sycophancy. Acknowledge briefly, move to substance.
- Semver discipline. Patch = bug fix or data refresh. Minor = new operator/function. Major = breaking KV schema or removed feature.
- Multi-source signal where applicable — N/A for this plugin (no external sources).

## Common task recipes

### Add a new math function

1. Implement `_i_myfn(args, angle_mode)` in `lib/functions.py`. Ignore `angle_mode` unless the function is trig/inverse-trig. No need to call `_check_arity` — it's done centrally by `call_function`.
2. Add one entry to `FUNCTIONS`: `FunctionSpec("myfn", _i_myfn, <arity>, <category>, "myfn(x)")`. Categories: `CATEGORY_BASIC`, `CATEGORY_ROOTS_EXP_LOG`, `CATEGORY_TRIG`, `CATEGORY_HYPERBOLIC`.
3. If the function is a trig function whose argument is an angle, also add its name to `parser.TRIG_FUNCTION_NAMES` so the result embed footer renders correctly.
4. Add tests in `tests/test_functions.py` (happy path + domain errors).
5. Run `py tools/run_audit.py`. HELP_TEXT regenerates automatically.

### Add a new operator

1. Add the ast op class to `parser._ALLOWED_BINOPS` or `_ALLOWED_UNARYOPS`.
2. Add a branch in `evaluator._apply_binop`.
3. If the op has overflow / domain pitfalls, wrap that branch in try/except mapping to `EvalError(reason)`.
4. Tests + audit.

### Add a config field

1. Add field to `lib/config.py:DEFAULTS` and to `validate_updates` (range check + error message).
2. Add to the slash option schema in `manifest.json`.
3. Add to `cmd_calc_config` in `plugin.py` (extract option + pass to validate_updates).
4. Add to `embed.build_config_embed` rows.
5. **Bump `CONFIG_SCHEMA_V`** — old entries become invisible and re-populate with defaults.
6. Tests + audit.

### Bump version

1. Update `manifest.json:version` (semver).
2. Add an entry to `CHANGELOG.md` under the new version with Added/Changed/Fixed/Removed sections.
3. Rebuild bundle. Audit.

## Things deferred

| Item | Reason |
|---|---|
| Unit conversions (length/mass/temp/time/data) | User-confirmed deferral. Would add a unit registry and parser ambiguity (`m` = meter or milli-?). |
| Contextual percent (`100 + 10%` = 110) | Requires non-context-free parsing. Trailing-`%`-as-`/100` is enough for v1. |
| Variables / assignment (`x = 5`) | Would need durable per-user state and complicates the parser. |
| Expression history | Adds per-user KV; tiny utility for the cost. |
| Bitwise / hex / binary literals | Niche for a general-purpose calc. Defer with hex/binary. |
| Complex numbers, factorial, gamma | Factorial has unbounded DoS surface; complex is rarely asked for. |
| Localized decimal separators | Single-locale v1. Revisit when i18n becomes a real ask. |
| Comparison / boolean ops | Calculator, not a logic engine. |
| Slash autocomplete on `expression:` | Meaningless for freeform math input. |
| Dashboard widget | Needs usage data first to know what's worth showing. |
