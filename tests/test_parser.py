import pytest

from lib import parser
from lib import reasons as R


@pytest.mark.parametrize("raw, expected_reason", [
    (None, R.INVALID_CHARS),
    ("", R.EMPTY),
    ("   ", R.EMPTY),
    ("a" * 121, R.TOO_LONG),
    ("1+\x001", R.INVALID_CHARS),     # NUL
    ("1+‎1", R.INVALID_CHARS),   # LRM (bidi)
    ("1+‮1", R.INVALID_CHARS),   # RLO (bidi)
])
def test_clean_rejects_bad_input(raw, expected_reason):
    with pytest.raises(parser.CleanError) as exc:
        parser.clean_expression(raw)
    assert exc.value.reason == expected_reason


def test_clean_normalizes_nfkc():
    # full-width digit '１' (U+FF11) normalizes to ASCII '1' under NFKC
    out = parser.clean_expression("１+1")
    assert out == "1+1"


def test_clean_strips_whitespace():
    assert parser.clean_expression("   2 + 2   ") == "2 + 2"


@pytest.mark.parametrize("inp, expected", [
    ("50%", "(50/100)"),
    ("100 * 5%", "100 * (5/100)"),
    ("0.5%", "(0.5/100)"),
    ("1e2%", "(1e2/100)"),
    ("100+10%", "100+(10/100)"),
    (".5%", "(.5/100)"),
    ("(50%)", "((50/100))"),
])
def test_preprocess_percent(inp, expected):
    assert parser.preprocess_percent(inp) == expected


def test_preprocess_percent_no_change_when_no_match():
    assert parser.preprocess_percent("2+3") == "2+3"
    assert parser.preprocess_percent("sqrt(2)") == "sqrt(2)"


def test_parse_simple_arithmetic_returns_tree():
    tree, reason = parser.parse("2+2")
    assert reason is None
    assert tree is not None


def test_parse_rejects_attribute_access():
    tree, reason = parser.parse("(1).__class__")
    assert tree is None
    assert reason == R.UNSUPPORTED_NODE


def test_parse_rejects_subscript():
    tree, reason = parser.parse("(1)[0]")
    assert tree is None
    # Either parse_error or unsupported_node is acceptable; both are blocked.
    assert reason in (R.UNSUPPORTED_NODE, R.PARSE_ERROR)


def test_parse_rejects_lambda():
    tree, reason = parser.parse("lambda x: x")
    assert tree is None
    assert reason in (R.UNSUPPORTED_NODE, R.PARSE_ERROR)


def test_parse_rejects_comparison():
    tree, reason = parser.parse("1 < 2")
    assert tree is None
    assert reason == R.WANT_COMPARE


def test_parse_rejects_bool_op():
    tree, reason = parser.parse("1 and 2")
    assert tree is None
    assert reason == R.WANT_COMPARE


def test_parse_rejects_walrus():
    tree, reason = parser.parse("(x := 5)")
    assert tree is None
    assert reason in (R.UNSUPPORTED_NODE, R.PARSE_ERROR)


def test_parse_emits_specific_hints_for_common_operator_mistakes():
    # ^ used as power
    _, reason = parser.parse("2 ^ 3")
    assert reason == R.WANT_POWER
    # Bitwise operators
    for expr in ("1 & 2", "1 | 2", "1 << 2", "1 >> 2", "~1"):
        _, reason = parser.parse(expr)
        assert reason == R.WANT_BITWISE, expr


def test_parse_rejects_modulo_operator_with_want_mod():
    # `pi%3` doesn't match the percent regex (starts with non-digit), so
    # stays as BinOp(Mod). The validator now surfaces WANT_MOD with a
    # hint pointing users at `mod(a, b)`.
    tree, reason = parser.parse("pi%3")
    assert tree is None
    assert reason == R.WANT_MOD


