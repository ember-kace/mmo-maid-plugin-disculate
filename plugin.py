"""Disculate — in-Discord calculator.

SDK assumption: MMO Maid SDK v0.5.0 (claude-mmomaid-sdk.md as of
2026-05-11). See SDK-ASSUMPTIONS.md for the inventory of unverified
behaviors (interaction.respond embeds= kwarg, member.permissions type,
ephemeral.cooldown_* return shape, user id path in interaction events).
"""

import time
from typing import Any, Dict, List, Optional, Tuple

from mmo_maid_sdk import Plugin, Context

from lib import config as cfg
from lib import embed as eb
from lib import logctx
from lib import reasons as R
from lib.format import format_result
from lib.parser import parse, uses_trig
from lib.walker import run_safe

plugin = Plugin()

PERM_MANAGE_GUILD = 0x20
PERM_ADMINISTRATOR = 0x8

COOLDOWN_SECONDS = 2
COOLDOWN_KEY_PREFIX = "cd:calc:"

LATENCY_BUCKETS = (
    (5, "<5"),
    (25, "5-25"),
    (100, "25-100"),
    (200, "100-200"),
)
LATENCY_BUCKET_OVER = ">200"


def _latency_bucket(ms: float) -> str:
    for threshold, label in LATENCY_BUCKETS:
        if ms < threshold:
            return label
    return LATENCY_BUCKET_OVER


def _user_id(event: Dict[str, Any]) -> str:
    # Observed SDK shape (v0.5.0 runtime, May 2026): user_id is a flat
    # top-level string. Falls back to the nested member.user.id /
    # user.id shapes that the SDK docs example used, in case the SDK
    # ever normalises differently.
    uid = event.get("user_id")
    if isinstance(uid, (str, int)):
        return str(uid)
    member = event.get("member")
    if isinstance(member, dict):
        user = member.get("user")
        if isinstance(user, dict):
            uid = user.get("id")
            if isinstance(uid, (str, int)):
                return str(uid)
    user = event.get("user")
    if isinstance(user, dict):
        uid = user.get("id")
        if isinstance(uid, (str, int)):
            return str(uid)
    return "unknown"


def _is_admin(event: Dict[str, Any]) -> bool:
    perms_raw = event.get("permissions")
    if perms_raw is None:
        member = event.get("member") or {}
        perms_raw = member.get("permissions", 0)
    if isinstance(perms_raw, bool):
        return False
    try:
        perms = int(perms_raw)
    except (TypeError, ValueError):
        return False
    return bool(perms & (PERM_MANAGE_GUILD | PERM_ADMINISTRATOR))


def _options(event: Dict[str, Any]) -> Dict[str, Any]:
    """Extract slash-command args from the SDK event payload.

    Observed shape (v0.5.0): event["command_options"] is a flat list of
    {"name", "value"} dicts. SDK doc's example used "options", and the
    raw Discord shape nests under "data.options" — we check all three,
    but treat each slot as a list-of-dicts only when it actually is one.
    Malformed shapes (strings, numbers, dicts in the wrong slot) fail
    closed: empty dict, no exception. Pre-v0.2.9 the data fallback
    called `.get` on whatever was at event["data"] and raised
    AttributeError when that wasn't a dict.
    """
    out: Dict[str, Any] = {}
    raw: Any = None
    for slot in ("command_options", "options"):
        candidate = event.get(slot)
        if isinstance(candidate, list):
            raw = candidate
            break
    if raw is None:
        data = event.get("data")
        if isinstance(data, dict):
            candidate = data.get("options")
            if isinstance(candidate, list):
                raw = candidate
    if raw is None:
        return out
    for opt in raw:
        if isinstance(opt, dict) and "name" in opt:
            out[opt["name"]] = opt.get("value")
    return out


def _safe_respond(ctx: Context, **kwargs: Any) -> None:
    kwargs.setdefault("allowed_mentions", eb.ALLOWED_MENTIONS_NONE)
    try:
        ctx.interaction.respond(**kwargs)
    except Exception as e:
        logctx.log_error(ctx, "respond failed", err=str(e))


def _record_metric(ctx: Context, result_tag: str, started_at: float) -> None:
    """Emit calc_eval + calc_latency_ms metrics.

    `started_at` is seeded at handler entry, so elapsed covers the full
    handler — parse + config read + walker + format + respond — not
    just the walker. The bucket tag (`<5`, `5-25`, ..., `>200`) gives
    the resolution that matters; the raw value is a coarse aggregate.
    """
    elapsed_ms = (time.monotonic() - started_at) * 1000.0
    try:
        ctx.metrics.record("calc_eval", value=1, tags={"result": result_tag})
        ctx.metrics.record(
            "calc_latency_ms",
            value=int(elapsed_ms),
            tags={"bucket": _latency_bucket(elapsed_ms)},
        )
    except Exception as e:
        logctx.log_warn(ctx, "metrics record failed", err=str(e))


def _check_cooldown(ctx: Context, user_id: str) -> Optional[int]:
    key = f"{COOLDOWN_KEY_PREFIX}{user_id}"
    try:
        status = ctx.ephemeral.cooldown_check(key)
    except Exception as e:
        logctx.log_warn(ctx, "cooldown_check failed", err=str(e))
        return None
    if not isinstance(status, dict):
        return None
    if not status.get("active"):
        return None
    remaining = status.get("remaining_seconds", COOLDOWN_SECONDS)
    try:
        return int(remaining)
    except (TypeError, ValueError):
        return COOLDOWN_SECONDS


