# AUDIT-REPORT.md — Disculate

**Verdict:** PASS for v0.2.9 ship (post-Round-V second-order audit).

| Round | Verdict | Findings | Action |
|---|---|---|---|
| R1 — Correctness (v0.1.0) | PASS | 0 BLOCKER, 0 MAJOR, 2 MINOR (fixed) | Both fixed in-tree before v0.1.0. |
| R2 — Tailored, generic (v0.1.0) | PASS | 0 BLOCKER, 0 MAJOR, 3 MINOR (deferred or accepted) | All scope/design decisions documented. |
| R3 — Deep (v0.1.0) | PASS | 0 BLOCKER, 0 MAJOR, 5 INFO | Logged into SDK-ASSUMPTIONS.md and RUNBOOK.md. |
| T — Tailored, math-shape-specific (v0.2.0) | PASS | 0 BLOCKER, 3 MAJOR (fixed), 6 MINOR (mostly fixed), 4 NIT (mostly fixed), 3 ENHANCE (deferred) | All MAJORs and most MINORs fixed; ENHANCE items in backlog. |
| U — Marketplace-validator escape (v0.2.1) | PASS | 1 BLOCKER (fixed) + new audit gate | File + identifier rename + substring-based local gate to mirror the marketplace's scanner. |
| Post-launch UX hardening (v0.2.2 – v0.2.8) | PASS | 3 production-found bugs (fixed), 4 UX improvements shipped | See "Post-launch findings" section below. |
| **V — Second-order audit (v0.2.9)** | **PASS** | **2 MAJOR (fixed), 1 MINOR, 1 docs-only, 7 NIT cleanups, 5 test-coverage gaps closed** | See "Round V" section at the bottom. |

Audit gates: all 8 green (`py tools/run_audit.py`). Tests: 272/272 green (was 195 at v0.2.0; the +77 covers diagnostics, step trace, brand thumbnail, header-hero layout, SDK shape regression locks, and Round V coverage gaps).

---

## Round 1 — Correctness

### Finding R1-01 — `config_change` metric had inconsistent tag schema
**Severity:** MINOR
**Probe:** Compare tag keys recorded by the not-admin / invalid / success paths in `cmd_calc_config`.
**Original:** Not-admin path tagged `result=`, success path tagged `field=`. Aggregations would split awkwardly.
**Fix:** Introduced `_record_config(ctx, result, field="none")` helper; every path emits both `result` and `field` keys.
**Files:** `plugin.py:148-164`, `plugin.py:188-242`
**Status:** Fixed.

### Finding R1-02 — Trailing `\x1c`-`\x1f` was silently stripped, not rejected
**Severity:** MINOR
**Probe:** Send `/calc expression:"1+1\x1f"`. Python's `str.strip()` treats 0x1c-0x1f as whitespace, so `clean_expression` removed them before the category check.
**Original test asserted `INVALID_CHARS`; was actually getting None (parsed fine).**
**Fix:** Test updated to check mid-string control chars (which are not stripped). Trailing instances are safe — they're whitespace-like.
**Files:** `tests/test_adversarial.py:33-43`
**Status:** Fixed (test, not code — code behavior was correct, test expectation was wrong).

### R1 sweep also verified

- `plugin.run()` is the last executable line of `plugin.py`. Audit gate `plugin_run` enforces.
- `eval()`, `exec()`, `compile()` are not called anywhere in shipped code. Audit gate `no_eval` enforces (AST scan, not regex).
- All `ctx.kv.set` for non-config (cache/transient) state include `ttl_seconds=`. N/A — we have no cache writes.
- Every external SDK call is wrapped in try/except. Verified by grep.
- Every user-visible string passes through `safe_text + clip`. Verified by reading `lib/embed.py`.
- Admin gate via `MANAGE_GUILD` bit handles int and string `permissions`. Verified by `test_calc_admin_perms_int_form_accepted`.

---

## Round 2 — Tailored audit (compute-only plugin shape)

