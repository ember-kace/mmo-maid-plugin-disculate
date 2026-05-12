# ARCHITECTURE.md — Disculate

Design decisions and the alternatives they beat. Each section names the call, the rejected alternatives, and the failure mode that would make us revisit.

---

## A — Stdlib `ast.parse` + manual walker, not `eval`, `compile`, or a third-party safe-eval lib

**Decision:** Parse user input with `ast.parse(mode="eval")`, validate every node against an allowlist, then walk the validated tree and compute values by hand.

**Alternatives rejected:**

1. **`eval()` on raw input** — the obvious sandbox escape. Trivially exploitable. Rejected automatically; the `no_eval` audit gate enforces this in code.
2. **`compile(tree, ..., 'eval')` + `eval(code)` on a validated AST** — still hands the validated tree to the interpreter. Any missed node type in the allowlist becomes an interpreter primitive. Rejected for principle and because the manual walker is small (~80 lines).
3. **`asteval`** — third-party safe-eval. Adds a dep and a CVE surface. We don't need its symbol table or numpy interop.
4. **`simpleeval`** — same as `asteval` but smaller. Same reasoning: we'd rather own the 80 lines.
5. **Custom Pratt parser** — would let us only emit the node types we want. ~3x the code of the allowlist walker, no real security benefit, and we'd have to re-litigate operator precedence.

**Failure mode that would revisit:** A future Python version adds a new AST node type that breaks our walker. We'd see test failures in `test_parser.py`; the response is to add the new type to either the allowlist or the explicit reject list. Annual review at minimum.

---

## B — Trailing `%` as `/100`, no `%` modulo operator

**Decision:** The percent regex rewrites `<number>%` to `(<number>/100)`. `mod(a, b)` is the modulo function.

**Alternatives rejected:**

1. **`%` as modulo (Python default)** — Calculator users want `50%` to mean 0.5, not "50 modulo something." Modulo is rarer.
2. **Contextual percent (`100 + 10%` = 110)** — Excel/Windows-calc behavior. Requires non-context-free parsing (the meaning of `%` depends on the operator to its left). Worth doing, deferred to v2.
3. **`percent()` function** — Less ergonomic. We added `mod(a, b)` for the rare case where users actually want modulo.

**Failure mode that would revisit:** Users frequently asking for `100 + 10%` to mean 110, which would require switching to contextual percent.

---

## C — KV for config, ephemeral for cooldowns, no SQL

**Decision:** `storage:kv` capability only (plus `interaction:respond`). One KV key per server (`config`). One ephemeral key per user (`cd:calc:<id>`).

**Alternatives rejected:**

1. **`storage:sql`** — Risky-tier capability. We have no relational queries, no joins, no leaderboards.
2. **Persistent cooldowns in KV** — KV writes-per-request add up. Ephemeral cooldowns are Redis-backed (faster) and LRU-evicted (no quota concern).
3. **No cooldowns** — Marketplace-grade plugin (100+ servers expected) should have a per-user spam guard. 2 seconds is light enough to not annoy.

**Failure mode that would revisit:** If we ever add expression history per user, that needs durable storage — KV (per-user keys, TTL) or SQL.

---

## D — Schema-versioned config values, not schema-versioned keys

**Decision:** KV key is plain `config`. Value carries a `v` field. Reader rejects mismatches and returns defaults.

**Alternative rejected:** Schema-versioned keys (`config:v1`, `config:v2`). Forces explicit migration code. With in-value versions, bumping the schema makes old entries invisible — they auto-repopulate with defaults the next time an admin runs `/calc-config`.

**Failure mode that would revisit:** A future change where existing config data is precious enough that defaults aren't acceptable. Then we'd write a one-shot migration.

---

## E — Embeds for responses, not plain content

**Decision:** Every response is an embed: gold for success, red for error, slate for informational/cooldown.

**Alternatives rejected:**

