"""Inputs an attacker might use. Each one must be either rejected
explicitly or produce a sanitized output. Nothing here should crash."""

import pytest

from fakectx import FakeCtx, opt, slash_event
from lib import embed as eb
from lib import reasons as R
from lib.parser import parse

import plugin as plugin_module


def _run(ctx, expression):
    event = slash_event("calc", options=[opt("expression", expression)])
    plugin_module.cmd_calc(ctx, event)
    return ctx.interaction.responses[0]


@pytest.mark.parametrize("payload", [
    "1+1‮",          # RLO bidi
    "1+‪1‬",    # LRE + PDF
    "1+‎1",          # LRM
    "1+‏1",          # RLM
    "1+⁦hidden⁩",  # FSI/PDI
])
def test_bidi_input_rejected(payload):
    _, reason, _ = parse(payload)
    assert reason == R.INVALID_CHARS


@pytest.mark.parametrize("payload", [
    "1+\x001",     # NUL mid-string
    "1+\x011",     # SOH mid-string
    "1+\x1f1",     # US mid-string (note: trailing 0x1c-0x1f is treated
                   # as whitespace by str.strip() and removed, which is safe)
    "1+\x7f1",     # DEL mid-string
])
def test_control_chars_in_body_rejected(payload):
    _, reason, _ = parse(payload)
    assert reason == R.INVALID_CHARS


def test_full_width_digits_normalized_and_accepted():
    tree, reason, _ = parse("１+１")  # １+１ → 1+1
    assert reason is None
    assert tree is not None


def test_homoglyph_at_everyone_neutralized_in_output():
    # The contiguous string "@everyone" must not appear in the output —
    # safe_text inserts a zero-width space between @ and everyone, which
    # defeats Discord's mention parser.
    embed_dict = eb.build_error_embed("@everyone 1/0", R.DIV_BY_ZERO)
    desc = embed_dict["description"]
    assert "@everyone" not in desc
    assert "@​everyone" in desc


def test_markdown_link_injection_stripped_in_output():
    embed_dict = eb.build_error_embed("[click](http://evil)", R.PARSE_ERROR)
    desc = embed_dict["description"]
    assert "http://evil" not in desc
    assert "[click](" not in desc


def test_triple_backtick_injection_stripped():
    embed_dict = eb.build_error_embed("```python\nprint('pwn')```", R.PARSE_ERROR)
    desc = embed_dict["description"]
    assert "```" not in desc


def test_dos_attempt_huge_pow_returns_overflow():
    ctx = FakeCtx()
    resp = _run(ctx, "9**99999")
    embed = resp["embeds"][0]
    assert R.OVERFLOW in embed["footer"]["text"]


def test_dos_attempt_chained_pow_caught():
    ctx = FakeCtx()
    # 2**2**1000 chains 2**(2**1000). The inner 2**1000 trips pow guard.
    resp = _run(ctx, "2**(2**1000)")
    embed = resp["embeds"][0]
    footer = embed["footer"]["text"]
    assert any(r in footer for r in (R.OVERFLOW, R.TIMEOUT, R.DOMAIN_ERROR))


def test_dos_attempt_oversize_input_rejected():
    ctx = FakeCtx()
    big = "1" + ("+1" * 100)  # 201 chars
    resp = _run(ctx, big)
    embed = resp["embeds"][0]
    assert R.TOO_LONG in embed["footer"]["text"]


def test_dos_attempt_deep_binop_chain_rejected():
    ctx = FakeCtx()
    # Python's parser collapses redundant parens (no nodes for them) so a
    # parenthesis-bomb does not produce a deep tree. Build a real left-assoc
    # BinOp chain instead: 32 additions produces depth 33.
    nest = "+".join(["1"] * 33)
    resp = _run(ctx, nest)
    embed = resp["embeds"][0]
    footer = embed["footer"]["text"]
    assert any(r in footer for r in (R.DEPTH_EXCEEDED, R.PARSE_ERROR))


def test_attribute_access_blocked():
    ctx = FakeCtx()
    for payload in [
        "(1).__class__",
        "((1).__class__).__bases__",
        "(1).real",
    ]:
        ctx.interaction.responses.clear()
        # Each call sets cooldown — bypass by using fresh user
        ctx.ephemeral.cooldowns.clear()
        resp = _run(ctx, payload)
        embed = resp["embeds"][0]
        assert R.UNSUPPORTED_NODE in embed["footer"]["text"]


def test_call_with_keyword_arg_blocked():
    ctx = FakeCtx()
    resp = _run(ctx, "round(1.5, ndigits=1)")
    embed = resp["embeds"][0]
    assert R.UNSUPPORTED_NODE in embed["footer"]["text"]


def test_format_string_injection_blocked():
    # f-strings parse as JoinedStr / FormattedValue
    _, reason, _ = parse("f'{1+1}'")
    assert reason in (R.UNSUPPORTED_NODE, R.PARSE_ERROR)


def test_long_function_name_blocked():
    _, reason, _ = parse("a" * 100 + "(1)")
    # Either too_long (input cap) or unsupported_function
    assert reason in (R.TOO_LONG, R.UNSUPPORTED_FUNC, R.PARSE_ERROR)


def test_division_by_extremely_small_returns_overflow_or_finite():
    ctx = FakeCtx()
    resp = _run(ctx, "1/1e-300")
    embed = resp["embeds"][0]
    footer = (embed.get("footer") or {}).get("text", "")
    # Either it succeeds with a huge number (rendered scientific, no footer
    # because no trig was used) or overflows with a `reason:` footer.
    # Both are acceptable — just must not crash.
    if "reason:" in footer:
        assert any(r in footer for r in (R.OVERFLOW, R.DOMAIN_ERROR))


def test_at_mentions_in_input_dont_ping():
    ctx = FakeCtx()
    event = slash_event("calc", options=[opt("expression", "@everyone 1+1")])
    plugin_module.cmd_calc(ctx, event)
    resp = ctx.interaction.responses[0]
    # allowed_mentions disables pings regardless of content
    assert resp["allowed_mentions"] == {"parse": []}
    # And the echoed expression should have @everyone neutralized too —
    # the contiguous pingable string must not appear in the output.
    desc = resp["embeds"][0]["description"]
    assert "@everyone" not in desc


def test_non_string_expression_rejected():
    ctx = FakeCtx()
    # Discord type=3 should ensure a string, but defensively...
    event = slash_event("calc", options=[opt("expression", 12345)])
    plugin_module.cmd_calc(ctx, event)
    embed = ctx.interaction.responses[0]["embeds"][0]
    assert R.INVALID_CHARS in embed["footer"]["text"]


def test_unicode_lookalike_function_name_blocked():
    # Cyrillic 'sin' looks like Latin 'sin'
    _, reason, _ = parse("ѕіη(0)")  # ѕі η — lookalikes
    assert reason in (R.UNSUPPORTED_FUNC, R.UNSUPPORTED_NAME, R.PARSE_ERROR)
