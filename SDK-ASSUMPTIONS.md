# SDK-ASSUMPTIONS.md — Disculate

Inventory of behaviors this plugin guesses at because the public SDK doc is incomplete. Walk this top to bottom after first install. Mark each VERIFIED or WRONG; delete the defensive try/except for items proven correct.

---

## A1 — `ctx.interaction.respond` accepts `embeds=[...]`
**Code:** `plugin.py:_safe_respond`, all `cmd_*` handlers.
**Assumption:** The SDK passes `embeds` through to Discord's REST interaction-response API. SDK doc shows only `content=`, `components=`, `ephemeral=`.
**Probe:** Run `/calc 1+1`. Confirm the response renders as an embed with gold accent and "= **2**" in the body.
**Falsification:** If the embed doesn't render (plain text, or empty response), the SDK is dropping `embeds`. Replace with `content=` plus markdown body.
**Fallback if wrong:** `_safe_respond` catches and logs. User sees nothing but no crash.
**Status:** Unverified.

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
**Probe:** Run `/calc 1+1` twice in 2 seconds. Second should show "Slow down" embed with remaining seconds.
**Falsification:** Second call goes through, or "Slow down" shows but with wrong/zero seconds.
**Fallback if wrong:** Adjust key names in `_check_cooldown`; falls open if shape differs.
**Status:** Unverified.

---

## A4 — `ctx.ephemeral.cooldown_set(key, ttl_seconds=N)`
**Code:** `plugin.py:_set_cooldown`
**Assumption:** Kwarg is `ttl_seconds`. Some SDKs use positional or `ttl`.
**Probe:** Same as A3 — if cooldown blocks the second call, this works too.
**Falsification:** TypeError in logs, or no cooldown applied.
**Fallback if wrong:** Match the actual signature.
**Status:** Unverified.

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
**Probe:** Run `/calc @everyone 1+1`. The response shows `@​everyone` (zero-width-joined) in the body but does NOT actually ping `@everyone` in the channel.
**Falsification:** Either ping fires (SDK is not forwarding allowed_mentions) or TypeError in logs.
**Fallback if wrong:** Rely solely on `safe_text`'s zero-width injection, which already breaks the ping client-side.
**Status:** Unverified.

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
**Probe:** First call to `/calc` on a fresh server should succeed with default config.
**Falsification:** First `/calc` errors or logs unexpected exception from `get_config`.
**Fallback if wrong:** `get_config` catches any exception and returns defaults — already defensive.
**Status:** Unverified.

---

## A9 — `ctx.metrics.record(name, value, tags)` signature
**Code:** `plugin.py:_record_eval`, `_record_config`.
**Assumption:** Per SDK doc — `ctx.metrics.record("name", value=N, tags={...})`.
**Probe:** Run `/calc 1+1`, then check the dev portal metrics viewer for `calc_eval` and `calc_latency_ms` entries.
**Falsification:** No metrics appear, or TypeError.
**Fallback if wrong:** Adjust signature; metric recording is already wrapped in try/except so failure doesn't break the response.
**Status:** Unverified.

---

## A10 — `ctx.log(msg, level=..., request_id=..., **extra)` carries kwargs through
**Code:** `lib/logctx.py:log_info / log_warn / log_error`.
**Assumption:** Extra kwargs are stored as JSON detail (per SDK doc) and become greppable.
**Probe:** Trigger an error path (e.g., `/calc 1/0`), check the log viewer for an entry with `request_id`, `level=warning`, and the structured `reason` field.
**Falsification:** Logs missing the kwargs, or only carrying the message text.
**Fallback if wrong:** Format kwargs into the message string manually.
**Status:** Unverified.

---

## A11 — `ctx.interaction.respond` forwards `embed.thumbnail` to Discord
**Code:** `lib/embed.py:build_result_embed`, `build_help_embed`, `build_config_embed` (only on the "updated" path).
**Assumption:** The SDK forwards arbitrary embed-dict keys to Discord's REST interaction-response API. `thumbnail = {"url": "<https-url>"}` is a standard Discord embed field and should pass through unchanged. Same reasoning as A1, but specifically about the thumbnail slot — Discord renders it top-right of the embed.
**Status:** **VERIFIED 2026-05-12.** Live `/calc-help` in the test guild rendered the Disculate avatar top-right of the embed (`raw.githubusercontent.com/.../assets/disculate.webp` served 200 OK to Discord's image proxy once the repo was made public). The error-path negative case also confirmed: a `parse_error` embed in the same screenshot carried no thumbnail, as designed. Result and config-updated builders share the same `_BRAND_THUMBNAIL` constant — verified by extension.

---

## Verification ritual (Phase 4, 30 minutes after first install)

1. Run each command listed in the probe section above in a test server.
2. Watch the structured-log viewer.
3. Mark each entry VERIFIED or WRONG with a one-line note (e.g., "VERIFIED 2026-05-12; embed renders fine").
4. For VERIFIED entries with a defensive try/except that exists only for the assumption: simplify or remove the fallback in a follow-up patch.
5. For WRONG entries: apply the documented fallback and re-bundle.
