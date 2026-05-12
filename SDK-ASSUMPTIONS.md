# SDK-ASSUMPTIONS.md — Disculate

Inventory of behaviors this plugin guesses at because the public SDK doc is incomplete. Walk this top to bottom after first install. Mark each VERIFIED or WRONG; delete the defensive try/except for items proven correct.

---

## A1 — `ctx.interaction.respond` accepts `embeds=[...]`
**Code:** `plugin.py:_safe_respond`, all `cmd_*` handlers.
**Assumption:** The SDK passes `embeds` through to Discord's REST interaction-response API. SDK doc shows only `content=`, `components=`, `ephemeral=`.
**Status:** **VERIFIED 2026-05-12 (by production traffic).** Every `/calc`, `/calc-help`, and `/calc-config` invocation since v0.2.0 has rendered an embed. Header-hero, field-grid, step trace, and brand-thumbnail layouts all rely on the SDK forwarding the full embed dict. No evidence of dropped fields in production logs.

---

## A2 — `event["member"]["permissions"]` can be int OR str
**Code:** `plugin.py:_is_admin`
**Original assumption:** Discord raw API uses string; some SDK transports decode to int. We handle both.
**Status:** **WRONG (resolved in v0.2.2).** The runtime delivers `permissions` as a top-level string on the event dict — there is no `member` wrapper at all. `_is_admin` now reads `event["permissions"]` first and falls back to the nested shape only if the top-level field is missing. Both int and str are still accepted.
**Observed payload (May 2026):** `{"type": "interaction_create", "user_id": "...", "permissions": "8", ...}` — flat.

---

## A3 — `ctx.ephemeral.cooldown_check(key)` returns `{"active": bool, "remaining_seconds": int}`
**Code:** `plugin.py:_check_cooldown`
**Assumption:** Per the SDK doc surface, but the doc doesn't precisely specify the dict keys.
**Status:** **VERIFIED 2026-05-12 (by production traffic).** Production logs show `ephemeral.cooldown_check` returning `{"active": ..., "remaining_seconds": ...}` with the expected types; the "Slow down" embed fires correctly on the second `/calc` within 2 seconds (`rpc_method: ephemeral.cooldown_check` log entries followed by a `cooldown` reason on the response).

---

## A4 — `ctx.ephemeral.cooldown_set(key, ttl_seconds=N)`
**Code:** `plugin.py:_set_cooldown`
**Assumption:** Kwarg is `ttl_seconds`. Some SDKs use positional or `ttl`.
**Status:** **VERIFIED 2026-05-12 (by production traffic).** Logs show `ephemeral.cooldown_set` returning successfully with `ttl_seconds=2` after every successful `/calc`; subsequent calls within the TTL window hit the cooldown path as expected.

---

## A5 — `user_id` path in interaction events
**Code:** `plugin.py:_user_id`
**Original assumption:** `event["member"]["user"]["id"]` in guild, `event["user"]["id"]` in DMs.
**Status:** **WRONG (resolved in v0.2.2).** Production logs revealed cooldown keys reading `cd:calc:unknown` — the fallback bucket — which is exactly the symptom this assumption was supposed to prevent. The actual shape is `event["user_id"]` as a top-level string. `_user_id` now checks that first; the nested shapes remain as fallbacks.
**Observed payload (May 2026):** `{"user_id": "627259696343941120", "user_username": "openshift", ...}` — flat.

---

## A6 — `allowed_mentions={"parse": []}` is accepted by `respond`
**Code:** `plugin.py:_safe_respond` (default), explicit in handler calls.
**Assumption:** Discord-standard payload. SDK doc doesn't mention this kwarg.
**Status:** **VERIFIED 2026-05-12 (by production traffic).** Production logs show `respond` calls with `allowed_mentions: {"parse": []}` succeeding (no TypeError). Defense-in-depth: even if the SDK silently dropped this kwarg, `safe_text`'s zero-width-space injection still neutralises `@everyone` / `@here` in echoed content.

---

