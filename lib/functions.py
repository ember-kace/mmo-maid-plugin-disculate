"""Function and constant allowlist for the walker.

Everything is driven from FUNCTIONS — one list of FunctionSpec records.
Adding a new function = one new entry. HELP_TEXT (in lib/embed.py) is
generated from this registry, so it can't drift.

All impl functions take (args, angle_mode). The angle_mode is only used
by trig/inverse-trig (everything else ignores it). The arity check is
centralized in call_function rather than repeated in each impl.

Pow is NOT in this module; ** is handled directly by the evaluator so
it can apply the DoS guard before computing.
"""

import math
from dataclasses import dataclass
from typing import Any, Callable, FrozenSet, List, Tuple, Union

ARITY_VARIADIC = -1

CATEGORY_BASIC = "basic"
CATEGORY_ROOTS_EXP_LOG = "roots_exp_log"
CATEGORY_TRIG = "trig"
CATEGORY_HYPERBOLIC = "hyperbolic"

CATEGORY_ORDER: List[Tuple[str, str]] = [
    (CATEGORY_BASIC, "Basic"),
    (CATEGORY_ROOTS_EXP_LOG, "Roots / exp / log"),
    (CATEGORY_TRIG, "Trig"),
    (CATEGORY_HYPERBOLIC, "Hyperbolic"),
]

CONSTANTS: dict = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
}


class _ArityError(Exception):
    def __init__(self, name: str, kind: str):
        super().__init__(f"{name}: {kind}")
        self.name = name
        self.kind = kind


def _check_arity(name: str, args: List[Any], expected) -> None:
    if expected == ARITY_VARIADIC:
        if len(args) < 1:
            raise _ArityError(name, "too_few")
        return
    lo, hi = expected if isinstance(expected, tuple) else (expected, expected)
    if len(args) < lo:
        raise _ArityError(name, "too_few")
    if len(args) > hi:
        raise _ArityError(name, "too_many")


# --- Pow guard (used by evaluator, not via FUNCTIONS) -----------------

# Bit-budget for int**int results. Lets small-base bignums stay exact
# (e.g. 2**100 is only 101 bits = 13 bytes), while still bounding any
# single pow() at ~512 bytes of bignum — well under the 64 MB sandbox.
# Pre-v0.2.9 we used two axis caps (exp > 64 OR base > 1_000_000); that
# collapsed 2**100 to a float, breaking `mod(2**100, 7)` and similar.
_POW_RESULT_BIT_BUDGET = 4096


def _safe_pow(base, exp):
    if isinstance(base, int) and isinstance(exp, int) and exp >= 0:
        # bit_length(0) == 0, so 0**N would falsely fit in 0 bits; the
        # max(1, ...) keeps the multiplication honest. `0**N` is also
        # trivially safe (0 or 1), so this is defense-in-depth only.
        bits = exp * max(1, abs(base).bit_length())
        if bits <= _POW_RESULT_BIT_BUDGET:
            return base ** exp
        return math.pow(base, exp)
    return math.pow(base, exp)


# --- Impls. Each takes (args, angle_mode). ----------------------------


def _i_abs(args, _am):
    return abs(args[0])


def _i_round(args, _am):
    if len(args) == 1:
        return round(args[0])
    ndigits = args[1]
    if isinstance(ndigits, float):
        if not ndigits.is_integer():
            raise ValueError("round: ndigits must be an integer")
        ndigits = int(ndigits)
    if not isinstance(ndigits, int):
        raise ValueError("round: ndigits must be an integer")
    return round(args[0], ndigits)


def _i_floor(args, _am):
    return math.floor(args[0])


def _i_ceil(args, _am):
    return math.ceil(args[0])


def _i_min(args, _am):
    return min(args)


def _i_max(args, _am):
    return max(args)


def _i_mod(args, _am):
    a, b = args[0], args[1]
    if b == 0:
        raise ZeroDivisionError("mod by zero")
    # Sign-follows-divisor for both int and float operands. Python's
    # built-in `%` does this for ints; math.fmod uses sign-follows-
    # dividend, which would give different math for `mod(-7, 3)` vs
    # `mod(-7.0, 3)`. Forcing one convention removes the inconsistency.
    if isinstance(a, int) and isinstance(b, int):
        return a % b
    return a - b * math.floor(a / b)


def _i_pow(args, _am):
    return _safe_pow(args[0], args[1])


def _i_sqrt(args, _am):
    return math.sqrt(args[0])


def _i_exp(args, _am):
    return math.exp(args[0])


def _i_log(args, _am):
    if len(args) == 1:
        return math.log(args[0])
    base = args[1]
    # math.log(x, base) computes log(x) / log(base). When base == 1,
    # log(base) == 0 and Python raises ZeroDivisionError — which the
    # walker would surface as `DIV_BY_ZERO`, but the real cause is a
    # domain violation on the base. Pre-empt with ValueError so the
    # walker maps it to DOMAIN_ERROR with the right hint (V1-03).
    if base == 1:
        raise ValueError("log: base must not be 1")
    if base <= 0:
        raise ValueError("log: base must be positive and not 1")
    return math.log(args[0], base)