def test_modulo_between_numbers_now_emits_want_mod_after_regex_tightening():
    # With the tightened percent regex, `5%3` and `5 % 3` no longer get
    # rewritten as percent — they reach the Mod operator path and emit
    # the WANT_MOD hint.
    for expr in ("5%3", "5 % 3", "10%2"):
        tree, reason = parser.parse(expr)
        assert tree is None, expr
        assert reason == R.WANT_MOD, f"{expr} -> {reason}"


def test_trailing_percent_still_works_after_regex_tightening():
    # The regex tightening must not break `50%`, `100% + 5`, or `200 * 5%`.
    for expr, expected in [
        ("50%", 0.5),
        ("100% + 5", 6.0),
        ("200 * 5%", 10.0),
    ]:
        tree, reason = parser.parse(expr)
        assert tree is not None, f"{expr} -> {reason}"


def test_percent_before_minus_rewrites_as_percent_not_modulo():
    # `5%-3` — minus is not in [\w.\(], so the negative lookahead passes
    # and `5%` is rewritten to `(5/100)`. Result: `(5/100) - 3 = -2.95`.
    # This is the right user-intent inference: `5% - 3` is "5 percent
    # minus three", not modulo. Lock the behavior with a test.
    from lib.evaluator import evaluate_safe
    tree, reason = parser.parse("5%-3")
    assert tree is not None, reason
    value, eval_reason = evaluate_safe(tree)
    assert eval_reason is None
    assert value == pytest.approx(-2.95)


def test_parse_rejects_unknown_function():
    tree, reason = parser.parse("foobar(1)")
    assert tree is None
    assert reason == R.UNSUPPORTED_FUNC


def test_parse_rejects_unknown_name():
    tree, reason = parser.parse("x + 1")
    assert tree is None
    assert reason == R.UNSUPPORTED_NAME


def test_parse_rejects_keyword_arg():
    tree, reason = parser.parse("round(1.5, ndigits=1)")
    assert tree is None
    assert reason == R.UNSUPPORTED_NODE


def test_parse_rejects_starred_arg():
    tree, reason = parser.parse("max(*[1,2,3])")
    assert tree is None
    assert reason in (R.UNSUPPORTED_NODE, R.PARSE_ERROR)


def test_parse_rejects_string_literal():
    tree, reason = parser.parse("'abc'")
    assert tree is None
    assert reason == R.UNSUPPORTED_NODE


def test_parse_rejects_complex_literal():
    tree, reason = parser.parse("1j")
    assert tree is None
    assert reason == R.UNSUPPORTED_NODE


def test_parse_rejects_bool_literal():
    # Python parses `True` as Constant(value=True). True is technically int
    # subclass so we explicitly reject bool.
    tree, reason = parser.parse("True + 1")
    assert tree is None
    # Either UNSUPPORTED_NAME (Python<3.4 style) or UNSUPPORTED_NODE
    assert reason in (R.UNSUPPORTED_NODE, R.UNSUPPORTED_NAME)


def test_parse_rejects_overly_deep():
    expr = "1" + "+1" * 50
    # 50 BinOps is depth ~50, exceeds MAX_DEPTH=32
    tree, reason = parser.parse(expr)
    assert tree is None
    assert reason == R.DEPTH_EXCEEDED


def test_node_count_cap_is_enforced_directly():
    """The 120-char input limit makes >200 nodes hard to construct from real
    input — but the cap is defense-in-depth. Validate that it actually
    triggers if a tree somehow has more nodes than MAX_NODES."""
    import ast
    from lib import reasons as R2
    state = parser._State()
    state.count = parser.MAX_NODES  # one more visit will trip
    node = ast.Constant(value=1)
    with pytest.raises(parser.ValidationError) as exc:
        parser._validate(node, 0, state)
    assert exc.value.reason == R2.NODE_COUNT_EXCEEDED


def test_parse_rejects_too_many_call_args():
    args = ",".join("1" for _ in range(17))
    tree, reason = parser.parse(f"max({args})")
    assert tree is None
    assert reason == R.TOO_MANY_ARGS


def test_parse_allows_known_constants():
    for name in ("pi", "e", "tau"):
        tree, reason = parser.parse(name)
        assert reason is None
        assert tree is not None
