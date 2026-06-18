import math

import pytest

from lib.functions import (
    ALL_FUNCTION_NAMES,
    CONSTANTS,
    _ArityError,
    call_function,
    is_allowed_function,
)


def test_constants_present():
    assert CONSTANTS["pi"] == math.pi
    assert CONSTANTS["e"] == math.e
    assert CONSTANTS["tau"] == math.tau


def test_function_allowlist_contains_expected():
    expected = {
        "abs", "round", "floor", "ceil", "min", "max", "mod", "pow",
        "sqrt", "exp", "log", "log10", "log2", "ln",
        "sin", "cos", "tan", "asin", "acos", "atan", "atan2",
        "sinh", "cosh", "tanh",
    }
    assert expected <= ALL_FUNCTION_NAMES


def test_is_allowed_function():
    assert is_allowed_function("sqrt")
    assert not is_allowed_function("eval")
    assert not is_allowed_function("__import__")


def test_arity_round():
    assert call_function("round", [1.567, 2], "rad") == 1.57
    assert call_function("round", [1.567], "rad") == 2


def test_arity_too_few():
    with pytest.raises(_ArityError) as exc:
        call_function("sqrt", [], "rad")
    assert exc.value.kind == "too_few"


def test_arity_too_many():
    with pytest.raises(_ArityError) as exc:
        call_function("sqrt", [1, 2], "rad")
    assert exc.value.kind == "too_many"


def test_min_max_variadic():
    assert call_function("min", [3, 1, 2], "rad") == 1
    assert call_function("max", [3, 1, 2], "rad") == 3
    assert call_function("min", [5], "rad") == 5


def test_mod_zero_raises():
    with pytest.raises(ZeroDivisionError):
        call_function("mod", [1, 0], "rad")


# --- V1-03 / V4-02: log base validation -----------------------------


def test_log_base_one_raises_value_error():
    """log base 1 must produce a ValueError (which the walker maps to
    DOMAIN_ERROR), not a ZeroDivisionError (which would map to
    DIV_BY_ZERO with a misleading hint about the second arg)."""
    with pytest.raises(ValueError):
        call_function("log", [5, 1], "rad")


@pytest.mark.parametrize("base", [0, -2, -0.5])
def test_log_base_non_positive_raises_value_error(base):
    with pytest.raises(ValueError):
        call_function("log", [5, base], "rad")


def test_log_with_valid_base_works():
    # Regression: don't break the happy path.
    assert call_function("log", [8, 2], "rad") == pytest.approx(3.0)
    assert call_function("log", [100, 10], "rad") == pytest.approx(2.0)


@pytest.mark.parametrize("a, b, expected", [
    (-7, 3, 2),         # int / int
    (-7.0, 3, 2.0),     # mixed
    (-7, 3.0, 2.0),     # mixed
    (-7.0, 3.0, 2.0),   # float / float
    (7, -3, -2),
    (7.0, -3, -2.0),
])
def test_mod_sign_consistent_for_negatives(a, b, expected):
    # T1-03: sign-follows-divisor for both int and float inputs.
    assert call_function("mod", [a, b], "rad") == expected


def test_trig_radians_default():
    assert call_function("sin", [0], "rad") == pytest.approx(0.0)
    assert call_function("cos", [0], "rad") == pytest.approx(1.0)


# --- v0.3.0 additions: inverse hyperbolic, cbrt, gcd/lcm, trunc ------


def test_new_functions_in_allowlist():
    assert {"asinh", "acosh", "atanh", "cbrt", "gcd", "lcm", "trunc"} <= ALL_FUNCTION_NAMES


def test_inverse_hyperbolic_happy_path():
    assert call_function("asinh", [0], "rad") == pytest.approx(0.0)
    assert call_function("acosh", [1], "rad") == pytest.approx(0.0)
    assert call_function("atanh", [0], "rad") == pytest.approx(0.0)
    # Round-trips with the forward functions.
    assert call_function("asinh", [math.sinh(2.0)], "rad") == pytest.approx(2.0)
    assert call_function("acosh", [math.cosh(2.0)], "rad") == pytest.approx(2.0)
    assert call_function("atanh", [math.tanh(0.5)], "rad") == pytest.approx(0.5)


def test_inverse_hyperbolic_ignores_angle_mode():
    # Hyperbolic functions take a real argument, not an angle — deg
    # mode must not change the result (mirrors sinh/cosh/tanh).
    assert call_function("asinh", [1], "deg") == call_function("asinh", [1], "rad")