### Finding R2-01 — `_record_eval` records elapsed_ms as int, sub-ms calls show as 0
**Severity:** MINOR (deferred)
**Probe:** Run a fast eval (`1+1`); the `calc_latency_ms` metric records value=0.
**Decision:** Accept. The bucket tag (`<5`, `5-25`, `25-100`, `100-200`, `>200`) captures the resolution we care about; the raw value is a coarse aggregate. Switching to microseconds would require a new metric name to avoid mixing units.
**Files:** `plugin.py:62-67`

### Finding R2-02 — `/calc-config` race when two admins run simultaneously
**Severity:** MINOR (accepted)
**Probe:** Two admins run `/calc-config precision:2` and `/calc-config angle_mode:deg` within the same second. Read-modify-write means one update loses the other's change.
**Decision:** Accept. Config writes are rare and admin-gated; the value space is 3 fields. The handoff calls out KV is read-modify-write generally. Monotonic-write doesn't apply (each field is independent, not a cooldown that should only extend).
**Files:** `lib/config.py:79-89`

### Finding R2-03 — Help text is large but bundled in `embed.py`
**Severity:** NIT (accepted)
**Probe:** Search for `HELP_TEXT`.
**Decision:** Accept. Keeping it inline avoids a separate file just for a string. Total `build_help_embed` output is ~770 chars vs the 5800 cap — comfortable margin.
**Files:** `lib/embed.py:120-135`

### R2 sweep also verified

- **Scalability:** Adding a function = one entry in `_PLAIN_FUNCS` or `_TRIG_FUNCS` + a help-text line + tests. Adding a constant = one entry in `CONSTANTS`. Adding a config field = bump `CONFIG_SCHEMA_V` + 5 small edits per the CLAUDE.md recipe.
- **Code cleanup:** No technical-debt try/except — every `try` has a specific reason. `_ArityError` is intentionally private.
- **Storage:** KV key dimensionality is trivial (one key, `config`, no per-user variation). Schema version in value (`v` field). TTL omitted intentionally (config is durable).
- **Security:** Admin gate, input scrubbing, allowed_mentions, no-eval, depth/count/length/timeout DoS guards. All four DoS guards have tests.
- **Slash commands:** Manifest declares exactly the three commands `plugin.py` registers (asserted by `tests/test_smoke.py:test_manifest_parses`).

---

## Round 3 — Deep audit

### Finding R3-01 — SDK `ctx.interaction.respond` embed kwarg is undocumented
**Severity:** INFO (probe required)
**Probe:** Trigger `/calc 1+1`. If embed renders, confirmed. If TypeError or no render, fall back to `content=` with markdown body.
**Mitigation if wrong:** `_safe_respond` catches; user sees nothing but the failure is logged.
**Files:** `plugin.py:60-65`
**Status:** Logged in `SDK-ASSUMPTIONS.md`.

### Finding R3-02 — `event["member"]["permissions"]` type drift
**Severity:** INFO (probe required)
**Probe:** Run `/calc-config` as admin. If access granted, the int/string detection in `_is_admin` is robust. If denied, log the actual type.
**Mitigation:** `_is_admin` handles bool, int, and str.
**Files:** `plugin.py:49-58`
**Status:** Logged in `SDK-ASSUMPTIONS.md`.

### Finding R3-03 — `ephemeral.cooldown_check` return shape
**Severity:** INFO (probe required)
**Probe:** Run `/calc` twice in 2 seconds. Second should be blocked with "Slow down" embed. If not, dig into return shape (active flag? remaining_seconds field?).
**Mitigation:** `_check_cooldown` falls open on any unexpected shape — feature still works, cooldown just no-ops.
**Files:** `plugin.py:107-119`
**Status:** Logged in `SDK-ASSUMPTIONS.md`.

### Finding R3-04 — User id path differs guild vs DM
**Severity:** INFO (mitigated)
**Probe:** Test by triggering `/calc` from a guild and a DM (if DMs are supported for this plugin — they should not be).
**Mitigation:** `_user_id` tries `member.user.id`, then `user.id`, then falls back to `"unknown"`. The fallback bucket would aggregate all anonymous callers on one cooldown key, which is a theoretical DoS surface (one bad actor blocks all `unknown` calls for 2s). Acceptable for a marketplace plugin that's only enabled in guilds.
**Files:** `plugin.py:30-46`
**Status:** Documented.

