"""Inject SDK exceptions at every external call site. Handler must
degrade gracefully, never crash, and always emit a structured log."""

from fakectx import FakeCtx, opt, slash_event
from mmo_maid_sdk import KvQuotaError, RpcTimeoutError, SdkError

import plugin as plugin_module


ADMIN_PERMS = 0x20


def test_kv_get_raises_during_config_load_falls_back_to_defaults():
    ctx = FakeCtx()

    def boom(*args, **kwargs):
        raise KvQuotaError("x")

    ctx.kv.get = boom
    event = slash_event("calc", options=[opt("expression", "1+1")])
    plugin_module.cmd_calc(ctx, event)
    # Should still respond — defaults kick in
    assert ctx.interaction.responses
    desc = ctx.interaction.responses[0]["embeds"][0]["description"]
    assert "= 2" in desc


def test_kv_set_raises_during_config_apply_returns_internal():
    ctx = FakeCtx()

    def boom(*args, **kwargs):
        raise KvQuotaError("over quota")

    ctx.kv.set = boom
    event = slash_event(
        "calc-config",
        options=[opt("precision", 3)],
        permissions=ADMIN_PERMS,
    )
    plugin_module.cmd_calc_config(ctx, event)
    assert ctx.interaction.responses
    footer = ctx.interaction.responses[0]["embeds"][0]["footer"]["text"]
    assert "internal" in footer or "error" in ctx.interaction.responses[0]["embeds"][0]["title"].lower()


def test_cooldown_check_raises_proceeds_with_calc():
    ctx = FakeCtx()

    def boom(key):
        raise RpcTimeoutError("ephemeral down")

    ctx.ephemeral.cooldown_check = boom
    event = slash_event("calc", options=[opt("expression", "1+1")])
    plugin_module.cmd_calc(ctx, event)
    # Falls open to allow the eval rather than blocking on infra failure
    assert ctx.interaction.responses
    desc = ctx.interaction.responses[0]["embeds"][0]["description"]
    assert "= 2" in desc


def test_cooldown_set_raises_does_not_block_response():
    ctx = FakeCtx()

    def boom(key, ttl_seconds=None):
        raise SdkError("cooldown_set down")

    ctx.ephemeral.cooldown_set = boom
    event = slash_event("calc", options=[opt("expression", "1+1")])
    plugin_module.cmd_calc(ctx, event)
    # The successful result still arrives
    assert ctx.interaction.responses


def test_metrics_record_raises_does_not_break_response():
    ctx = FakeCtx()

    def boom(*args, **kwargs):
        raise SdkError("metrics down")

    ctx.metrics.record = boom
    event = slash_event("calc", options=[opt("expression", "1+1")])
    plugin_module.cmd_calc(ctx, event)
    assert ctx.interaction.responses


def test_respond_itself_raising_is_logged_not_crashed():
    ctx = FakeCtx()

    def boom(**kwargs):
        raise SdkError("respond down")

    ctx.interaction.respond = boom
    event = slash_event("calc", options=[opt("expression", "1+1")])
    # Must not raise out of the handler
    plugin_module.cmd_calc(ctx, event)
    assert any(e.get("level") == "error" for e in ctx.log_entries)
