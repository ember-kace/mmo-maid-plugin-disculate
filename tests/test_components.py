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


def _component_event(custom_id, user_id="111"):
    return {
        "type": "interaction_create",
        "interaction_type": 3,
        "custom_id": custom_id,
        "user_id": user_id,
        "permissions": "0",
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


def test_help_button_click_renders_help_ephemerally():
    ctx = FakeCtx()
    plugin_module.comp_show_help(ctx, _component_event("dch:help:parse_error"))
    resp = _first_response(ctx)
    assert resp["ephemeral"] is True
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
