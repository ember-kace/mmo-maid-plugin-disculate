import pytest

from fakectx import FakeCtx, opt, slash_event

import plugin as plugin_module
from lib import config as cfg
from lib import reasons as R

ADMIN_PERMS = 0x20  # MANAGE_GUILD


def _first_response(ctx):
    assert ctx.interaction.responses, "no response sent"
    return ctx.interaction.responses[0]


def _embed(resp):
    embeds = resp.get("embeds", [])
    assert embeds, f"no embeds in response: {resp}"
    return embeds[0]


def test_calc_happy_path_public():
    ctx = FakeCtx()
    event = slash_event("calc", options=[opt("expression", "2+2")])
    plugin_module.cmd_calc(ctx, event)
    resp = _first_response(ctx)
    assert resp.get("ephemeral") is False
    desc = _embed(resp)["description"]
    assert "2+2" in desc
    assert "**4**" in desc
    metric_names = {m["name"] for m in ctx.metrics.recorded}
    assert "calc_eval" in metric_names
    assert "calc_latency_ms" in metric_names


def test_calc_ephemeral_flag_honored():
    ctx = FakeCtx()
    event = slash_event("calc", options=[opt("expression", "1+1"), opt("ephemeral", True)])
    plugin_module.cmd_calc(ctx, event)
    assert _first_response(ctx)["ephemeral"] is True


def test_calc_blocks_attribute_access():
    ctx = FakeCtx()
    event = slash_event("calc", options=[opt("expression", "(1).__class__")])
    plugin_module.cmd_calc(ctx, event)
    resp = _first_response(ctx)
    embed = _embed(resp)
    assert resp["ephemeral"] is True
    assert "reason" in embed["footer"]["text"]


def test_calc_cooldown_blocks_second_call():
    ctx = FakeCtx()
    event = slash_event("calc", options=[opt("expression", "1+1")], user_id="42")
    plugin_module.cmd_calc(ctx, event)
    ctx.interaction.responses.clear()
    plugin_module.cmd_calc(ctx, event)
    resp = _first_response(ctx)
    assert resp["ephemeral"] is True
    embed = _embed(resp)
    assert "Slow down" in embed["title"]


def test_calc_div_by_zero_returns_error_embed():
    ctx = FakeCtx()
    event = slash_event("calc", options=[opt("expression", "1/0")])
    plugin_module.cmd_calc(ctx, event)
    resp = _first_response(ctx)
    assert resp["ephemeral"] is True
    assert R.DIV_BY_ZERO in _embed(resp)["footer"]["text"]


def test_calc_uses_per_server_angle_mode():
    ctx = FakeCtx()
    cfg.apply_updates(ctx, {"angle_mode": "deg"})
    event = slash_event("calc", options=[opt("expression", "sin(90)")])
    plugin_module.cmd_calc(ctx, event)
    desc = _embed(_first_response(ctx))["description"]
    assert "**1**" in desc


def test_calc_uses_per_server_precision():
    ctx = FakeCtx()
    cfg.apply_updates(ctx, {"precision": 2})
    event = slash_event("calc", options=[opt("expression", "1/3")])
    plugin_module.cmd_calc(ctx, event)
    desc = _embed(_first_response(ctx))["description"]
    assert "0.33" in desc
    assert "0.333" not in desc


def test_calc_allowed_mentions_set_to_none():
    ctx = FakeCtx()
    event = slash_event("calc", options=[opt("expression", "1+1")])
    plugin_module.cmd_calc(ctx, event)
    resp = _first_response(ctx)
    assert resp["allowed_mentions"] == {"parse": []}


def test_calc_config_requires_admin():
    ctx = FakeCtx()
    event = slash_event("calc-config", options=[opt("precision", 4)], permissions=0)
    plugin_module.cmd_calc_config(ctx, event)
    resp = _first_response(ctx)
    assert resp["ephemeral"] is True
    assert R.NOT_ADMIN in _embed(resp)["footer"]["text"]


def test_calc_config_admin_can_update():
    ctx = FakeCtx()
    event = slash_event(
        "calc-config",
        options=[opt("precision", 3), opt("angle_mode", "deg")],
        permissions=ADMIN_PERMS,
    )
    plugin_module.cmd_calc_config(ctx, event)
    resp = _first_response(ctx)
    assert resp["ephemeral"] is True
    embed = _embed(resp)
    assert "updated" in embed["title"].lower()
    # Verify it actually persisted
    stored = ctx.kv.store.get(cfg.CONFIG_KEY)
    assert stored["precision"] == 3
    assert stored["angle_mode"] == "deg"


def test_calc_config_rejects_invalid_range():
    ctx = FakeCtx()
    event = slash_event(
        "calc-config",
        options=[opt("precision", 99)],
        permissions=ADMIN_PERMS,
    )
    plugin_module.cmd_calc_config(ctx, event)
    embed = _embed(_first_response(ctx))
    assert R.CONFIG_INVALID in embed["footer"]["text"]


def test_calc_config_no_options_shows_current():
    ctx = FakeCtx()
    event = slash_event("calc-config", options=[], permissions=ADMIN_PERMS)
    plugin_module.cmd_calc_config(ctx, event)
    embed = _embed(_first_response(ctx))
    assert "Current settings" in embed["title"] or "updated" in embed["title"].lower()


def test_calc_help_returns_help_embed():
    ctx = FakeCtx()
    plugin_module.cmd_calc_help(ctx, slash_event("calc-help"))
    resp = _first_response(ctx)
    assert resp["ephemeral"] is True
    embed = _embed(resp)
    assert "Disculate" in embed["title"]
    desc = embed["description"]
    for token in ("pi", "sqrt", "/calc-config"):
        assert token in desc


