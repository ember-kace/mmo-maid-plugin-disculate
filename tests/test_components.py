"""Component round-trips — the 'Show help' button on error embeds (v0.2.15).

Covers: button render on both error stages (parse + walk), the click
round-trip, reason parsing from the END of the custom_id, stale/garbage
state, metric shielding, plus the v0.2.15 UX fixes (cooldown ceil,
server-settings field in help).
"""

from fakectx import FakeCtx, opt, slash_event

import plugin as plugin_module
from lib import config as cfg
from lib import embed as eb
from lib import reasons as R

ADMIN_PERMS = 0x20  # MANAGE_GUILD


def _component_event(custom_id, user_id="111", permissions=0):
    return {
        "type": "interaction_create",
        "interaction_type": 3,
        "custom_id": custom_id,
        "user_id": user_id,
        "permissions": str(permissions),
    }


def _first_response(ctx):
    assert ctx.interaction.responses, "no response sent"
    return ctx.interaction.responses[0]


def _embed(resp):
    embeds = resp.get("embeds", [])
    assert embeds, f"no embeds in response: {resp}"
    return embeds[0]


def _button(resp):
    rows = resp.get("components") or []
    assert rows, f"no components in response: {resp}"
    buttons = rows[0].get("components") or []
    assert buttons, f"empty action row: {rows[0]}"
    return buttons[0]


# --- button render on error paths ------------------------------------


def test_parse_error_carries_help_button_with_reason():
    ctx = FakeCtx()
    plugin_module.cmd_calc(ctx, slash_event("calc", options=[opt("expression", "((1")]))
    resp = _first_response(ctx)
    btn = _button(resp)
    assert btn["label"] == "Show help"
    assert btn["custom_id"].startswith(eb.HELP_BUTTON_CUSTOM_ID_PREFIX)
    # The id suffix matches the embed's reason footer — one source of truth.
    footer_reason = _embed(resp)["footer"]["text"].removeprefix("reason: ")
    assert btn["custom_id"] == f"{eb.HELP_BUTTON_CUSTOM_ID_PREFIX}{footer_reason}"


def test_walk_error_carries_help_button_with_reason():
    ctx = FakeCtx()
    plugin_module.cmd_calc(ctx, slash_event("calc", options=[opt("expression", "1/0")]))
    resp = _first_response(ctx)
    btn = _button(resp)
    footer_reason = _embed(resp)["footer"]["text"].removeprefix("reason: ")
    assert btn["custom_id"] == f"{eb.HELP_BUTTON_CUSTOM_ID_PREFIX}{footer_reason}"


def test_success_response_has_no_components():
    ctx = FakeCtx()
    plugin_module.cmd_calc(ctx, slash_event("calc", options=[opt("expression", "2+2")]))
    resp = _first_response(ctx)
    assert not resp.get("components")


# --- click round-trip --------------------------------------------------


def test_help_button_click_updates_error_message_in_place():
    # SDK 0.7: the button edits the (ephemeral) error message into the
    # help card rather than stacking a second ephemeral. An updated
    # message keeps its original visibility, so help stays ephemeral —
    # and the Show-help button is cleared (no components carried).
    ctx = FakeCtx()
    plugin_module.comp_show_help(ctx, _component_event("dch:help:parse_error"))
    resp = _first_response(ctx)
    assert resp.get("update_message") is True
    assert _embed(resp)["title"] == "Disculate"
    assert not resp.get("components")


def test_help_button_click_falls_back_on_pre_0_7_host():
    # A host whose respond() predates update_message= raises TypeError;
    # the help must still render, degraded to a fresh ephemeral reply.
    ctx = FakeCtx()
    real_respond = ctx.interaction.respond

    def respond(**kwargs):
        if kwargs.get("update_message"):
            raise TypeError("respond() got an unexpected keyword 'update_message'")
        return real_respond(**kwargs)

    ctx.interaction.respond = respond
    plugin_module.comp_show_help(ctx, _component_event("dch:help:overflow"))
    resp = _first_response(ctx)
    assert resp.get("ephemeral") is True
    assert "update_message" not in resp
    assert _embed(resp)["title"] == "Disculate"


def test_help_button_click_records_reason_metric():
    ctx = FakeCtx()
    plugin_module.comp_show_help(ctx, _component_event("dch:help:div_by_zero"))
    clicks = [m for m in ctx.metrics.recorded if m["name"] == "component_click"]
    assert clicks, "component_click metric not recorded"
    assert clicks[0]["tags"] == {"component": "help", "reason": "div_by_zero"}


def test_help_button_click_with_empty_reason_tags_unknown():
    # Stale or hand-crafted id with nothing after the prefix — still
    # serves help, tags the metric honestly as unknown.
    ctx = FakeCtx()
    plugin_module.comp_show_help(ctx, _component_event("dch:help:"))
    assert _embed(_first_response(ctx))["title"] == "Disculate"
    clicks = [m for m in ctx.metrics.recorded if m["name"] == "component_click"]
    assert clicks[0]["tags"]["reason"] == "unknown"


def test_help_button_click_survives_metrics_failure():
    ctx = FakeCtx()

    def boom(*a, **k):
        raise RuntimeError("metrics down")

    ctx.metrics.record = boom
    plugin_module.comp_show_help(ctx, _component_event("dch:help:overflow"))
    # Response already went out before the metric attempt; failure logged.
    assert _embed(_first_response(ctx))["title"] == "Disculate"
    assert any("metrics record failed" in e["msg"] for e in ctx.log_entries)


def test_component_handler_registered_with_prefix():
    handlers = plugin_module.plugin._handlers.get("component", {})
    assert eb.HELP_BUTTON_CUSTOM_ID_PREFIX in handlers


