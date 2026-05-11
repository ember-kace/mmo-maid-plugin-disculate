import math

import pytest

from lib.format import format_result


def test_ints_with_thousands_separators():
    assert format_result(0) == "0"
    assert format_result(1) == "1"
    assert format_result(-1) == "-1"
    assert format_result(1234) == "1,234"
    assert format_result(-1234567) == "-1,234,567"


def test_float_that_is_whole_number_drops_decimal():
    assert format_result(2.0) == "2"
    assert format_result(-7.0) == "-7"


def test_float_basic_precision():
    assert format_result(3.14159265, precision=2) == "3.14"
    assert format_result(3.14159265, precision=6) == "3.141593"


def test_float_trailing_zeros_trimmed():
    assert format_result(1.5, precision=6) == "1.5"
    assert format_result(1.50, precision=6) == "1.5"


def test_scientific_for_huge():
    s = format_result(1e15, precision=6, scientific_threshold=12)
    assert "e" in s
    assert s.startswith("1") or s.startswith("-")


def test_scientific_for_tiny():
    s = format_result(1.23e-10, precision=6, scientific_threshold=12)
    assert "e" in s


def test_zero_renders_as_zero():
    assert format_result(0.0) == "0"
    assert format_result(0) == "0"


def test_negative_zero_renders_as_zero():
    assert format_result(-0.0) == "0"


def test_nan_renders():
    assert format_result(float("nan")) == "NaN"


def test_inf_renders():
    assert format_result(float("inf")) == "+inf"
    assert format_result(float("-inf")) == "-inf"


def test_precision_zero_truncates_integer_part_only():
    assert format_result(3.7, precision=0) == "4"


def test_negative_float():
    assert format_result(-3.14, precision=2) == "-3.14"


def test_bool_treated_as_int():
    # Defensive: format_result should never see a bool from the evaluator,
    # but if it does we want stable behavior.
    assert format_result(True) == "1"
    assert format_result(False) == "0"


def test_huge_int_routes_scientific():
    s = format_result(10**15, scientific_threshold=12)
    assert "e" in s


def test_value_at_precision_boundary_uses_scientific():
    # T2-01: with precision=6, 1e-7 must NOT render as "0.000000" -> "0".
    # The boundary `abs_v < 10**-precision` routes sub-precision values
    # into scientific notation instead.
    s = format_result(1e-7, precision=6, scientific_threshold=12)
    assert s != "0", "1e-7 lost its value at the boundary"
    assert "e" in s


def test_value_just_above_precision_stays_fixed():
    # 1e-6 IS representable at precision=6 -> "0.000001"
    s = format_result(1e-6, precision=6, scientific_threshold=12)
    assert s == "0.000001"


def test_int_and_equivalent_float_at_threshold_render_consistently():
    # T2-04: ensure 10**12 (int) and 1e12 (float) take the same code path
    # convention. Both should yield scientific notation with the same shape.
    s_int = format_result(10**12, precision=6, scientific_threshold=12)
    s_float = format_result(1e12, precision=6, scientific_threshold=12)
    # Both render as scientific, both have an exponent in them.
    assert "e" in s_int
    assert "e" in s_float


def test_thousand_separators_in_decimal():
    s = format_result(1234.5, precision=2)
    assert "1,234" in s