1. **Plain `content="..."` with markdown** — Works but lacks visual identity. Doesn't match MMO Maid platform's aesthetic.
2. **Code blocks** — Equation rendering in `code` is fine but doesn't compose with branded color/footer.

**Failure mode that would revisit:** SDK rejects `embeds=` kwarg (see SDK-ASSUMPTIONS A1). Fallback path: build the same message as `content=` with markdown.

---

## F — Defense-in-depth DoS guards (input cap, depth cap, node cap, pow guard, wall-clock)

**Decision:** Five layered guards, none of which alone is sufficient:

- 120-char input cap (parser.MAX_INPUT_LEN)
- 32-deep AST (parser.MAX_DEPTH)
- 200-node AST (parser.MAX_NODES)
- `**` operand guard (functions._safe_pow): int base > 1M or int exp > 64 → math.pow → float overflow → typed reason
- 200ms wall-clock budget (walker.BUDGET_SECONDS)

**Alternatives rejected:**

1. **Only input cap.** `9**9**9**9` is 11 chars and would blow up memory.
2. **Only timeout.** A successful but malicious eval that allocates a 1 GB bignum would OOM before the timeout fires.
3. **Only pow guard.** Functions like `factorial` (deferred) have similar properties.
4. **Trust the sandbox.** The sandbox is 64 MB RAM. A single bignum > 64 MB kills the worker; restart latency hits all subsequent users. Better to reject malicious inputs before the bignum grows.

**Failure mode that would revisit:** A new operator or function with unbounded resource cost. The guard pattern (pre-check, then route through float math when in doubt) generalizes.

---

## G — `_safe_respond` + fail-open infra dependencies

**Decision:** Every external `ctx.*` call is wrapped. Cooldown, metrics, and respond failures log an error but don't abort the request. KV read failures fall back to defaults.

**Alternative rejected:** Propagate exceptions. The user would see "Internal error" embeds for transient SDK hiccups that don't affect the computation.

**Failure mode that would revisit:** A future SDK change where silently-failing one of these is dangerous (e.g., if metrics drops become billable). For now, observability of failure-via-log is enough.

---

## H — `request_id` ContextVar, not thread-local

**Decision:** Use `contextvars.ContextVar`, seed at every handler entry.

**Alternatives rejected:**

1. **`threading.local`** — Doesn't work under asyncio. We don't know whether the SDK uses threads, asyncio, or trio; ContextVar handles all three.
2. **Pass request_id as a function parameter** — Threading it through every helper inflates signatures.
3. **Generate inside each log call** — Defeats the point: callers want one ID for the whole event.

**Failure mode that would revisit:** SDK switches to a model where ContextVar isolation breaks (multiprocess, for example). Unlikely.

---

## I — Header-hero result + field-grid help (v0.2.3)

**Decision:** The result embed renders `` `<expression>` `` on top and `## = <result>` below as a Discord markdown heading; the `/calc-help` embed splits function categories into inline embed fields (Basic / Roots-Exp-Log / Trig / Hyperbolic) plus a full-width Notes field.

**Alternatives rejected:**

1. **Bold-only result** (v0.2.0–0.2.2) — the result and expression shared the same visual weight inside a single description line. Looked like a chat message, not a card. Discord's `##` markdown heading inside embed descriptions (post-2023) gives the answer noticeably larger type without needing extra structure.
2. **Reduction-chain rendering** for steps (`= 3*7-8` then `= 21-8` then `= 13`) — would need to track and substitute the entire expression at each step. Numbered substitutions are simpler to compute (one entry per BinOp/Call) and easier to scan.
3. **Single description blob for help** — the v0.2.2 layout. Functional but a wall of text; the field grid groups visually and exploits Discord's 3-per-row inline packing.

**Failure mode that would revisit:** Discord deprecates markdown headers inside embeds (would force a fallback to `**bold**` wrapping).

---

## J — Trace-list step renderer with smart-auto threshold (v0.2.4)