def test_calc_user_id_unknown_uses_fallback_cooldown_key():
    ctx = FakeCtx()
    event = {
        "type": "interaction_create",
        "name": "calc",
        "options": [opt("expression", "1+1")],
    }
    plugin_module.cmd_calc(ctx, event)
    cd_keys = [k for k in ctx.ephemeral.cooldowns if "calc:" in k]
    assert cd_keys, "no cooldown set"
    assert "unknown" in cd_keys[0]


def test_calc_admin_perms_int_form_accepted():
    ctx = FakeCtx()
    event = {
        "type": "interaction_create",
        "name": "calc-config",
        "member": {"user": {"id": "x"}, "permissions": ADMIN_PERMS},  # int, not str
        "options": [opt("precision", 5)],
    }
    plugin_module.cmd_calc_config(ctx, event)
    resp = _first_response(ctx)
    assert "updated" in _embed(resp)["title"].lower()


def test_calc_emits_metrics_with_bounded_tag_values():
    ctx = FakeCtx()
    event = slash_event("calc", options=[opt("expression", "1/0")])
    plugin_module.cmd_calc(ctx, event)
    eval_metric = next(m for m in ctx.metrics.recorded if m["name"] == "calc_eval")
    assert eval_metric["tags"]["result"] in R.ALL_REASONS or eval_metric["tags"]["result"] == "ok"


def test_calc_percent_evaluates():
    ctx = FakeCtx()
    event = slash_event("calc", options=[opt("expression", "200 * 5%")])
    plugin_module.cmd_calc(ctx, event)
    desc = _embed(_first_response(ctx))["description"]
    assert "**10**" in desc


def test_calc_footer_present_only_when_trig_used():
    # T2-02: angle-mode footer is noise on non-trig results.
    ctx = FakeCtx()
    plugin_module.cmd_calc(ctx, slash_event("calc", options=[opt("expression", "2+2")]))
    embed = _embed(_first_response(ctx))
    assert "footer" not in embed, "footer should be absent for non-trig results"

    # Reset cooldown bucket for second call
    ctx.ephemeral.cooldowns.clear()
    ctx.interaction.responses.clear()
    plugin_module.cmd_calc(ctx, slash_event("calc", options=[opt("expression", "sin(0)")]))
    embed = _embed(_first_response(ctx))
    assert "footer" in embed
    assert "angle" in embed["footer"]["text"]


def test_calc_footer_absent_for_hyperbolic_functions():
    # uses_trig must mean "uses something that honors angle_mode", not
    # "uses any function math people call trig." Hyperbolic functions
    # don't honor angle_mode, so sinh/cosh/tanh should NOT show the footer.
    ctx = FakeCtx()
    for expr in ("sinh(1)", "cosh(0)", "tanh(0)"):
        ctx.ephemeral.cooldowns.clear()
        ctx.interaction.responses.clear()
        plugin_module.cmd_calc(ctx, slash_event("calc", options=[opt("expression", expr)]))
        embed = _embed(_first_response(ctx))
        assert "footer" not in embed, f"{expr} should not have an angle footer"


def test_calc_footer_present_for_inverse_trig():
    # Inverse trig honors angle_mode (output is in radians or degrees),
    # so the footer SHOULD appear.
    ctx = FakeCtx()
    for expr in ("asin(0)", "acos(1)", "atan(1)", "atan2(1, 1)"):
        ctx.ephemeral.cooldowns.clear()
        ctx.interaction.responses.clear()
        plugin_module.cmd_calc(ctx, slash_event("calc", options=[opt("expression", expr)]))
        embed = _embed(_first_response(ctx))
        assert "footer" in embed, f"{expr} should have an angle footer"


def test_calc_caret_emits_want_power_hint():
    ctx = FakeCtx()
    plugin_module.cmd_calc(ctx, slash_event("calc", options=[opt("expression", "2^3")]))
    embed = _embed(_first_response(ctx))
    assert R.WANT_POWER in embed["footer"]["text"]


def test_calc_percent_modulo_collision_emits_want_mod():
    # T5-03: `5 % 3` now reaches the Mod operator path and emits a
    # specific hint pointing at mod(a, b).
    ctx = FakeCtx()
    plugin_module.cmd_calc(ctx, slash_event("calc", options=[opt("expression", "5 % 3")]))
    embed = _embed(_first_response(ctx))
    assert R.WANT_MOD in embed["footer"]["text"]


def test_calc_implicit_multiplication_emits_want_explicit_mult():
    # T3-02: `2(3)` and `2pi` are calculator-keyboard idioms that mean
    # implicit multiplication. Both should produce a specific hint.
    for expr in ("2(3)", "2pi", "3 (5)"):
        ctx = FakeCtx()
        plugin_module.cmd_calc(ctx, slash_event("calc", options=[opt("expression", expr)]))
        embed = _embed(_first_response(ctx))
        assert R.WANT_EXPLICIT_MULT in embed["footer"]["text"], expr


def test_calc_works_when_ephemeral_raises():
    # T5-05: ephemeral subsystem failures must not block evaluation.
    # The plugin falls open (cooldown ineffective) but still answers.
    from mmo_maid_sdk import SdkError
    ctx = FakeCtx()

    def cooldown_check_boom(_key):
        raise SdkError("ephemeral down")

    def cooldown_set_boom(_key, ttl_seconds=None):
        raise SdkError("ephemeral down")

    ctx.ephemeral.cooldown_check = cooldown_check_boom
    ctx.ephemeral.cooldown_set = cooldown_set_boom
    plugin_module.cmd_calc(ctx, slash_event("calc", options=[opt("expression", "2+2")]))
    assert ctx.interaction.responses, "no response despite ephemeral failure"
    desc = _embed(_first_response(ctx))["description"]
    assert "**4**" in desc
