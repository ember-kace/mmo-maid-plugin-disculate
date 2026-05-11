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
**Assumption:** Discord raw API uses string; some SDK transports decode to int. We handle both.
**Probe:** Run `/calc-config precision:5` as an admin. Either branch should grant access. Log shows `_is_admin` returning True.
**Falsification:** Admin command is rejected for a real admin. Dump `event["member"]` and check `permissions` type.
**Fallback if wrong:** Update `_is_admin` to coerce the actual type seen.
**Status:** Unverified.

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
**Assumption:** `event["member"]["user"]["id"]` in guild, `event["user"]["id"]` in DMs (defensive — plugin is per-server, DMs shouldn't happen).
**Probe:** Run `/calc 1+1`, log `request_id` and look at the cooldown key in the next request. Should be `cd:calc:<your_id>`, not `cd:calc:unknown`.
**Falsification:** Cooldown key is `cd:calc:unknown` for a real user.
**Fallback if wrong:** All anonymous users share one cooldown — soft DoS surface but not a crash. Update `_user_id`.
**Status:** Unverified.

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
**Assumption:** SDK normalizes Discord's nested `data.options` to a flat list. SDK doc shows `event.get("options", [])` for slash command events.
**Probe:** Run `/calc-config precision:3 angle_mode:deg`. Confirm the config writes both fields.
**Falsification:** Only one field updated, or none — options shape is different.
**Fallback if wrong:** Adjust `_options` to dig into `event["data"]["options"]`.
**Status:** Unverified.

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

## Verification ritual (Phase 4, 30 minutes after first install)

1. Run each command listed in the probe section above in a test server.
2. Watch the structured-log viewer.
3. Mark each entry VERIFIED or WRONG with a one-line note (e.g., "VERIFIED 2026-05-12; embed renders fine").
4. For VERIFIED entries with a defensive try/except that exists only for the assumption: simplify or remove the fallback in a follow-up patch.
5. For WRONG entries: apply the documented fallback and re-bundle.