**Decision:** `walker.run` accepts an optional `trace=[]` list. When non-None, the walker appends a `BinOpStep` / `CallStep` dataclass for every successful binary-op or function-call evaluation in inner-first order. `cmd_calc` renders the trace as a numbered "Steps" embed field *only when* `len(trace) >= 2`.

**Alternatives rejected:**

1. **Always render a Steps field** — `/calc 2+2` would show "1. `2 + 1` = `2`" as the only step. Noise. The ≥2 threshold cleanly hides the field for expressions with no meaningful work to display.
2. **Opt-in `steps:true` slash option** — most users never discover slash options. Smart-auto means power users get steps automatically for compound expressions.
3. **Render steps from a re-walk of the AST after evaluation** — would re-do the math. Cheaper to just thread a list through the existing walker.

**Failure mode that would revisit:** A user complains that simple cases sometimes need the trace shown — at which point an `steps:true/false` slash option could be added without disturbing the smart-auto default.

---

## K — Brand asset hosted in-repo, referenced by `raw.githubusercontent.com` URL (v0.2.5)

**Decision:** `assets/disculate.webp` (128×128, ~3 KB) ships in the repo but **not in the marketplace bundle**. Discord fetches it via the hard-coded `BRAND_THUMBNAIL_URL` (raw.githubusercontent.com) at render time.

**Alternatives rejected:**

1. **Bundle the binary inside the plugin zip** — Discord still needs a URL to reference it; the binary inside the bundle would never be served. Pure dead weight.
2. **`attachment://disculate.webp`** Discord attachment-reference syntax — would need the SDK to support multipart message uploads, which the doc doesn't mention. Plus every interaction response would have to re-upload the binary.
3. **Per-server custom branding** via `/calc-config thumbnail:<url>` — adds an admin attack surface (point at a malicious URL, get Discord's proxy to fetch it). Server-uploaded brand assets stay opt-out, off by default. Deferred indefinitely.
4. **External CDN (Imgur / Cloudflare R2 / S3)** — extra infra to maintain. GitHub raw is free, stable, version-controlled, and the repo is already public.

**Failure mode that would revisit:** GitHub's raw URL gets rate-limited or 404s under marketplace-scale traffic. Then move to a real CDN; the `BRAND_THUMBNAIL_URL` constant is the single switch.

---

## L — Diagnostic-explainer layer between reason codes and embed text (v0.2.8)

**Decision:** `lib/diagnostics.py:explain(expression, reason, detail)` returns a context-specific `(what, how)` pair that the error embed renders verbatim above the input echo. Reason codes stay as the bounded enum (for metrics); detail strings carry the raise-site context (function name, operator symbol, SyntaxError offset, typed-name typo, etc.) into the explainer.

**Alternatives rejected:**

1. **One static hint per reason code** (v0.2.0 baseline) — too generic. "Division by zero." doesn't say which operator; "Math domain error." doesn't say which function failed; "Could not parse" doesn't say there's an unclosed paren.
2. **Cardinality-exploded reason codes** (`DIV_BY_ZERO_DIV`, `DIV_BY_ZERO_FLOORDIV`, `DIV_BY_ZERO_MOD`, `DOMAIN_ERROR_SQRT`, `DOMAIN_ERROR_LOG`, …) — would balloon the metric tag space and force a rewrite of every raise site. Putting context in `detail` is a free-text channel that doesn't affect aggregation.
3. **LLM-generated explanations** — adds a network dep and a non-deterministic surface to a sandboxed plugin. The handler library is small enough to template by hand.
4. **`difflib.get_close_matches(cutoff=0.6)`** for did-you-mean — at this cutoff, `cosecant` suggests `cos`, which is wrong. Cutoff 0.7 catches 1-2 character typos but rejects loose guesses; chosen by sampling against the function/constant allowlists.

**Failure mode that would revisit:** A new reason code ships without a matching handler entry — the embed falls back to the canonical `hint_for(reason)` text, which is correct but no better than v0.2.7. Audit checklist for new reason codes should add "wire a handler in lib/diagnostics.py".