# --- v0.2.15 UX fixes ---------------------------------------------------


def test_cooldown_remaining_uses_ceil_not_trunc():
    ctx = FakeCtx()
    ctx.ephemeral.cooldowns["cd:calc:42"] = 1.2
    assert plugin_module._check_cooldown(ctx, "42") == 2


def test_help_embed_shows_server_settings_field():
    ctx = FakeCtx()
    cfg.apply_updates(ctx, {"precision": 3, "angle_mode": "deg"})
    plugin_module.cmd_calc_help(ctx, slash_event("calc-help"))
    embed = _embed(_first_response(ctx))
    settings = [f for f in embed["fields"] if f["name"] == "Server settings"]
    assert settings, "Server settings field missing from /calc-help"
    value = settings[0]["value"]
    assert "**3**" in value
    assert "degrees" in value
    assert "/calc-config" in value
    assert settings[0]["inline"] is False


def test_help_embed_without_config_omits_settings_field():
    embed = eb.build_help_embed()
    names = {f["name"] for f in embed.get("fields", [])}
    assert "Server settings" not in names
    assert "Getting started" not in names


# --- v0.4.0: quick-start + one-click angle toggle ----------------------


def test_help_shows_quickstart_when_never_configured():
    # Fresh server (updated_at == 0) gets the numbered quick-start, not
    # an echo of default settings.
    ctx = FakeCtx()
    plugin_module.cmd_calc_help(ctx, slash_event("calc-help"))
    embed = _embed(_first_response(ctx))
    fields = {f["name"]: f for f in embed["fields"]}
    assert "Getting started" in fields
    assert "Server settings" not in fields
    assert "1." in fields["Getting started"]["value"]


def test_help_shows_server_settings_once_configured():
    ctx = FakeCtx()
    cfg.apply_updates(ctx, {"angle_mode": "deg"})
    plugin_module.cmd_calc_help(ctx, slash_event("calc-help"))
    embed = _embed(_first_response(ctx))
    names = {f["name"] for f in embed["fields"]}
    assert "Server settings" in names
    assert "Getting started" not in names


def test_help_lists_every_command():
    ctx = FakeCtx()
    plugin_module.cmd_calc_help(ctx, slash_event("calc-help"))
    embed = _embed(_first_response(ctx))
    body = embed.get("description", "") + " ".join(
        f.get("value", "") for f in embed.get("fields", [])
    )
    for name in ("/calc", "/calc-config", "/calc-help"):
        assert name in body, f"{name} missing from /calc-help"


def test_config_view_shows_angle_toggle_button():
    ctx = FakeCtx()
    plugin_module.cmd_calc_config(
        ctx, slash_event("calc-config", options=[], permissions=ADMIN_PERMS)
    )
    btn = _button(_first_response(ctx))
    assert btn["custom_id"].startswith(eb.ANGLE_TOGGLE_CUSTOM_ID_PREFIX)
    # Default angle is radians → button offers degrees.
    assert btn["custom_id"].endswith(":deg")
    assert "degrees" in btn["label"].lower()


def test_config_update_path_carries_no_toggle():
    # An admin who set an option clearly knows the command — keep the
    # updated card clean.
    ctx = FakeCtx()
    plugin_module.cmd_calc_config(
        ctx,
        slash_event("calc-config", options=[opt("precision", 3)], permissions=ADMIN_PERMS),
    )
    assert not _first_response(ctx).get("components")


def test_angle_toggle_click_flips_mode_in_place():
    ctx = FakeCtx()
    plugin_module.comp_set_angle(
        ctx, _component_event("dcc:angle:deg", permissions=ADMIN_PERMS)
    )
    resp = _first_response(ctx)
    assert resp.get("update_message") is True
    assert ctx.kv.store[cfg.CONFIG_KEY]["angle_mode"] == "deg"
    # The refreshed card now offers the opposite (back to radians).
    assert _button(resp)["custom_id"].endswith(":rad")


def test_angle_toggle_click_requires_admin():
    ctx = FakeCtx()
    plugin_module.comp_set_angle(
        ctx, _component_event("dcc:angle:deg", permissions=0)
    )
    resp = _first_response(ctx)
    assert resp["ephemeral"] is True
    assert R.NOT_ADMIN in _embed(resp)["footer"]["text"]
    assert cfg.CONFIG_KEY not in ctx.kv.store  # nothing persisted


def test_angle_toggle_click_with_stale_target_refuses_cleanly():
    # A hand-crafted / stale custom_id with a bad target is refused via
    # the normal config-validation path, not a crash.
    ctx = FakeCtx()
    plugin_module.comp_set_angle(
        ctx, _component_event("dcc:angle:bogus", permissions=ADMIN_PERMS)
    )
    resp = _first_response(ctx)
    assert R.CONFIG_INVALID in _embed(resp)["footer"]["text"]
    assert cfg.CONFIG_KEY not in ctx.kv.store


def test_angle_toggle_click_records_component_metric():
    ctx = FakeCtx()
    plugin_module.comp_set_angle(
        ctx, _component_event("dcc:angle:deg", permissions=ADMIN_PERMS)
    )
    clicks = [m for m in ctx.metrics.recorded if m["name"] == "component_click"]
    assert clicks
    assert clicks[0]["tags"] == {"component": "angle_toggle", "reason": "deg"}


def test_angle_toggle_handler_registered_with_prefix():
    handlers = plugin_module.plugin._handlers.get("component", {})
    assert eb.ANGLE_TOGGLE_CUSTOM_ID_PREFIX in handlers
