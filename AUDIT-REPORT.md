# AUDIT-REPORT.md — Disculate

**Verdict:** PASS for v0.2.0 ship (post-tailored-audit).

| Round | Verdict | Findings | Action |
|---|---|---|---|
| R1 — Correctness (v0.1.0) | PASS | 0 BLOCKER, 0 MAJOR, 2 MINOR (fixed) | Both fixed in-tree before v0.1.0. |
| R2 — Tailored, generic (v0.1.0) | PASS | 0 BLOCKER, 0 MAJOR, 3 MINOR (deferred or accepted) | All scope/design decisions documented. |
| R3 — Deep (v0.1.0) | PASS | 0 BLOCKER, 0 MAJOR, 5 INFO | Logged into SDK-ASSUMPTIONS.md and RUNBOOK.md. |
| **T — Tailored, math-shape-specific (v0.2.0)** | **PASS** | **0 BLOCKER, 3 MAJOR (fixed), 6 MINOR (mostly fixed), 4 NIT (mostly fixed), 3 ENHANCE (deferred)** | All MAJORs and most MINORs fixed; ENHANCE items in backlog. |

Audit gates: all 7 green (`py tools/run_audit.py`). Tests: 192/192 green (up from 175).

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
**Probe:** Time `evaluate_safe` on the deepest legal expression (32 binops, 200 nodes max). p99 < 1ms on a developer laptop.
**Decision:** The budget check fires before each node visit, so a single very-slow node could run uncapped. All our allowed primitives (`math.*`, arithmetic) are O(1), so this never matters in practice. Documented for future maintainers.
**Files:** `lib/evaluator.py:38-46`

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
**Fix:** `parser._validate` rejects non-finite float literals with `OVERFLOW`. `evaluator._eval` centralized post-op finite check; the Pow-specific check is removed for a single source of truth.
**Tests:** `test_inf_literal_rejected_at_parse_time`, `test_inf_nan_results_caught_post_binop`.
**Files:** [lib/parser.py:114-117](lib/parser.py#L114-L117), [lib/evaluator.py:36-46](lib/evaluator.py#L36-L46)
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
**Fix:** `_build_help_text()` derives the function list from `FUNCTIONS` and the limits from `parser.MAX_INPUT_LEN` and `evaluator.EVAL_BUDGET_SECONDS`. Categories are grouped via `CATEGORY_ORDER`.
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
**Fix:** Docstring on `_record_eval` notes that elapsed covers the full handler, not just the evaluator.
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
- `1e1000` and post-binop nan/inf cases added to `test_evaluator.py`.
- `5 % 3` collision tests added to `test_parser.py` and `test_handlers.py`.
- Format boundary at `1e-7` added to `test_format.py`.
- Cooldown fallback when ephemeral raises added to `test_handlers.py`.

Test count grew from 175 → 192.