def _i_log10(args, _am):
    return math.log10(args[0])


def _i_log2(args, _am):
    return math.log2(args[0])


def _i_ln(args, _am):
    return math.log(args[0])


def _i_sin(args, am):
    x = args[0]
    if am == "deg":
        x = math.radians(x)
    return math.sin(x)


def _i_cos(args, am):
    x = args[0]
    if am == "deg":
        x = math.radians(x)
    return math.cos(x)


def _i_tan(args, am):
    x = args[0]
    if am == "deg":
        x = math.radians(x)
    return math.tan(x)


def _i_asin(args, am):
    out = math.asin(args[0])
    if am == "deg":
        out = math.degrees(out)
    return out


def _i_acos(args, am):
    out = math.acos(args[0])
    if am == "deg":
        out = math.degrees(out)
    return out


def _i_atan(args, am):
    out = math.atan(args[0])
    if am == "deg":
        out = math.degrees(out)
    return out


def _i_atan2(args, am):
    out = math.atan2(args[0], args[1])
    if am == "deg":
        out = math.degrees(out)
    return out


def _i_sinh(args, _am):
    return math.sinh(args[0])


def _i_cosh(args, _am):
    return math.cosh(args[0])


def _i_tanh(args, _am):
    return math.tanh(args[0])


# --- Registry --------------------------------------------------------


@dataclass(frozen=True)
class FunctionSpec:
    name: str
    impl: Callable[[List[Any], str], Any]
    arity: Union[int, Tuple[int, int]]
    category: str
    help: str


FUNCTIONS: List[FunctionSpec] = [
    FunctionSpec("abs",    _i_abs,    1,      CATEGORY_BASIC, "abs(x)"),
    FunctionSpec("round",  _i_round,  (1, 2), CATEGORY_BASIC, "round(x[, n])"),
    FunctionSpec("floor",  _i_floor,  1,      CATEGORY_BASIC, "floor(x)"),
    FunctionSpec("ceil",   _i_ceil,   1,      CATEGORY_BASIC, "ceil(x)"),
    FunctionSpec("min",    _i_min,    ARITY_VARIADIC, CATEGORY_BASIC, "min(a, b, ...)"),
    FunctionSpec("max",    _i_max,    ARITY_VARIADIC, CATEGORY_BASIC, "max(a, b, ...)"),
    FunctionSpec("mod",    _i_mod,    2,      CATEGORY_BASIC, "mod(a, b)"),
    FunctionSpec("pow",    _i_pow,    2,      CATEGORY_BASIC, "pow(a, b)"),
    FunctionSpec("sqrt",   _i_sqrt,   1,      CATEGORY_ROOTS_EXP_LOG, "sqrt(x)"),
    FunctionSpec("exp",    _i_exp,    1,      CATEGORY_ROOTS_EXP_LOG, "exp(x)"),
    FunctionSpec("log",    _i_log,    (1, 2), CATEGORY_ROOTS_EXP_LOG, "log(x[, base])"),
    FunctionSpec("log10",  _i_log10,  1,      CATEGORY_ROOTS_EXP_LOG, "log10(x)"),
    FunctionSpec("log2",   _i_log2,   1,      CATEGORY_ROOTS_EXP_LOG, "log2(x)"),
    FunctionSpec("ln",     _i_ln,     1,      CATEGORY_ROOTS_EXP_LOG, "ln(x)"),
    FunctionSpec("sin",    _i_sin,    1,      CATEGORY_TRIG, "sin(x)"),
    FunctionSpec("cos",    _i_cos,    1,      CATEGORY_TRIG, "cos(x)"),
    FunctionSpec("tan",    _i_tan,    1,      CATEGORY_TRIG, "tan(x)"),
    FunctionSpec("asin",   _i_asin,   1,      CATEGORY_TRIG, "asin(x)"),
    FunctionSpec("acos",   _i_acos,   1,      CATEGORY_TRIG, "acos(x)"),
    FunctionSpec("atan",   _i_atan,   1,      CATEGORY_TRIG, "atan(x)"),
    FunctionSpec("atan2",  _i_atan2,  2,      CATEGORY_TRIG, "atan2(y, x)"),
    FunctionSpec("sinh",   _i_sinh,   1,      CATEGORY_HYPERBOLIC, "sinh(x)"),
    FunctionSpec("cosh",   _i_cosh,   1,      CATEGORY_HYPERBOLIC, "cosh(x)"),
    FunctionSpec("tanh",   _i_tanh,   1,      CATEGORY_HYPERBOLIC, "tanh(x)"),
]

_REGISTRY: dict = {spec.name: spec for spec in FUNCTIONS}
ALL_FUNCTION_NAMES: FrozenSet[str] = frozenset(_REGISTRY.keys())


def is_allowed_function(name: str) -> bool:
    return name in _REGISTRY


def call_function(name: str, args: List[Any], angle_mode: str) -> Any:
    try:
        spec = _REGISTRY[name]
    except KeyError:
        raise
    _check_arity(name, args, spec.arity)
    return spec.impl(args, angle_mode)
