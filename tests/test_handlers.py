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
    assert "= 4" in desc
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
    assert "= 1" in desc


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
    # Tokens may live in the description OR in any field value after the
    # v0.2.3 field-grid refactor. Search the union.
    body = embed.get("description", "") + " ".join(
        f.get("value", "") for f in embed.get("fields", [])
    ) + " " + (embed.get("footer") or {}).get("text", "")
    for token in ("pi", "sqrt", "/calc-config"):
        assert token in body, f"{token} not surfaced in help embed"


def test_help_embed_uses_field_grid():
    """Lock the field-grid layout (v0.2.3) against future regression."""
    from lib.functions import CATEGORY_ORDER
    ctx = FakeCtx()
    plugin_module.cmd_calc_help(ctx, slash_event("calc-help"))
    embed = _embed(_first_response(ctx))
    field_names = {f["name"] for f in embed.get("fields", [])}
    # Every function category appears as its own field.
    for _, label in CATEGORY_ORDER:
        assert label in field_names, f"{label} category missing as a field"
    # Notes field is full-width (non-inline) — it's the operational
    # caveats block.
    notes_field = next((f for f in embed["fields"] if f["name"] == "Notes"), None)
    assert notes_field is not None and notes_field.get("inline") is False
    # Category fields are inline so Discord packs them as a grid.
    for f in embed["fields"]:
        if f["name"] != "Notes":
            assert f.get("inline") is True, f"{f['name']} should be inline"


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
    assert "= 10" in desc


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
    # T3-02: implicit-multiplication idioms get a specific hint instead
    # of a generic parse_error. v0.2.6 extends coverage to the symmetric
    # `)<digit>` / `)<letter>` cases on top of the original
    # `<digit>(` / `<digit><letter>` cases.
    for expr in (
        "2(3)",          # digit then paren
        "2pi",           # digit then letter
        "3 (5)",         # digit then space then paren
        "(1 + 1) 10",    # close-paren then space then digit  (v0.2.6)
        "(1 + 1)10",     # close-paren then digit             (v0.2.6)
        "(1 + 1) pi",    # close-paren then space then name   (v0.2.6)
    ):
        ctx = FakeCtx()
        plugin_module.cmd_calc(ctx, slash_event("calc", options=[opt("expression", expr)]))
        embed = _embed(_first_response(ctx))
        assert R.WANT_EXPLICIT_MULT in embed["footer"]["text"], expr


def test_calc_with_real_sdk_event_shape_evaluates_expression():
    # Regression: production logs (May 2026) showed every /calc returning
    # EMPTY because the SDK delivers `command_options`, not `options`,
    # and `user_id` as a top-level string, not nested in `member.user.id`.
    # Lock the actual observed shape against future drift.
    ctx = FakeCtx()
    real_event = {
        "type": "interaction_create",
        "interaction_type": 2,
        "command_name": "calc",
        "user_id": "627259696343941120",
        "guild_id": "1503442627750531274",
        "channel_id": "1503472480785010910",
        "user_username": "openshift",
        "permissions": "8",  # ADMINISTRATOR bit
        "command_options": [
            {"name": "expression", "type": 3, "value": "3+6"},
        ],
        "modal_values": {},
        "values": [],
        "custom_id": "",
        "component_type": 0,
        "interaction_id": "1503780492552700147",
    }
    plugin_module.cmd_calc(ctx, real_event)
    resp = ctx.interaction.responses[0]
    desc = resp["embeds"][0]["description"]
    assert "= 9" in desc, f"got desc: {desc}"
    # Cooldown key should use the real user_id, not the fallback "unknown".
    cd_keys = list(ctx.ephemeral.cooldowns.keys())
    assert any("627259696343941120" in k for k in cd_keys), cd_keys


def test_calc_shows_steps_field_for_compound_expression():
    """v0.2.4: Steps field appears when AST has >= 2 traceable nodes."""
    ctx = FakeCtx()
    plugin_module.cmd_calc(ctx, slash_event("calc", options=[opt("expression", "(2+1)*7-8")]))
    embed = _embed(_first_response(ctx))
    fields = embed.get("fields", [])
    steps_field = next((f for f in fields if f["name"] == "Steps"), None)
    assert steps_field is not None, f"Steps field missing; fields={fields}"
    assert steps_field["inline"] is False, "Steps field must be full-width"
    value = steps_field["value"]
    # Numbered list with three entries leading to the final 13.
    assert "1." in value and "2." in value and "3." in value
    assert "= `13`" in value


