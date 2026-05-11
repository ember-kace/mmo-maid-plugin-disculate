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


def test_round_rejects_non_integer_ndigits():
    with pytest.raises(ValueError):
        call_function("round", [1.5, 1.5], "rad")


def test_unknown_function_raises():
    with pytest.raises(KeyError):
        call_function("nope", [1], "rad")