### Finding R3-05 — Wall-clock budget granularity
**Severity:** INFO (accepted)
**Probe:** Time `run_safe` on the deepest legal expression (32 binops, 200 nodes max). p99 < 1ms on a developer laptop.
**Decision:** The budget check fires before each node visit, so a single very-slow node could run uncapped. All our allowed primitives (`math.*`, arithmetic) are O(1), so this never matters in practice. Documented for future maintainers.
**Files:** `lib/walker.py:38-46`

### R3 sweep also verified

- **Concurrency:** No shared mutable state in the plugin. KV writes (config) are read-modify-write with last-write-wins, documented in R2-02.
- **Adversarial input:** 25 parametrized cases in `tests/test_adversarial.py` cover bidi, control chars, NFKC lookalikes, markdown injection, mention injection, DoS attempts (length/depth/pow/timeout), and supply-chain-style payloads (lambdas, attribute access, f-strings).
- **Supply chain:** `requirements.txt` is empty. The only `import` from outside stdlib is `mmo_maid_sdk`.
- **Observability:** Three metrics — `calc_eval` (tags: `result`), `calc_latency_ms` (tags: `bucket`), `config_change` (tags: `result`, `field`). All tag values come from bounded enums. No user input ever becomes a tag value.
- **Operational:** See `RUNBOOK.md`.
- **Test quality:** 192 tests (v0.2.0), parametrized where the input space justifies it, failure-injection at every external call site, stub-contract test locks the SDK surface.
- **Sandbox edge cases:** No disk writes, no `os.environ`, no `sys.argv`, no raw sockets, no `--network` calls. Audit `imports` gate scans `ast.Import` and `ast.Attribute` to enforce.

---

## Round T — Math-shape tailored audit (v0.2.0)

Post-launch audit explicitly shaped to Disculate's actual attack surface — the parser + evaluator + formatter — rather than the generic R1-R3 cycle. Three MAJOR math-correctness bugs that would have surfaced on real use.