@pytest.mark.parametrize("fn, bad", [
    ("acosh", 0.5),   # needs x >= 1
    ("acosh", -3),
    ("atanh", 1),     # needs -1 < x < 1
    ("atanh", -1),
    ("atanh", 2),
])
def test_inverse_hyperbolic_domain_errors(fn, bad):
    with pytest.raises(ValueError):
        call_function(fn, [bad], "rad")


def test_cbrt_happy_path():
    assert call_function("cbrt", [27], "rad") == pytest.approx(3.0)
    assert call_function("cbrt", [0], "rad") == pytest.approx(0.0)
    assert call_function("cbrt", [2.5], "rad") == pytest.approx(2.5 ** (1.0 / 3.0))


def test_cbrt_handles_negatives_unlike_sqrt():
    assert call_function("cbrt", [-8], "rad") == pytest.approx(-2.0)
    with pytest.raises(ValueError):
        call_function("sqrt", [-8], "rad")


def test_gcd_lcm_happy_path():
    assert call_function("gcd", [12, 18], "rad") == 6
    assert call_function("gcd", [-12, 18], "rad") == 6
    assert call_function("gcd", [0, 5], "rad") == 5
    assert call_function("lcm", [4, 6], "rad") == 12
    assert call_function("lcm", [0, 5], "rad") == 0


def test_gcd_lcm_accept_integral_floats():
    # Division upstream produces floats: gcd(12/2, 9) must work.
    assert call_function("gcd", [6.0, 9], "rad") == 3
    assert call_function("lcm", [4.0, 6.0], "rad") == 12


@pytest.mark.parametrize("fn", ["gcd", "lcm"])
def test_gcd_lcm_reject_fractional(fn):
    with pytest.raises(ValueError):
        call_function(fn, [1.5, 3], "rad")
    with pytest.raises(ValueError):
        call_function(fn, [3, 0.25], "rad")


def test_trunc_rounds_toward_zero():
    assert call_function("trunc", [3.9], "rad") == 3
    assert call_function("trunc", [-3.9], "rad") == -3
    assert call_function("trunc", [5], "rad") == 5


def test_trunc_division_gives_c_style_semantics():
    # The floor-div note in /calc-help points here: -7//2 = -4 (Python),
    # trunc(-7/2) = -3 (C/Java/JS/Rust).
    assert call_function("trunc", [-7 / 2], "rad") == -3


def test_trig_degrees():
    assert call_function("sin", [30], "deg") == pytest.approx(0.5)
    assert call_function("cos", [60], "deg") == pytest.approx(0.5)


def test_inverse_trig_degrees():
    assert call_function("asin", [0.5], "deg") == pytest.approx(30.0)
    assert call_function("atan2", [1, 1], "deg") == pytest.approx(45.0)


def test_hyperbolic_not_affected_by_angle_mode():
    rad = call_function("sinh", [1], "rad")
    deg = call_function("sinh", [1], "deg")
    assert rad == deg


def test_hypot_happy_path():
    assert call_function("hypot", [3, 4], "rad") == pytest.approx(5.0)
    assert call_function("hypot", [0, 0], "rad") == pytest.approx(0.0)
    assert call_function("hypot", [5, 12], "rad") == pytest.approx(13.0)
    # Negative operands square away — result is always non-negative.
    assert call_function("hypot", [-3, -4], "rad") == pytest.approx(5.0)


def test_hypot_ignores_angle_mode():
    assert call_function("hypot", [3, 4], "deg") == call_function("hypot", [3, 4], "rad")


def test_sign_returns_int_negative_zero_positive():
    assert call_function("sign", [5], "rad") == 1
    assert call_function("sign", [-2.5], "rad") == -1
    assert call_function("sign", [0], "rad") == 0
    # -0.0 maps to 0, not -1.
    assert call_function("sign", [-0.0], "rad") == 0
    # int in / int out — no spurious decimal in the formatted result.
    assert isinstance(call_function("sign", [3.7], "rad"), int)


def test_round_rejects_non_integer_ndigits():
    with pytest.raises(ValueError):
        call_function("round", [1.5, 1.5], "rad")


def test_unknown_function_raises():
    with pytest.raises(KeyError):
        call_function("nope", [1], "rad")
