"""Format evaluator results for display.

Conventions:
- int results stay int with thousands-separators (`1,234`).
- floats that land exactly on an integer below the scientific threshold
  are displayed without a decimal point (`2.0` -> `2`).
- magnitudes above the threshold or genuinely below the chosen precision
  switch to scientific notation.
- otherwise fixed-point with the configured precision; trailing zeros
  trimmed.
"""

import math
from typing import Union

Number = Union[int, float]


def format_result(value: Number, precision: int = 6, scientific_threshold: int = 12) -> str:
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, int):
        return _format_int(value, precision, scientific_threshold)
    if isinstance(value, float):
        return _format_float(value, precision, scientific_threshold)
    return str(value)


def _format_int(v: int, precision: int, scientific_threshold: int) -> str:
    if v == 0:
        return "0"
    if abs(v) >= 10 ** scientific_threshold:
        # Same scientific policy as the float path so equal-valued
        # int and float render identically.
        return _scientific(float(v), max(1, precision))
    return f"{v:,}"


def _format_float(v: float, precision: int, scientific_threshold: int) -> str:
    if math.isnan(v):
        return "NaN"
    if math.isinf(v):
        return "+inf" if v > 0 else "-inf"
    if v == 0.0:
        return "0"

    abs_v = abs(v)
    big = 10 ** scientific_threshold
    # `small = 10**-precision`: any non-zero magnitude below this can't
    # be shown in fixed-point at the current precision (it would render
    # as "0.000…0"), so route to scientific instead.
    small = 10 ** -precision

    if abs_v >= big or abs_v < small:
        return _scientific(v, max(1, precision))

    if v.is_integer() and abs_v < big:
        as_int = int(v)
        return f"{as_int:,}"

    text = f"{v:,.{precision}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _scientific(v: float, precision: int) -> str:
    text = f"{v:.{precision}e}"
    mantissa, exp = text.split("e")
    mantissa = mantissa.rstrip("0").rstrip(".") if "." in mantissa else mantissa
    exp_sign = "+" if exp[0] != "-" else "-"
    exp_num = int(exp)
    return f"{mantissa}e{exp_sign}{abs(exp_num)}"