def _set_cooldown(ctx: Context, user_id: str) -> None:
    key = f"{COOLDOWN_KEY_PREFIX}{user_id}"
    try:
        ctx.ephemeral.cooldown_set(key, ttl_seconds=COOLDOWN_SECONDS)
    except Exception as e:
        logctx.log_warn(ctx, "cooldown_set failed", err=str(e))


@plugin.on_ready
def on_ready(ctx: Context):
    logctx.new_request_id()
    logctx.log_info(ctx, "disculate booted", server_id=ctx.server_id)


@plugin.on_slash_command("calc")
def cmd_calc(ctx: Context, event: Dict[str, Any]):
    logctx.new_request_id()
    started = time.monotonic()
    opts = _options(event)
    raw_expression = opts.get("expression", "")
    ephemeral = bool(opts.get("ephemeral", False))
    user_id = _user_id(event)

    remaining = _check_cooldown(ctx, user_id)
    if remaining is not None and remaining > 0:
        _safe_respond(
            ctx,
            embeds=[eb.build_cooldown_embed(remaining)],
            ephemeral=True,
        )
        _record_metric(ctx, R.COOLDOWN, started)
        return

    tree, parse_reason, parse_detail = parse(raw_expression)
    if parse_reason is not None:
        _safe_respond(
            ctx,
            embeds=[eb.build_error_embed(
                raw_expression if isinstance(raw_expression, str) else "",
                parse_reason,
                parse_detail,
            )],
            ephemeral=True,
        )
        _set_cooldown(ctx, user_id)
        _record_metric(ctx, parse_reason, started)
        return

    config = cfg.get_config(ctx)
    trace: List[Any] = []
    value, eval_reason, eval_detail = run_safe(tree, angle_mode=config["angle_mode"], trace=trace)
    if eval_reason is not None:
        _safe_respond(
            ctx,
            embeds=[eb.build_error_embed(raw_expression, eval_reason, eval_detail)],
            ephemeral=True,
        )
        _set_cooldown(ctx, user_id)
        _record_metric(ctx, eval_reason, started)
        return

    try:
        result_text = format_result(
            value,
            precision=config["precision"],
            scientific_threshold=config["scientific_threshold"],
        )
    except Exception as e:
        logctx.log_error(ctx, "format failed", err=str(e))
        _safe_respond(
            ctx,
            embeds=[eb.build_error_embed(raw_expression, R.INTERNAL)],
            ephemeral=True,
        )
        _set_cooldown(ctx, user_id)
        _record_metric(ctx, R.INTERNAL, started)
        return

    # Smart auto: render the Steps field only when there are >= 2
    # traceable nodes. For `2+2`, `sqrt(2)`, or `min(3,1,4)` the trace
    # has < 2 entries and there's nothing meaningful to list, so the
    # card stays clean.
    steps_text = None
    if len(trace) >= 2:
        steps_text = eb.format_steps(
            trace,
            precision=config["precision"],
            scientific_threshold=config["scientific_threshold"],
        )

    _safe_respond(
        ctx,
        embeds=[eb.build_result_embed(
            raw_expression,
            result_text,
            config["angle_mode"],
            uses_trig=uses_trig(tree),
            steps_text=steps_text,
        )],
        ephemeral=ephemeral,
    )
    _set_cooldown(ctx, user_id)
    _record_metric(ctx, R.OK, started)


def _record_config(ctx: Context, result: str, field: str = "none") -> None:
    try:
        ctx.metrics.record(
            "config_change",
            value=1,
            tags={"result": result, "field": field},
        )
    except Exception as e:
        logctx.log_warn(ctx, "metrics record failed", err=str(e))


@plugin.on_slash_command("calc-config")
def cmd_calc_config(ctx: Context, event: Dict[str, Any]):
    logctx.new_request_id()
    if not _is_admin(event):
        _safe_respond(
            ctx,
            embeds=[eb.build_error_embed("", R.NOT_ADMIN)],
            ephemeral=True,
        )
        _record_config(ctx, R.NOT_ADMIN)
        return

    opts = _options(event)
    precision = opts.get("precision")
    angle_mode = opts.get("angle_mode")
    scientific_threshold = opts.get("scientific_threshold")

    updates, errors = cfg.validate_updates(
        precision=precision if precision is not None else None,
        angle_mode=angle_mode if angle_mode is not None else None,
        scientific_threshold=scientific_threshold if scientific_threshold is not None else None,
    )
    if errors:
        _safe_respond(
            ctx,
            embeds=[eb.build_config_error_embed(errors)],
            ephemeral=True,
        )
        _record_config(ctx, R.CONFIG_INVALID)
        return

    try:
        merged = cfg.apply_updates(ctx, updates)
    except Exception as e:
        logctx.log_error(ctx, "config apply failed", err=str(e))
        _safe_respond(
            ctx,
            embeds=[eb.build_error_embed("", R.INTERNAL)],
            ephemeral=True,
        )
        _record_config(ctx, R.INTERNAL)
        return

    changed: List[str] = list(updates.keys())
    _safe_respond(
        ctx,
        embeds=[eb.build_config_embed(merged, changed)],
        ephemeral=True,
    )
    if changed:
        for field in changed:
            _record_config(ctx, "ok", field=field)
    else:
        _record_config(ctx, "ok", field="none")


@plugin.on_slash_command("calc-help")
def cmd_calc_help(ctx: Context, event: Dict[str, Any]):
    logctx.new_request_id()
    _safe_respond(
        ctx,
        embeds=[eb.build_help_embed()],
        ephemeral=True,
    )


plugin.run()
