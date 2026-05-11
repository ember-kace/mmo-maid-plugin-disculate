import math

import pytest

from lib import reasons as R
from lib.evaluator import evaluate_safe
from lib.parser import parse


def _eval(expr, angle_mode="rad", budget=0.2):
    tree, reason = parse(expr)
    assert reason is None, f"parse failed: {reason}"
    return evaluate_safe(tree, angle_mode=angle_mode, budget_seconds=budget)


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
    value, reason = _eval(expr)
    assert reason is None
    assert value == expected


@pytest.mark.parametrize("expr, expected", [
    ("pi", math.pi),
    ("e", math.e),
    ("tau", math.tau),
])
def test_constants(expr, expected):
    value, reason = _eval(expr)
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
    value, reason = _eval(expr)
    assert reason is None
    assert value == pytest.approx(expected)


def test_trig_default_radians():
    value, reason = _eval("sin(0)")
    assert reason is None
    assert value == pytest.approx(0.0)
    value, reason = _eval("cos(pi)")
    assert reason is None
    assert value == pytest.approx(-1.0)


def test_trig_degree_mode():
    value, reason = _eval("sin(90)", angle_mode="deg")
    assert reason is None
    assert value == pytest.approx(1.0)
    value, reason = _eval("cos(180)", angle_mode="deg")
    assert reason is None
    assert value == pytest.approx(-1.0)


def test_inverse_trig_degree_mode():
    value, reason = _eval("asin(1)", angle_mode="deg")
    assert reason is None
    assert value == pytest.approx(90.0)
    value, reason = _eval("atan2(1, 1)", angle_mode="deg")
    assert reason is None
    assert value == pytest.approx(45.0)


def test_percentage_via_preprocessing():
    value, reason = _eval("50%")
    assert reason is None
    assert value == 0.5
    value, reason = _eval("200 * 5%")
    assert reason is None
    assert value == 10.0


def test_div_by_zero():
    for expr in ("1/0", "1.0/0", "1//0", "mod(1, 0)"):
        value, reason = _eval(expr)
        assert value is None, expr
        assert reason == R.DIV_BY_ZERO, expr


def test_domain_errors():
    for expr in ("sqrt(-1)", "log(-1)", "log(0)", "asin(2)", "acos(2)", "(-2)**0.5"):
        value, reason = _eval(expr)
        assert value is None, expr
        assert reason == R.DOMAIN_ERROR, f"{expr} -> {reason}"


def test_inf_nan_results_caught_post_binop():
    # T1-02: result-side nan/inf must be caught regardless of the operator
    # that produced them. With T1-01 rejecting inf/nan literals upfront,
    # these cases are now reached only via intermediate float arithmetic.
    # The centralized check in _eval converts them to typed reasons.
    for expr, expected_reason in [
        ("1e308 + 1e308", R.OVERFLOW),     # finite + finite -> inf
        ("1e308 * 10",    R.OVERFLOW),
        ("0 * (1e308 * 10)", R.OVERFLOW),  # would be 0 * inf = nan in raw float; caught upstream
    ]:
        value, reason = _eval(expr)
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
        # Either rejected at parse (literal overflow) or at eval (binop overflow)
        if tree is None:
            assert reason in (R.OVERFLOW, R.PARSE_ERROR), f"{expr} -> {reason}"
        else:
            _, eval_reason = evaluate_safe(tree)
            assert eval_reason in (R.OVERFLOW, R.DOMAIN_ERROR), f"{expr} -> {eval_reason}"


def test_pow_guard_huge_int_exp_routes_through_float():
    # 2**1000000 as bignum would eat memory; our guard routes to math.pow,
    # which overflows cleanly to OverflowError -> OVERFLOW.
    value, reason = _eval("2**1000000")
    assert value is None
    assert reason == R.OVERFLOW


def test_pow_guard_negative_exp_int_routes_through_float():
    value, reason = _eval("2**-3")
    assert reason is None
    assert value == pytest.approx(0.125)


def test_pow_small_ints_preserved():
    value, reason = _eval("2**10")
    assert reason is None
    assert value == 1024
    assert isinstance(value, int)


def test_pow_huge_base_routes_through_float():
    value, reason = _eval("10000000**2")
    # base > 1_000_000 forces float route
    assert reason is None
    assert value == pytest.approx(1e14)


def test_timeout_trips_when_budget_tiny():
    # Force the budget so low that the first node visit trips. The wall-clock
    # check runs at every node visit; with a negative budget the very first
    # call to check() should raise TIMEOUT.
    tree, _ = parse("1+1+1+1+1")
    value, reason = evaluate_safe(tree, budget_seconds=-1.0)
    assert value is None
    assert reason == R.TIMEOUT


def test_evaluator_returns_internal_on_unknown_error(monkeypatch):
    from lib import evaluator
    tree, _ = parse("1+1")

    def boom(*args, **kwargs):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(evaluator, "_eval", boom)
    value, reason = evaluator.evaluate_safe(tree)
    assert value is None
    assert reason == R.INTERNAL


def test_nested_calls_evaluate():
    value, reason = _eval("sqrt(abs(-16))")
    assert reason is None
    assert value == 4.0


def test_unary_combinations():
    value, reason = _eval("--5")
    assert reason is None
    assert value == 5
    value, reason = _eval("-+-5")
    assert reason is None
    assert value == 5