### T1-01 / T1-02 — NaN/inf leakage (MAJOR)
**Probe:** `/calc 1e1000` returned `+inf`. `/calc 1e308 + 1e308` produced `NaN`.
**Root cause:** Two-fold. (1) `ast.parse("1e1000")` produces `Constant(value=inf)` — the validator's `isinstance(v, (int, float))` check accepted it. (2) Only `Pow` checked its result for finite; every other binop returned raw float, propagating nan/inf downstream.
**Fix:** `parser._validate` rejects non-finite float literals with `OVERFLOW`. `walker._walk` centralized post-op finite check; the Pow-specific check is removed for a single source of truth.
**Tests:** `test_inf_literal_rejected_at_parse_time`, `test_inf_nan_results_caught_post_binop`.
**Files:** [lib/parser.py:114-117](lib/parser.py#L114-L117), [lib/walker.py:36-46](lib/walker.py#L36-L46)
**Status:** Fixed.

### T1-03 — `mod()` sign inconsistency across int/float (MAJOR)
**Probe:** `mod(-7, 3)` → 2 (Python `%`, sign-follows-divisor). `mod(-7.0, 3)` → -1.0 (`math.fmod`, sign-follows-dividend).
**Fix:** Always use `a - b * math.floor(a / b)` (or Python `%` for int/int — same result, but int return type preserved). All operand combinations now return sign-follows-divisor.
**Tests:** `test_mod_sign_consistent_for_negatives` (6 parametrized cases).
**Files:** [lib/functions.py:127-138](lib/functions.py#L127-L138)
**Status:** Fixed.

### T1-04 / T1-05 — `%` modulo collision + opaque operator-mistake errors (MAJOR)
**Probe:** `5 % 3` returned `PARSE_ERROR` because the percent regex greedily rewrote `5 %` to `(5/100)`. `2^3` and `1 < 2` returned generic `UNSUPPORTED_NODE` with no hint about the actual supported syntax.
**Fix:**
- Tightened percent regex with negative lookahead `(?!\s*[\w.\(])`. `5%2`, `5%pi`, `5%(3+1)` no longer get rewritten — they fall through to `BinOp(Mod)` which the validator catches.
- Five new reason codes: `WANT_POWER` (for `^`), `WANT_MOD` (for `%` as operator), `WANT_COMPARE` (for `<`, `==`, `and`, `or`), `WANT_BITWISE` (for `&`, `|`, `<<`, `>>`, `~`), `WANT_EXPLICIT_MULT` (for `2(3)`, `2pi`). Each has a hint pointing at the supported equivalent.
**Tests:** `test_parse_emits_specific_hints_for_common_operator_mistakes`, `test_parse_rejects_modulo_operator_with_want_mod`, `test_modulo_between_numbers_now_emits_want_mod_after_regex_tightening`, `test_trailing_percent_still_works_after_regex_tightening`.
**Files:** [lib/parser.py:30-39](lib/parser.py#L30-L39), [lib/parser.py:124-148](lib/parser.py#L124-L148), [lib/reasons.py](lib/reasons.py)
**Status:** Fixed.

### T2-01 — Format boundary at `1e-7` rendered as `0` (MAJOR)
**Probe:** `/calc 1e-7` with default precision=6 returned `"0"`. The boundary `abs_v < 10 ** (-precision - 1)` was off by one: at exactly `1e-7` the condition was False, so fixed-point format ran and produced `"0.000000"` → trimmed to `"0"`.
**Fix:** Boundary is now `abs_v < 10 ** -precision`. Anything below the smallest representable fixed-point value at the chosen precision routes to scientific notation.
**Tests:** `test_value_at_precision_boundary_uses_scientific`, `test_value_just_above_precision_stays_fixed`.
**Files:** [lib/format.py:42-46](lib/format.py#L42-L46)
**Status:** Fixed.

### T2-02 — Angle-mode footer noise on non-trig results (MINOR)
**Probe:** `/calc 2+2` showed `angle: radians` in the footer despite the expression not using trig.
**Fix:** `parser.uses_trig(tree)` walks the validated AST for trig calls. Footer only emitted when True.
**Files:** [lib/parser.py:181-187](lib/parser.py#L181-L187), [lib/embed.py:106-123](lib/embed.py#L106-L123), [plugin.py:181-189](plugin.py#L181-L189)
**Status:** Fixed.

### T1-06 — Pow guard boundary documented (NIT)
**Probe:** Why 64 specifically?
**Fix:** Extracted `_POW_INT_EXP_LIMIT = 64`, `_POW_INT_BASE_LIMIT = 1_000_000` with a rationale comment that ties the value to the sandbox's 64 MB RAM ceiling.
**Files:** [lib/functions.py:69-84](lib/functions.py#L69-L84)
**Status:** Fixed (clarification, not behavior change).

### T2-04 — Scientific format unified across int/float (MINOR)
**Probe:** `_format_int` called `_scientific(float(v), max(6, _digits(scientific_threshold)))`, `_format_float` called `_scientific(v, max(1, precision))`. Same value via two paths could render with different precisions.
**Fix:** Both paths now use `max(1, precision)`. Helper `_digits` removed.
**Files:** [lib/format.py:21-32](lib/format.py#L21-L32)
**Status:** Fixed.

### T3-01 — Case-sensitivity message clarified (MINOR)
**Probe:** `/calc Pi` returned "Unknown name. Only pi, e, and tau are supported as constants." User couldn't tell whether the issue was the name or the case.
**Fix:** Hint now reads "Only pi, e, and tau are supported (case-sensitive)."
**Files:** [lib/reasons.py:55](lib/reasons.py#L55)
**Status:** Fixed.

### T3-02 — Implicit multiplication caught with specific hint (MINOR)
**Probe:** `2(3)` returned `UNSUPPORTED_NODE`. `2pi` returned `PARSE_ERROR`. Both are calculator-keyboard idioms.
**Fix:** `_validate` raises `WANT_EXPLICIT_MULT` directly on non-name `Call`. The convenience `parse()` also matches `\d\s*\(|\d\s*[A-Za-z_]` against the cleaned input after parse failure, surfacing the same hint for `2pi`-style syntax errors.
**Files:** [lib/parser.py:163-167](lib/parser.py#L163-L167), [lib/parser.py:178-182](lib/parser.py#L178-L182)
**Status:** Fixed.

### T3-03 — `inf` / `nan` documented in help (NIT)
**Fix:** Help text now includes "inf/nan literals not supported."
**Files:** [lib/embed.py:140](lib/embed.py#L140)
**Status:** Fixed.

### T3-05 / T3-06 — Help text auto-generates from registry + canonical limits (MINOR)
**Probe:** HELP_TEXT manually listed 24 functions and the 120-char input cap. Adding a function or changing the cap would silently drift.
**Fix:** `_build_help_text()` derives the function list from `FUNCTIONS` and the limits from `parser.MAX_INPUT_LEN` and `walker.BUDGET_SECONDS`. Categories are grouped via `CATEGORY_ORDER`.
**Files:** [lib/embed.py:120-150](lib/embed.py#L120-L150)
**Status:** Fixed.

### S1 — Function registry (MINOR)
**Fix:** `FunctionSpec` dataclass collects name, impl, arity, category, and help blurb. `FUNCTIONS` list is the single registry. `_PLAIN_FUNCS` / `_TRIG_FUNCS` dicts removed; `ALL_FUNCTION_NAMES` and `_REGISTRY` derive from it. `call_function` centralizes the arity check. Adding a function is one new list entry.
**Files:** [lib/functions.py:184-218](lib/functions.py#L184-L218)
**Status:** Fixed.

### S3 — Semver alignment (NIT)
**Decision:** Bumped from v1.0.0 to v0.2.0. The handoff's semver policy reserves major bumps for breaking changes; the inaugural release should be 0.1.0, and v1.0.0 comes after the SDK-assumption probe is complete. Documented at the top of CHANGELOG.
**Status:** Fixed.

### T6-01 — `OK` constant (NIT)
**Fix:** `R.OK = "ok"` exported from `lib/reasons.py`. `_record_eval(ctx, R.OK, started)` replaces the magic string in [plugin.py:191](plugin.py#L191).
**Status:** Fixed.

### T6-02 — Latency-metric docstring clarified (NIT)
**Fix:** Docstring on `_record_metric` (renamed from `_record_eval` in v0.2.1) notes that elapsed covers the full handler, not just the walker.
**Files:** [plugin.py:62-71](plugin.py#L62-L71)
**Status:** Fixed.

### T2-03, T3-04, S2, T6-03, E1, E2, E3 — Deferred
- **T2-03** (negative-zero sign preservation): NIT. Accept; calculator users don't expect `-0`.
- **T3-04** (`(-5)%` regex extension): NIT. Document as a limitation; users write `-5%` or `(-5)/100`.
- **S2** (configurable cooldown): Defer until a user asks.
- **T6-03** (request_id metric tag): Would explode cardinality; tagging not appropriate. Logs already correlate by request_id.
- **E1** (autocomplete), **E2** (history), **E3** (explain-mode): Backlog. None are blockers; all add SDK-shape unknowns or sizeable code paths.

### Testing gaps (T5-*) — all fixed
- `(-2)**0.5` added to `test_domain_errors` parametrize.
- `1e1000` and post-binop nan/inf cases added to `tests/test_walker.py` (renamed from `test_evaluator.py` in v0.2.1).
- `5 % 3` collision tests added to `test_parser.py` and `test_handlers.py`.
- Format boundary at `1e-7` added to `test_format.py`.
- Cooldown fallback when ephemeral raises added to `test_handlers.py`.

Test count grew from 175 → 192.

---

## Round U — Marketplace-validator escape (v0.2.1)

Caught at upload, not at audit. The MMO Maid platform validator rejected the bundle with:

> `lib/evaluator.py: contains blocked pattern 'eval(' — this is not allowed in marketplace plugins`

The validator uses **substring matching**, not Python parsing. Our `_eval(...)` recursive helper and `_record_eval(...)` metric helper both contained the literal `eval(` substring and tripped the check despite being custom identifiers, not calls to the dangerous builtin.

### U1 — `eval(` substring escape (BLOCKER)

**Probe:** Build the bundle and read any shipped file for the substring `eval(`. Pre-fix hits: `lib/evaluator.py` (6×, function def + recursive calls), `plugin.py` (6×, `_record_eval` def + calls), `lib/parser.py` (1×, docstring mentioned `eval()`).

**Why our local audit missed it:** [tools/run_audit.py:check_no_eval_compile_exec_ast](tools/run_audit.py) uses `ast.parse` + `ast.walk` to find calls where `node.func.id in {"eval", "exec", "compile"}`. That correctly didn't match our custom-named functions. The marketplace's substring check is strictly weaker (matches identifier prefixes) but is what we have to satisfy.

**Fix:**
1. Renamed `lib/evaluator.py` → [lib/walker.py](lib/walker.py).
2. Renamed every `eval`-rooted identifier: `evaluate` → `run`, `_eval` → `_walk`, `evaluate_safe` → `run_safe`, `EvalError` → `WalkError`, `EVAL_BUDGET_SECONDS` → `BUDGET_SECONDS`.
3. Renamed `plugin._record_eval` → `plugin._record_metric`. The metric **name** `"calc_eval"` (a string literal without trailing `(`) is unchanged so any future dashboard still finds it.
4. Rewrote [lib/parser.py](lib/parser.py) module docstring to describe the safety guarantee without using the literal substrings `eval()`/`exec()`/`compile()`.
5. Renamed `tests/test_evaluator.py` → `tests/test_walker.py`, internal `_eval` test helper → `_run`, and `test_..._with_eval` → `test_..._with_calc`.

**New audit gate:** [tools/run_audit.py:check_blocked_substrings](tools/run_audit.py). Substring-based scan over the bundle's `INCLUDED_FILES`, blocking `eval(`, `exec(`, and `__import__(`. Intentionally narrow — initially included `compile(`, `getattr(`, `globals(`, etc., but `compile(` false-positived on `re.compile(...)` and the marketplace clearly can't actually be blocking common stdlib idioms. If a future upload hits a different pattern, add it back here. The AST gate `check_no_eval_compile_exec_ast` stays in place for the broader set; the two gates are complementary.

**Files:** [lib/walker.py](lib/walker.py), [plugin.py](plugin.py), [lib/embed.py](lib/embed.py), [lib/parser.py](lib/parser.py), [lib/functions.py](lib/functions.py), [tests/test_walker.py](tests/test_walker.py), [tests/test_failure_injection.py](tests/test_failure_injection.py), [tools/build_bundle.py](tools/build_bundle.py), [tools/run_audit.py](tools/run_audit.py)

**Status:** Fixed. All 8 audit gates green, 195 tests green, zero `eval(`/`exec(`/`__import__(` substrings in any shipped file.

**Lesson for future rounds:** When the local audit and the platform's validator use different matching strategies, the local audit is at best an under-approximation of what the platform will accept. Mirror the platform's strategy when possible — even if it's naive — so failures happen at audit time, not at upload.

---

## Post-launch findings (v0.2.2 – v0.2.8)

Production traffic surfaced three real bugs that pre-launch testing missed, plus motivated four UX improvements. Each was shipped as a patch release on `main` directly; no separate audit-round artifacts. The CHANGELOG carries the full detail per version.

### v0.2.2 — SDK event-shape correction (BLOCKER, fixed)

**Symptom:** Every `/calc` invocation returned `reason: empty` in production despite users typing real expressions. Cooldown keys bucketed under `cd:calc:unknown`.

**Root cause:** Our test fixtures emitted the SDK shape from the SDK doc's example (`event["options"]`, `event["member"]["user"]["id"]`). The actual runtime delivers `event["command_options"]` and `event["user_id"]` at the top level. Tests passed against a fiction.

**Fix:** `_options`, `_user_id`, `_is_admin` now read the observed shape first, fall back to the doc shape. Test fixtures updated. Regression test in `tests/test_handlers.py:test_calc_with_real_sdk_event_shape_evaluates_expression` uses a verbatim production payload.

**Lesson:** SDK doc examples are advisory, not authoritative. The first probe after a marketplace install should always be "send a real interaction, log the raw payload, compare to assumptions."

### v0.2.6 — Implicit-mult hint regex symmetry (MINOR, fixed)

**Symptom:** `/calc 1000 * (1 + 7%)  10` (missing operator between `)` and `10`) returned generic `parse_error` instead of the `WANT_EXPLICIT_MULT` hint that v0.2.0 added for the symmetric `2(3)` / `2pi` case.

**Fix:** Six-character regex extension on `_IMPLICIT_MULT_RE`: added `\)\s*\d|\)\s*[A-Za-z_]` alternates.

**Lesson:** When a hint regex covers "X then Y", check whether the symmetric "Y then X" deserves the same hint.

### v0.2.7 — Expression-echo `**` stripping (MAJOR, fixed)

**Symptom:** `/calc 2**8` rendered `2  8` (double space, no operator) in the embed's expression echo. Math still computed correctly (`= 256`); only the display lied.

**Root cause:** `lib/embed.py:safe_text` aggressively strips every markdown marker (`**`, `__`, `~~`, `||`, `` ` ``) — including `**`, which is a legitimate Python Pow operator. The strip happens before the expression is wrapped in inline-code backticks; Discord doesn't actually interpret `**` inside backticks anyway.

**Fix:** New `safe_text_in_code` helper that keeps markdown chars but still strips backticks (the only chars that genuinely break the inline-code context). Used for the expression echo in `build_result_embed` and `build_error_embed`.

**Lesson:** Sanitisation should be context-aware. The same string going into a `## header` vs an inline `` `code` `` span has different sensitivities; using strict scrub for both was the bug.

### v0.2.3 / v0.2.4 / v0.2.5 / v0.2.8 — UX additions

Each motivated by direct user feedback rather than an audit finding:

- **v0.2.3** — Header-hero result + field-grid help. See ARCHITECTURE §I.
- **v0.2.4** — Step trace with smart-auto threshold. See ARCHITECTURE §J.
- **v0.2.5** — Brand thumbnail on success embeds. See ARCHITECTURE §K. Verified SDK A11 (embed thumbnail kwarg).
- **v0.2.8** — Diagnostic explainer with did-you-mean. See ARCHITECTURE §L.

### Status: All 247 tests green, all 8 audit gates green, no known regressions in production.

---

## Round V — Second-order audit (v0.2.9)

Independent re-read of the entire codebase after R1–R3, T, U, and v0.2.2–v0.2.8 post-launch shipped. Goal: find what those rounds missed. Result: 2 MAJOR correctness items + 1 MINOR error-routing + 1 minor cap robustness + 7 nit-level cleanups + 5 test-coverage gaps. No BLOCKER. All fixed in v0.2.9.

| ID | Severity | One-liner | Status |
|---|---|---|---|
| V1-01 | MAJOR | `_safe_pow` precision loss: `mod(2**100, 7) = 0.0` instead of `2` | **Fixed** (bit-budget replaces axis caps) |
| V1-02 | MAJOR | `_options` raises AttributeError on non-dict `event["data"]` | **Fixed** (type-check each slot) |
| V1-03 | MINOR | `log(x, 1)` reports DIV_BY_ZERO with misleading "second arg" hint | **Fixed** (pre-check, ValueError → DOMAIN_ERROR) |
| V2-01 | MINOR | `enforce_total_cap` trims description only — field-heavy embeds escape cap | **Fixed** (two-pass: description, then fields) |
| V2-02 | NIT (docs) | Floor-division semantics may surprise C/JS users | **Fixed** (Notes line in `/calc-help`, CLAUDE bullet) |
| V3-01 | NIT | `format_result`'s `isinstance(value, bool)` branch is unreachable | **Fixed** (branch removed, invariant locked by V4-04) |
| V3-02 | NIT | `cmd_calc_config` tautology `x if x is not None else None` | **Fixed** (three tautologies dropped) |
| V3-03 | NIT | Lazy `from . import diagnostics` in `build_error_embed` — no cycle | **Fixed** (hoisted to module top) |
| V3-04 | NIT | Redundant `and abs_v < big` in `_format_float` | **Fixed** (condition simplified) |
| V3-05 | NIT | `embed.py` docstring drift (`_safe_text` → `safe_text`) | **Fixed** (docstring corrected) |
| V3-06 | NIT | Inconsistent import style in `tools/run_audit.py` | **Fixed** (`from tools.build_bundle import …` everywhere) |
| V3-07 | NIT | Literal ZWSP / bidi controls in `embed.py` source | **Fixed** (replaced with `\u` escapes) |
| V3-08 | NIT | `.claude/settings.local.json` allegedly committed | **N/A** (file isn't tracked; `.gitignore` already covers it) |
| V3-09 | NIT | "epoch 0" comment in `build_bundle.py` misleading | **Fixed** (rephrased as "zip-format epoch, 1980-01-01") |
| V4-01 | TEST | No regression test for `_safe_pow` exact-int preservation | **Added** (4 cases + boundary + DoS canary) |
| V4-02 | TEST | No test for `log(x, 1)` domain handling | **Added** (3 cases + happy-path lock) |
| V4-03 | TEST | No test for malformed `event["data"]` shape | **Added** (7 parametrized malformed payloads) |
| V4-04 | TEST | No invariant test that walker never returns `bool` | **Added** (14 sampled expressions) |
| V4-05 | TEST | No test for `enforce_total_cap` field-heavy path | **Added** (new `tests/test_embed.py`, 5 cases) |

### Why R1–T missed these

V1-01 is the most instructive: existing tests probed the *DoS* boundary (does `9**99999` overflow?) and the *domain* boundary (does `sqrt(-1)` raise?). No test asserted *exact* int preservation for a power the bignum was perfectly capable of computing. The documented pow-guard contract in CLAUDE.md said "clamps at float-overflow," not "may lose precision below the DoS threshold" — so the precision regression was invisible to anyone reading the contract.

V1-02 came from the same blind spot as v0.2.2's "SDK doc examples are advisory, not authoritative": the post-v0.2.2 fix made `_options` more defensive but the `event["data"]` fallback path was added later (defensive against a Discord-style nested shape) and inherited the original assumption that `data` is a dict if present at all.

V1-03 — never noticed because `log` happy-path tests cover `log(8, 2) == 3` etc.; nobody ever tested `log(5, 1)` until a user could ask "why does this work the way it does?"

V2-01 — never noticed because every embed Disculate currently builds fits well under the cap. Found by reading the function critically, asking "does this enforce the cap in every shape?" rather than "does this work for our shapes?"

### Architectural observations (informational, not findings)

- The pow guard was implicitly enforcing two policies (DoS bound + precision floor). After V1-01's fix, it enforces one (DoS bound); precision preservation is a direct consequence.
- The detail-string convention has free-form string detail with handler-specific parsing (`split(":", 1)`, `rpartition("@")`). Works for the current ~12 reasons but a `Detail = dataclass` refactor would scale better if the explainer grows. Defer until pain emerges.
- Adding `tests/test_known_inputs.py` (a single parametrized catalogue of expression → expected reason / value) would make future regressions louder than the current spread across `test_adversarial`, `test_parser`, `test_walker`, etc. Worth doing in a future round; not a finding.

### Status: 272 tests green, all 8 audit gates green. Pow-guard precision restored; handler is type-safe; help embed protected end-to-end against the 6000-char wall.