def test_calc_shows_steps_field_for_nested_function_calls():
    ctx = FakeCtx()
    plugin_module.cmd_calc(ctx, slash_event("calc", options=[opt("expression", "sqrt(abs(-16))")]))
    embed = _embed(_first_response(ctx))
    steps_field = next((f for f in embed.get("fields", []) if f["name"] == "Steps"), None)
    assert steps_field is not None
    value = steps_field["value"]
    # Inner abs first, then outer sqrt.
    assert "abs(-16)" in value
    assert "sqrt(16)" in value


def test_calc_omits_steps_field_for_trivial_expression():
    ctx = FakeCtx()
    plugin_module.cmd_calc(ctx, slash_event("calc", options=[opt("expression", "2+2")]))
    embed = _embed(_first_response(ctx))
    fields = embed.get("fields", [])
    assert not any(f["name"] == "Steps" for f in fields), \
        "Steps field should be absent for a single-BinOp expression"


def test_calc_omits_steps_field_for_single_function_call():
    ctx = FakeCtx()
    plugin_module.cmd_calc(ctx, slash_event("calc", options=[opt("expression", "min(3, 1, 4, 1, 5)")]))
    embed = _embed(_first_response(ctx))
    fields = embed.get("fields", [])
    assert not any(f["name"] == "Steps" for f in fields)


def test_calc_steps_field_respects_precision_config():
    """Step values share the same precision/scientific config as the final result."""
    from lib import config as cfg
    ctx = FakeCtx()
    cfg.apply_updates(ctx, {"precision": 2})
    # Bust the cooldown set by the apply_updates pathway? It's a config write,
    # not a calc cooldown, so we're fine. But config doesn't set cooldown either.
    plugin_module.cmd_calc(ctx, slash_event("calc", options=[opt("expression", "1/3 + 1/6")]))
    embed = _embed(_first_response(ctx))
    steps_field = next((f for f in embed["fields"] if f["name"] == "Steps"), None)
    assert steps_field is not None
    # 6-decimal default rendering would emit "0.333333"; precision=2 must NOT.
    assert "0.333333" not in steps_field["value"]


def test_calc_expression_echo_preserves_pow_operator():
    """v0.2.7: `**` is a valid math operator and must survive into the
    expression echo. Pre-v0.2.7, safe_text stripped it defensively,
    making the displayed expression lie about what the user typed
    (e.g., `2**8` rendered as `2  8` with double space)."""
    ctx = FakeCtx()
    plugin_module.cmd_calc(ctx, slash_event("calc", options=[opt("expression", "2**8")]))
    embed = _embed(_first_response(ctx))
    desc = embed["description"]
    assert "`2**8`" in desc, f"** should survive into the expression echo; got: {desc!r}"
    assert "= 256" in desc


def test_calc_expression_echo_preserves_pow_in_error_path():
    """Same scrub fix applies to the error embed echo."""
    ctx = FakeCtx()
    # Force a parse error after `**` so we exercise the error builder.
    # `2**` has a trailing operator -> parse_error.
    plugin_module.cmd_calc(ctx, slash_event("calc", options=[opt("expression", "2**")]))
    embed = _embed(_first_response(ctx))
    desc = embed["description"]
    assert "`2**`" in desc, f"** should survive into the error echo; got: {desc!r}"


def test_calc_result_embed_carries_brand_thumbnail():
    """v0.2.5: success embeds carry the Disculate avatar in the top-right."""
    from lib.embed import BRAND_THUMBNAIL_URL
    ctx = FakeCtx()
    plugin_module.cmd_calc(ctx, slash_event("calc", options=[opt("expression", "2+2")]))
    embed = _embed(_first_response(ctx))
    assert embed.get("thumbnail", {}).get("url") == BRAND_THUMBNAIL_URL


