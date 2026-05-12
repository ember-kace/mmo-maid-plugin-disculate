import math

import pytest

from lib import reasons as R
from lib.parser import parse
from lib.walker import run_safe


def _run(expr, angle_mode="rad", budget=0.2):
    tree, reason = parse(expr)
    assert reason is None, f"parse failed: {reason}"
    return run_safe(tree, angle_mode=angle_mode, budget_seconds=budget)


@pytest.mark.parametrize("expr, expected", [
    ("2+2", 4),
    ("2-3", -1),
    ("3*4", 12),
    ("10/4", 2.5),
    ("10//3", 3),
    ("2**8", 256),
    ("+5", 5),
    ("-5", -5),
    ("-(2+3)", -5),
    ("(1+2)*3", 9),
])
def test_basic_arithmetic(expr, expected):
    value, reason = _run(expr)
    assert reason is None
    assert value == expected


@pytest.mark.parametrize("expr, expected", [
    ("pi", math.pi),
    ("e", math.e),
    ("tau", math.tau),
])
def test_constants(expr, expected):
    value, reason = _run(expr)
    assert reason is None
    assert value == pytest.approx(expected)


@pytest.mark.parametrize("expr, expected", [
    ("sqrt(16)", 4.0),
    ("abs(-7)", 7),
    ("floor(3.7)", 3),
    ("ceil(3.2)", 4),
    ("min(3,1,2)", 1),
    ("max(3,1,2)", 3),
    ("round(3.567, 2)", 3.57),
    ("log10(1000)", 3.0),
    ("log2(8)", 3.0),
    ("exp(0)", 1.0),
    ("log(e)", 1.0),
    ("ln(e)", 1.0),
    ("mod(7, 3)", 1),
    ("pow(2, 10)", 1024),
])
def test_functions(expr, expected):
    value, reason = _run(expr)
    assert reason is None
    assert value == pytest.approx(expected)


def test_trig_default_radians():
    value, reason = _run("sin(0)")
    assert reason is None
    assert value == pytest.approx(0.0)
    value, reason = _run("cos(pi)")
    assert reason is None
    assert value == pytest.approx(-1.0)


def test_trig_degree_mode():
    value, reason = _run("sin(90)", angle_mode="deg")
    assert reason is None
    assert value == pytest.approx(1.0)
    value, reason = _run("cos(180)", angle_mode="deg")
    assert reason is None
    assert value == pytest.approx(-1.0)


def test_inverse_trig_degree_mode():
    value, reason = _run("asin(1)", angle_mode="deg")
    assert reason is None
    assert value == pytest.approx(90.0)
    value, reason = _run("atan2(1, 1)", angle_mode="deg")
    assert reason is None
    assert value == pytest.approx(45.0)


def test_percentage_via_preprocessing():
    value, reason = _run("50%")
    assert reason is None
    assert value == 0.5
    value, reason = _run("200 * 5%")
    assert reason is None
    assert value == 10.0


def test_div_by_zero():
    for expr in ("1/0", "1.0/0", "1//0", "mod(1, 0)"):
        value, reason = _run(expr)
        assert value is None, expr
        assert reason == R.DIV_BY_ZERO, expr


def test_domain_errors():
    for expr in ("sqrt(-1)", "log(-1)", "log(0)", "asin(2)", "acos(2)", "(-2)**0.5"):
        value, reason = _run(expr)
        assert value is None, expr
        assert reason == R.DOMAIN_ERROR, f"{expr} -> {reason}"


def test_inf_nan_results_caught_post_binop():
    # T1-02: result-side nan/inf must be caught regardless of the operator
    # that produced them. With T1-01 rejecting inf/nan literals upfront,
    # these cases are now reached only via intermediate float arithmetic.
    # The centralized check in walker._walk converts them to typed reasons.
    for expr, expected_reason in [
        ("1e308 + 1e308", R.OVERFLOW),     # finite + finite -> inf
        ("1e308 * 10",    R.OVERFLOW),
        ("0 * (1e308 * 10)", R.OVERFLOW),  # would be 0 * inf = nan in raw float; caught upstream
    ]:
        value, reason = _run(expr)
        assert value is None, f"{expr} produced {value}"
        # OVERFLOW or DOMAIN_ERROR both indicate the centralized guard fired.
        assert reason in (R.OVERFLOW, R.DOMAIN_ERROR), f"{expr} -> {reason}"


def test_inf_literal_rejected_at_parse_time():
    # T1-01: ast.parse("1e1000") -> Constant(value=inf). Validator must
    # reject this so it can't seed downstream arithmetic.
    tree, reason = parse("1e1000")
    assert tree is None
    assert reason == R.OVERFLOW
    # Also ensure -inf and 1e500 are rejected
    for expr in ("1e500", "-1e1000", "1e308 ** 2"):
        tree, reason = parse(expr)
        # Either rejected at parse (literal overflow) or at walk (binop overflow)
        if tree is None:
            assert reason in (R.OVERFLOW, R.PARSE_ERROR), f"{expr} -> {reason}"
        else:
            _, walk_reason = run_safe(tree)
            assert walk_reason in (R.OVERFLOW, R.DOMAIN_ERROR), f"{expr} -> {walk_reason}"