## A7 — `event["options"]` is a flat list of `{"name", "value"}`
**Code:** `plugin.py:_options`, all handlers.
**Original assumption:** SDK normalizes Discord's nested `data.options` to a flat list at `event["options"]`. SDK doc's example used `event.get("options", [])`.
**Status:** **WRONG (resolved in v0.2.2). The biggest miss of the session.** Production logs showed every `/calc` returning the EMPTY reason despite users typing real expressions. The SDK delivers slash command arguments at `event["command_options"]`, not `event["options"]` — the SDK doc's example is out of date. `_options` now reads `command_options` first, then `options`, then `data.options`.
**Observed payload (May 2026):** `{"command_name": "calc", "command_options": [{"name": "expression", "type": 3, "value": "3+6"}], ...}`.
**Lesson:** The SDK doc's examples are not reliable — only the observed runtime payload is. The other SDK assumption entries in this file should be assumed unreliable until empirically validated.

---

## A8 — `ctx.kv.get` returns `None` for missing keys (not raises)
**Code:** `lib/config.py:get_config`
**Assumption:** SDK doc shows `get / set / delete / exists / increment / ...` but doesn't specify miss behavior.
**Status:** **VERIFIED 2026-05-12 (by production traffic).** Logs show `kv.get key="config"` returning successfully on first `/calc` invocations on a fresh server; default config is applied silently with no error log entries.

---

## A9 — `ctx.metrics.record(name, value, tags)` signature
**Code:** `plugin.py:_record_metric`, `_record_config`.
**Assumption:** Per SDK doc — `ctx.metrics.record("name", value=N, tags={...})`.
**Status:** **VERIFIED 2026-05-12 (by production traffic).** Logs show `metrics.record` calls with `metric: "calc_eval"` and `metric: "calc_latency_ms"` landing successfully on every `/calc` invocation; tag values track the documented enum (`ok`, `parse_error`, `want_explicit_mult`, etc.).

---

## A10 — `ctx.log(msg, level=..., request_id=..., **extra)` carries kwargs through
**Code:** `lib/logctx.py:log_info / log_warn / log_error`.
**Assumption:** Extra kwargs are stored as JSON detail (per SDK doc) and become greppable.
**Status:** **VERIFIED 2026-05-12 (by production traffic).** Structured `details` field in the log viewer carries `request_id`, `event_id`, `worker_idx`, and our custom kwargs (`reason`, `err`, etc.) as documented.

---

## A11 — `ctx.interaction.respond` forwards `embed.thumbnail` to Discord
**Code:** `lib/embed.py:build_result_embed`, `build_help_embed`, `build_config_embed` (only on the "updated" path).
**Assumption:** The SDK forwards arbitrary embed-dict keys to Discord's REST interaction-response API. `thumbnail = {"url": "<https-url>"}` is a standard Discord embed field and should pass through unchanged. Same reasoning as A1, but specifically about the thumbnail slot — Discord renders it top-right of the embed.
**Status:** **VERIFIED 2026-05-12.** Live `/calc-help` in the test guild rendered the Disculate avatar top-right of the embed (`raw.githubusercontent.com/.../assets/disculate.webp` served 200 OK to Discord's image proxy once the repo was made public). The error-path negative case also confirmed: a `parse_error` embed in the same screenshot carried no thumbnail, as designed. Result and config-updated builders share the same `_BRAND_THUMBNAIL` constant — verified by extension.

---

## Verification ritual (completed 2026-05-12)

The probe completed: 9 of 11 assumptions verified by production traffic, 3 of which (A2, A5, A7) turned out WRONG and were fixed in v0.2.2.

| ID | Topic | Status |
|---|---|---|
| A1 | Embed forwarding | VERIFIED |
| A2 | `permissions` shape | WRONG → fixed v0.2.2 |
| A3 | `cooldown_check` return shape | VERIFIED |
| A4 | `cooldown_set` kwarg name | VERIFIED |
| A5 | `user_id` event path | WRONG → fixed v0.2.2 |
| A6 | `allowed_mentions` forwarding | VERIFIED |
| A7 | Slash command options shape | WRONG → fixed v0.2.2 (biggest miss of the launch) |
| A8 | `kv.get` miss returns None | VERIFIED |
| A9 | `metrics.record` signature | VERIFIED |
| A10 | `ctx.log` kwarg forwarding | VERIFIED |
| A11 | Embed `thumbnail` forwarding | VERIFIED |

**Net lesson:** SDK doc examples were unreliable in three of seven testable cases. For future MMO Maid plugin work, the first production deploy should always validate event-shape assumptions against the structured log viewer before declaring v1.0.

**Open follow-ups:** None blocking. Defensive try/except blocks at every external `ctx.*` call site remain in place — the verification doesn't justify removing them since the marginal cost is one branch each and the recovery story matters more than the cost.