def test_help_embed_carries_brand_thumbnail():
    from lib.embed import BRAND_THUMBNAIL_URL
    ctx = FakeCtx()
    plugin_module.cmd_calc_help(ctx, slash_event("calc-help"))
    embed = _embed(_first_response(ctx))
    assert embed.get("thumbnail", {}).get("url") == BRAND_THUMBNAIL_URL


def test_config_updated_embed_carries_brand_thumbnail():
    from lib.embed import BRAND_THUMBNAIL_URL
    ctx = FakeCtx()
    plugin_module.cmd_calc_config(
        ctx,
        slash_event("calc-config", options=[opt("precision", 3)], permissions=0x20),
    )
    embed = _embed(_first_response(ctx))
    assert embed.get("thumbnail", {}).get("url") == BRAND_THUMBNAIL_URL


def test_error_embed_has_no_brand_thumbnail():
    """v0.2.5: errors stay plain — brand on a red error feels off-tone."""
    ctx = FakeCtx()
    plugin_module.cmd_calc(ctx, slash_event("calc", options=[opt("expression", "1/0")]))
    embed = _embed(_first_response(ctx))
    assert "thumbnail" not in embed


def test_cooldown_embed_has_no_brand_thumbnail():
    """v0.2.5: cooldown notice is small; thumbnail would overwhelm it."""
    ctx = FakeCtx()
    event = slash_event("calc", options=[opt("expression", "1+1")], user_id="42")
    plugin_module.cmd_calc(ctx, event)
    ctx.interaction.responses.clear()
    plugin_module.cmd_calc(ctx, event)  # second call trips cooldown
    embed = _embed(_first_response(ctx))
    assert "thumbnail" not in embed


def test_config_current_embed_has_no_brand_thumbnail():
    """v0.2.5: read-only /calc-config (no fields changed) is informational, not success."""
    ctx = FakeCtx()
    plugin_module.cmd_calc_config(
        ctx,
        slash_event("calc-config", options=[], permissions=0x20),
    )
    embed = _embed(_first_response(ctx))
    assert "thumbnail" not in embed


def test_calc_unknown_function_typo_suggests_in_error_embed():
    """v0.2.8: diagnostic explainer surfaces did-you-mean for close typos."""
    ctx = FakeCtx()
    plugin_module.cmd_calc(ctx, slash_event("calc", options=[opt("expression", "sqirt(2)")]))
    embed = _embed(_first_response(ctx))
    desc = embed["description"]
    assert "sqirt" in desc
    assert "sqrt" in desc  # the suggestion


def test_calc_pi_case_mismatch_suggests_pi_in_error_embed():
    """v0.2.8: case-mismatch is the strongest did-you-mean signal."""
    ctx = FakeCtx()
    plugin_module.cmd_calc(ctx, slash_event("calc", options=[opt("expression", "Pi + 1")]))
    embed = _embed(_first_response(ctx))
    desc = embed["description"]
    assert "case-sensitive" in desc.lower()
    assert "`pi`" in desc


def test_calc_unclosed_paren_diagnoses_imbalance_in_error_embed():
    """v0.2.8: parser pattern detection identifies missing close-paren."""
    ctx = FakeCtx()
    plugin_module.cmd_calc(ctx, slash_event("calc", options=[opt("expression", "((1+2)")]))
    embed = _embed(_first_response(ctx))
    desc = embed["description"]
    assert "Unclosed" in desc


def test_calc_sqrt_negative_diagnostic_names_function_and_suggests_abs():
    """v0.2.8: domain error carries function name → context-specific advice."""
    ctx = FakeCtx()
    plugin_module.cmd_calc(ctx, slash_event("calc", options=[opt("expression", "sqrt(-1)")]))
    embed = _embed(_first_response(ctx))
    desc = embed["description"]
    assert "sqrt" in desc
    assert "abs" in desc


def test_calc_div_by_zero_diagnostic_names_operator():
    """v0.2.8: div-by-zero carries the operator symbol."""
    ctx = FakeCtx()
    plugin_module.cmd_calc(ctx, slash_event("calc", options=[opt("expression", "1/0")]))
    embed = _embed(_first_response(ctx))
    desc = embed["description"]
    assert "`/`" in desc


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
    assert "= 4" in desc