def test_pow_guard_huge_int_exp_routes_through_float():
    # 2**1000000 as bignum would eat memory; our guard routes to math.pow,
    # which overflows cleanly to OverflowError -> OVERFLOW.
    value, reason = _run("2**1000000")
    assert value is None
    assert reason == R.OVERFLOW


def test_pow_guard_negative_exp_int_routes_through_float():
    value, reason = _run("2**-3")
    assert reason is None
    assert value == pytest.approx(0.125)


def test_pow_small_ints_preserved():
    value, reason = _run("2**10")
    assert reason is None
    assert value == 1024
    assert isinstance(value, int)


def test_pow_huge_base_routes_through_float():
    value, reason = _run("10000000**2")
    # base > 1_000_000 forces float route
    assert reason is None
    assert value == pytest.approx(1e14)


def test_timeout_trips_when_budget_tiny():
    # Force the budget so low that the first node visit trips. The wall-clock
    # check runs at every node visit; with a negative budget the very first
    # call to check() should raise TIMEOUT.
    tree, _ = parse("1+1+1+1+1")
    value, reason = run_safe(tree, budget_seconds=-1.0)
    assert value is None
    assert reason == R.TIMEOUT


def test_walker_returns_internal_on_unknown_error(monkeypatch):
    from lib import walker
    tree, _ = parse("1+1")

    def boom(*args, **kwargs):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(walker, "_walk", boom)
    value, reason = walker.run_safe(tree)
    assert value is None
    assert reason == R.INTERNAL


def test_nested_calls_run():
    value, reason = _run("sqrt(abs(-16))")
    assert reason is None
    assert value == 4.0


def test_unary_combinations():
    value, reason = _run("--5")
    assert reason is None
    assert value == 5
    value, reason = _run("-+-5")
    assert reason is None
    assert value == 5


# --- Step trace (v0.2.4) ---------------------------------------------


def test_trace_none_is_backward_compatible():
    # Existing call sites (no trace= kwarg) keep working unchanged.
    tree, _ = parse("2+2")
    value, reason = run_safe(tree)
    assert reason is None
    assert value == 4


def test_trace_records_binop_steps_in_inner_first_order():
    from lib.walker import BinOpStep
    tree, _ = parse("(2+1)*7-8")
    trace = []
    value, reason = run_safe(tree, trace=trace)
    assert reason is None and value == 13
    assert all(isinstance(s, BinOpStep) for s in trace)
    # `2+1` -> 3, then `3*7` -> 21, then `21-8` -> 13.
    assert [(s.left, s.op, s.right, s.result) for s in trace] == [
        (2, "+", 1, 3),
        (3, "*", 7, 21),
        (21, "-", 8, 13),
    ]


def test_trace_records_call_steps_inner_first():
    from lib.walker import BinOpStep, CallStep
    tree, _ = parse("sqrt(abs(-16)) + 1")
    trace = []
    value, reason = run_safe(tree, trace=trace)
    assert reason is None and value == 5.0
    kinds = [type(s).__name__ for s in trace]
    assert kinds == ["CallStep", "CallStep", "BinOpStep"]
    assert trace[0].name == "abs" and trace[0].args == [-16] and trace[0].result == 16
    assert trace[1].name == "sqrt" and trace[1].args == [16] and trace[1].result == 4.0
    assert trace[2].op == "+" and trace[2].result == 5.0


def test_trace_skips_unary_and_constants():
    from lib.walker import BinOpStep
    # `-(2+3)` -> one BinOp inside a UnaryOp. UnaryOp doesn't emit a step.
    tree, _ = parse("-(2+3)")
    trace = []
    value, reason = run_safe(tree, trace=trace)
    assert reason is None and value == -5
    assert len(trace) == 1
    assert isinstance(trace[0], BinOpStep)
    assert trace[0].result == 5  # BinOp's own result (before USub)


def test_trace_skips_constant_lookup():
    # `pi + 1`: one BinOp, zero CallSteps. The `pi` lookup is not a step.
    tree, _ = parse("pi + 1")
    trace = []
    run_safe(tree, trace=trace)
    assert len(trace) == 1
    assert trace[0].op == "+"


def test_trace_operator_symbols_match_user_syntax():
    from lib.walker import _OP_SYMBOLS
    expected = {
        "+": "+", "-": "-", "*": "*",
        "/": "/", "//": "//", "**": "**",
    }
    seen = set(_OP_SYMBOLS.values())
    for sym in expected.values():
        assert sym in seen, f"operator {sym!r} missing from _OP_SYMBOLS"
