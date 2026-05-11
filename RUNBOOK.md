# RUNBOOK.md — Disculate operational scenarios

Operational scenarios with concrete diagnostics. Each scenario lists the symptom, the user-facing behavior, the admin action, and the recovery path.

---

## 1 — Worker OOM (rare)

**Symptom:** Random `/calc` invocations return nothing or the platform reports the worker was killed.
**Behavior:** SDK respawns the worker. Cold-start adds ~1s latency to the next request.
**Action:** None unless it repeats. The sandbox is 64 MB; our plugin's resident set is well under 5 MB. An OOM is almost certainly a SDK-side regression, not our code.
**Diagnosis:**
- Check the metric `calc_latency_ms` distribution — if p99 spikes coincide with worker restarts, it's a memory pressure event.
- If a single expression seems to always crash the worker, copy it and try it locally with `py -m pytest tests/ -k <relevant>` to see if it crashes.
**Recovery:** SDK auto-respawns. Restart is transparent to users beyond the next-call latency hit.

---

## 2 — Sustained high evaluation timeouts

**Symptom:** Metric `calc_eval` shows elevated `result:timeout` tag values.
**Behavior:** Users see "Evaluation took too long" errors.
**Action:**
- If timeouts cluster around a single user, it's likely DoS probing. The 2-second cooldown limits damage; consider raising `COOLDOWN_SECONDS` if abuse persists.
- If timeouts are distributed, the worker may be CPU-starved. Check sibling plugins for runaway loops.
**Recovery:** No code change needed unless the rate exceeds 1%/day, at which point investigate the longest-running expressions in `request_id`-keyed logs.

---

## 3 — KV quota exceeded on a server

**Symptom:** `KvQuotaError` in logs from `/calc-config`.
**Behavior:** Admin sees the "Internal error" embed; existing config still readable.
**Action:** Each server has 10,000 keys, but we only ever set one (`config`). If we're hitting the quota, another plugin sharing the namespace has gone rogue — that's a platform bug, not ours.
**Diagnosis:** `count(prefix="config")` should be 1.
**Recovery:** Wait for platform quota reset, or admin clears keys manually if SDK exposes that.

---

## 4 — Per-server cache divergence (N/A)

We do not cache calc results. This scenario is intentionally not applicable.

---

## 5 — Schema migration (config v1 → v2 in a future release)

**Symptom:** None visible during the rollout itself.
**Behavior:** Servers on v2 reading a v1 KV entry will get default config back (the `v != 2` reader path returns defaults).
**Action:**
1. Bump `CONFIG_SCHEMA_V` in `lib/config.py`.
2. Update `DEFAULTS` and `validate_updates`.
3. Optionally write a one-shot migration helper that reads v1, writes v2 — but easier to let users re-set via `/calc-config`.
4. Document in `CHANGELOG.md` under the new MINOR/MAJOR version.
**Recovery:** Servers either re-run `/calc-config` or live with defaults.

---

## 6 — Rollback

**Symptom:** v1.0.1 (hypothetical) ships a regression.
**Behavior:** Depends on the regression.
**Action:**
1. Bisect via `tools/run_audit.py` on the previous tagged commit.
2. Rebuild bundle from the previous good commit (`py tools/build_bundle.py`).
3. Re-upload the previous version through the platform's plugin manager.
**Recovery:** Platform redeploys the previous version. KV is unaffected; cooldowns are ephemeral and rebuild themselves.

---

## 7 — User reports "calc didn't respond"

**Symptom:** A user says they ran `/calc` and got nothing.
**Behavior:** Most likely Discord's 3-second window expired (rare — we don't defer) or `interaction.respond` raised.
**Diagnosis:**
- Search logs for `request_id` near the user's report time.
- Look for `respond failed` warnings — that's the `_safe_respond` catch.
**Recovery:** No persistent state to repair. Have the user retry.

---

## 8 — Bad bundle (rejected at upload)

**Symptom:** Platform's upload validator rejects the bundle.
**Behavior:** New version not deployed.
**Diagnosis:**
- Run `py tools/run_audit.py` locally — the `manifest`, `imports`, `no_eval`, `plugin_run`, and `bundle` gates catch most issues before upload.
- Inspect `build/disculate.zip` — files outside the allowlist in `tools/build_bundle.py` would have been rejected during build.
**Recovery:** Fix the issue identified by the local audit; rebuild and re-upload.

---

## 9 — Clock skew on the worker

**Symptom:** Cooldown TTL or `config.updated_at` looks wrong.
**Behavior:** Cooldown could be too short or too long; `updated_at` could be unreadable.
**Action:** Trust the sandbox clock; we don't depend on absolute clock alignment for anything user-visible. `updated_at` is informational only.
**Recovery:** None needed unless the platform's time source is broken (a platform issue, not ours).

---

## 10 — Unexpected SDK exception

**Symptom:** Logs show `level:error` entries with exception types we don't explicitly catch.
**Behavior:** `_safe_respond` and the typed-exception wrappers in `lib/config.py` and `plugin.py` catch all `Exception` as last-resort. User sees the "Internal error" embed.
**Action:**
- Promote the new exception type into the explicit catch list with a specific reason code.
- Add a failure-injection test in `tests/test_failure_injection.py`.
**Recovery:** No persistent damage; the broad catch keeps the plugin alive.

---

## Thresholds for opening a Round 4 audit

Re-open a Round 4 audit if any of these hold for a week of post-deploy data:

- `result:timeout` rate exceeds 1%/day.
- `result:overflow` or `result:domain_error` rate exceeds 5%/day (suggests a missing operator or function users genuinely want).
- Worker p99 RSS exceeds 50 MB.
- Any `level:error` log with a previously-unseen exception type fires more than 0.1%/day.
- SDK assumption A1–A10 turns out wrong (`SDK-ASSUMPTIONS.md`).

Otherwise, ship is stable.
