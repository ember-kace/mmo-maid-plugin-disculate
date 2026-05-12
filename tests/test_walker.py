import math

import pytest

from lib import reasons as R
from lib.parser import parse
from lib.walker import run_safe


def _run(expr, angle_mode="rad", budget=0.2):
    tree, reason, _ = parse(expr)
    assert reason is None, f"parse failed: {reason}"
    value, walk_reason, _ = run_safe(tree, angle_mode=angle_mode, budget_seconds=budget)
    return value, walk_reason


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
    tree, reason, _ = parse("1e1000")
    assert tree is None
    assert reason == R.OVERFLOW
    # Also ensure -inf and 1e500 are rejected
    for expr in ("1e500", "-1e1000", "1e308 ** 2"):
        tree, reason, _ = parse(expr)
        # Either rejected at parse (literal overflow) or at walk (binop overflow)
        if tree is None:
            assert reason in (R.OVERFLOW, R.PARSE_ERROR), f"{expr} -> {reason}"
        else:
            _, walk_reason, _ = run_safe(tree)
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
    # Result of 10000000**2 is 47 bits (well under the 4096 budget),
    # so v0.2.9 returns an exact int. Pre-0.2.9 this routed through
    # math.pow because base > 1_000_000 — now the bit-budget keeps it
    # exact. Either return type is fine; the math is what matters.
    value, reason = _run("10000000**2")
    assert reason is None
    assert value == 100_000_000_000_000


# --- V1-01 pow bit-budget tests (v0.2.9) ----------------------------


@pytest.mark.parametrize("expr, expected", [
    ("mod(2**100, 7)", 2),
    ("mod(3**70, 7)", 4),
    ("mod(2**70, 7)", 2),
    ("2**100 - 2**100", 0),
])
def test_pow_preserves_int_exactness_for_small_base_bignums(expr, expected):
    """V1-01: small-base, high-exp powers stay exact. Pre-v0.2.9
    `mod(2**100, 7)` returned 0.0 because _safe_pow routed through
    math.pow whenever exp > 64."""
    value, reason = _run(expr)
    assert reason is None, expr
    assert value == expected, f"{expr} -> {value}, expected {expected}"


def test_pow_bit_budget_boundary_holds():
    """The bit estimate is conservative: `exp * bit_length(|base|)`
    overestimates the actual result bit-length by roughly 2x for
    base=2 (since `bit_length(2) == 2` but `log2(2) == 1`). With a
    4096-bit budget, the boundary for base=2 lands at exp=2048 →
    estimate 4096 (fits) vs exp=2049 → estimate 4098 (routed to
    math.pow, which overflows past float max ~10**308)."""
    # 2**2048: estimate 2048 * 2 = 4096 bits = budget. Exact int.
    value, reason = _run("2**2048")
    assert reason is None
    assert isinstance(value, int)
    assert value.bit_length() == 2049  # actual is N+1 bits for 2**N
    # 2**2049: estimate 4098 > 4096 budget. math.pow overflows.
    value, reason = _run("2**2049")
    assert value is None
    assert reason == R.OVERFLOW


def test_calc_log_base_one_reports_domain_not_div_by_zero():
    """V1-03 end-to-end: `log(5, 1)` reaches the user as DOMAIN_ERROR,
    not as the previously-misleading DIV_BY_ZERO."""
    value, reason = _run("log(5, 1)")
    assert value is None
    assert reason == R.DOMAIN_ERROR


def test_pow_dos_canaries_still_overflow():
    """Regression for T-round / R3 DoS guards: huge powers still
    produce OVERFLOW, not silently consume memory."""
    for expr in ("9**99999", "10**1000000"):
        value, reason = _run(expr)
        assert value is None, expr
        assert reason == R.OVERFLOW, f"{expr} -> {reason}"


def test_timeout_trips_when_budget_tiny():
    # Force the budget so low that the first node visit trips. The wall-clock
    # check runs at every node visit; with a negative budget the very first
    # call to check() should raise TIMEOUT.
    tree, _, _ = parse("1+1+1+1+1")
    value, reason, _ = run_safe(tree, budget_seconds=-1.0)
    assert value is None
    assert reason == R.TIMEOUT


def test_walker_returns_internal_on_unknown_error(monkeypatch):
    from lib import walker
    tree, _, _ = parse("1+1")

    def boom(*args, **kwargs):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(walker, "_walk", boom)
    value, reason, _ = walker.run_safe(tree)
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


def test_walker_never_returns_bool():
    """V3-01 / V4-04: format_result's bool branch was historically a
    defensive check — but the walker only ever returns int or float.
    Parser rejects True/False literals; arithmetic on int/float can't
    produce bool. Lock the invariant so the dropped branch in
    format.py stays defensible."""
    for expr in (
        "2+2", "1/3", "sqrt(2)", "pi", "sin(0)", "min(3, 1, 2)",
        "(2+1)*7-8", "abs(-5)", "round(3.5)", "-(2+3)", "2**8",
        "log(10, 10)", "max(1, 2, 3)", "mod(7, 3)",
    ):
        value, reason = _run(expr)
        assert reason is None, expr
        assert not isinstance(value, bool), f"{expr} -> bool {value!r}"


# --- Step trace (v0.2.4) ---------------------------------------------


def test_trace_none_is_backward_compatible():
    # Existing call sites (no trace= kwarg) keep working unchanged.
    tree, _, _ = parse("2+2")
    value, reason, _ = run_safe(tree)
    assert reason is None
    assert value == 4


def test_trace_records_binop_steps_in_inner_first_order():
    from lib.walker import BinOpStep
    tree, _, _ = parse("(2+1)*7-8")
    trace = []
    value, reason, _ = run_safe(tree, trace=trace)
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
    tree, _, _ = parse("sqrt(abs(-16)) + 1")
    trace = []
    value, reason, _ = run_safe(tree, trace=trace)
    assert reason is None and value == 5.0
    kinds = [type(s).__name__ for s in trace]
    assert kinds == ["CallStep", "CallStep", "BinOpStep"]
    assert trace[0].name == "abs" and trace[0].args == [-16] and trace[0].result == 16
    assert trace[1].name == "sqrt" and trace[1].args == [16] and trace[1].result == 4.0
    assert trace[2].op == "+" and trace[2].result == 5.0


def test_trace_skips_unary_and_constants():
    from lib.walker import BinOpStep
    # `-(2+3)` -> one BinOp inside a UnaryOp. UnaryOp doesn't emit a step.
    tree, _, _ = parse("-(2+3)")
    trace = []
    value, reason, _ = run_safe(tree, trace=trace)
    assert reason is None and value == -5
    assert len(trace) == 1
    assert isinstance(trace[0], BinOpStep)
    assert trace[0].result == 5  # BinOp's own result (before USub)


def test_trace_skips_constant_lookup():
    # `pi + 1`: one BinOp, zero CallSteps. The `pi` lookup is not a step.
    tree, _, _ = parse("pi + 1")
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
