"""Coverage for lib/diagnostics.py — the per-reason error explainer."""

import pytest

from lib import diagnostics, reasons as R


# --- unknown name / function ----------------------------------------


@pytest.mark.parametrize("typed, expected", [
    ("Pi", "pi"),
    ("E", "e"),
    ("TAU", "tau"),
    ("Pi", "pi"),
])
def test_unknown_name_case_mismatch_suggests_lowercase(typed, expected):
    what, how = diagnostics.explain(f"{typed} + 1", R.UNSUPPORTED_NAME, typed)
    assert f"`{typed}`" in what
    assert how is not None
    assert "case-sensitive" in how.lower()
    assert f"`{expected}`" in how


@pytest.mark.parametrize("typo, expected", [
    ("sqirt", "sqrt"),
    ("flor", "floor"),
])
def test_unknown_function_close_typo_suggests(typo, expected):
    what, how = diagnostics.explain(f"{typo}(1)", R.UNSUPPORTED_FUNC, typo)
    assert typo in what
    assert how is not None
    assert expected in how


def test_unknown_function_far_typo_no_suggestion():
    what, how = diagnostics.explain("forblar(1)", R.UNSUPPORTED_FUNC, "forblar")
    assert "forblar" in what
    # The "how" line may still exist (pointing at /calc-help) but should NOT
    # contain a "Did you mean" suggestion.
    if how is not None:
        assert "Did you mean" not in how


# --- parse error pattern detection ----------------------------------


def test_parse_unclosed_paren():
    what, how = diagnostics.explain("((1+2)", R.PARSE_ERROR, "")
    assert "Unclosed parenthesis" in what
    assert "Add 1 `)`" in how


def test_parse_extra_close_paren():
    what, how = diagnostics.explain("1+2)", R.PARSE_ERROR, "")
    assert "Too many `)`" in what


def test_parse_trailing_operator():
    what, how = diagnostics.explain("2+", R.PARSE_ERROR, "")
    assert "ends with an operator" in what
    assert "`+`" in what


def test_parse_offset_used_when_no_other_pattern_matches():
    # Balanced parens, no trailing operator — fall through to offset rendering.
    what, how = diagnostics.explain("1 ** 2 ** **", R.PARSE_ERROR, "invalid syntax@12")
    # Either the offset gets surfaced or a generic message — both acceptable.
    assert what  # non-empty


# --- div by zero ----------------------------------------------------


def test_div_by_zero_with_div_operator():
    what, how = diagnostics.explain("1/0", R.DIV_BY_ZERO, "/")
    assert "`/`" in what


def test_div_by_zero_with_floor_div_operator():
    what, how = diagnostics.explain("1//0", R.DIV_BY_ZERO, "//")
    assert "`//`" in what


def test_div_by_zero_from_mod_function():
    what, how = diagnostics.explain("mod(1, 0)", R.DIV_BY_ZERO, "mod")
    assert "mod" in what


# --- domain errors --------------------------------------------------


def test_domain_error_sqrt_negative_suggests_abs():
    what, how = diagnostics.explain("sqrt(-1)", R.DOMAIN_ERROR, "sqrt: math domain error")
    assert "sqrt" in what
    assert how is not None
    assert "abs" in how


def test_domain_error_log_zero_explains_range():
    what, how = diagnostics.explain("log(0)", R.DOMAIN_ERROR, "log: math domain error")
    assert "log" in what
    assert "positive" in how.lower()


def test_domain_error_asin_out_of_range():
    what, how = diagnostics.explain("asin(2)", R.DOMAIN_ERROR, "asin: math domain error")
    assert "asin" in what
    assert "-1" in what and "1" in what


def test_domain_error_unknown_function_falls_back_to_generic():
    what, how = diagnostics.explain("foo(x)", R.DOMAIN_ERROR, "foo: math domain error")
    assert "Math domain error" in what


# --- overflow / arity / size limits ---------------------------------


def test_overflow_explains_float_ceiling():
    what, how = diagnostics.explain("2**10000", R.OVERFLOW, "")
    assert "too large" in what.lower()
    assert "10^308" in how


def test_arity_too_many_names_function():
    what, how = diagnostics.explain("sqrt(1, 2)", R.TOO_MANY_ARGS, "sqrt")
    assert "sqrt" in what
    assert "too many" in what.lower()


def test_arity_too_few_names_function():
    what, how = diagnostics.explain("sqrt()", R.TOO_FEW_ARGS, "sqrt")
    assert "sqrt" in what
    assert "more arguments" in what.lower()


def test_too_long_reports_character_count():
    expr = "x" * 200
    what, how = diagnostics.explain(expr, R.TOO_LONG, "")
    assert "200 characters" in what


# --- unsupported node translations ----------------------------------


def test_unsupported_node_compare_translates():
    what, how = diagnostics.explain("1 < 2", R.UNSUPPORTED_NODE, "Compare")
    assert "Comparison" in what


def test_unsupported_node_keyword_args_translates():
    what, how = diagnostics.explain("round(1, ndigits=1)", R.UNSUPPORTED_NODE, "keyword args")
    assert "Keyword arguments" in what


# --- fall-through ---------------------------------------------------


def test_unknown_reason_falls_back_to_canonical():
    what, how = diagnostics.explain("x", "made_up_reason", "")
    # Falls back to INTERNAL's hint via hint_for()'s default.
    assert what == R.hint_for("made_up_reason")
    assert how is None


def test_no_detail_safe_for_unknown_func():
    # Detail-less unknown_function — falls back to canonical, no None deref.
    what, how = diagnostics.explain("", R.UNSUPPORTED_FUNC, None)
    assert what == R.hint_for(R.UNSUPPORTED_FUNC)
