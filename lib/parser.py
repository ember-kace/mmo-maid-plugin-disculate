"""Input cleaning, percent preprocessing, parse + node allowlist validation.

The parse stage uses stdlib ast.parse(mode='eval'). Doing so does NOT
execute user input — ast.parse builds a syntax tree. The evaluator
(evaluator.py) walks that tree manually. eval(), exec(), and compile()
are never called on user-supplied data.

Validation runs before evaluation so depth/count caps and the node
allowlist trip without burning the evaluator's wall-clock budget.
"""

import ast
import math
import re
import unicodedata
from typing import Optional, Tuple

from . import reasons
from .functions import CONSTANTS, is_allowed_function

MAX_INPUT_LEN = 120
MAX_DEPTH = 32
MAX_NODES = 200
MAX_CALL_ARGS = 16

TRIG_FUNCTION_NAMES = frozenset({
    "sin", "cos", "tan", "asin", "acos", "atan", "atan2",
})

# The negative lookahead `(?!\s*[\w.\(])` ensures we only treat `%` as
# percent when it's NOT followed by another value. `50%` and `100% + 5`
# match (end-of-expression or followed by an operator). `5%2`, `5%pi`,
# and `5%(3+1)` do NOT match — they fall through to BinOp(Mod) which the
# validator then surfaces with the WANT_MOD hint.
_PERCENT_RE = re.compile(
    r"(\d+(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)\s*%(?!\s*[\w.\(])"
)

# Post-parse-failure analysis: spot implicit-multiplication patterns so
# the user gets a specific hint instead of a generic PARSE_ERROR.
_IMPLICIT_MULT_RE = re.compile(r"\d\s*\(|\d\s*[A-Za-z_]")

_DISALLOWED_UNICODE_CATEGORIES = ("Cc", "Cf", "Co", "Cs")

_ALLOWED_BINOPS = (
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Pow,
)
_ALLOWED_UNARYOPS = (ast.UAdd, ast.USub)


class CleanError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class ValidationError(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


def clean_expression(raw: object) -> str:
    if not isinstance(raw, str):
        raise CleanError(reasons.INVALID_CHARS)
    s = unicodedata.normalize("NFKC", raw).strip()
    if not s:
        raise CleanError(reasons.EMPTY)
    if len(s) > MAX_INPUT_LEN:
        raise CleanError(reasons.TOO_LONG)
    for c in s:
        if unicodedata.category(c) in _DISALLOWED_UNICODE_CATEGORIES:
            raise CleanError(reasons.INVALID_CHARS)
    return s


def preprocess_percent(s: str) -> str:
    return _PERCENT_RE.sub(r"(\1/100)", s)


def parse_and_validate(cleaned: str) -> ast.Expression:
    preprocessed = preprocess_percent(cleaned)
    try:
        tree = ast.parse(preprocessed, mode="eval")
    except SyntaxError:
        raise ValidationError(reasons.PARSE_ERROR)
    except ValueError:
        raise ValidationError(reasons.PARSE_ERROR)
    if not isinstance(tree, ast.Expression):
        raise ValidationError(reasons.PARSE_ERROR)
    state = _State()
    _validate(tree, 0, state)
    return tree


class _State:
    __slots__ = ("count",)

    def __init__(self):
        self.count = 0


def _validate(node: ast.AST, depth: int, state: _State) -> None:
    state.count += 1
    if state.count > MAX_NODES:
        raise ValidationError(reasons.NODE_COUNT_EXCEEDED)
    if depth > MAX_DEPTH:
        raise ValidationError(reasons.DEPTH_EXCEEDED)

    if isinstance(node, ast.Expression):
        _validate(node.body, depth + 1, state)
        return

    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValidationError(reasons.UNSUPPORTED_NODE, f"literal type {type(v).__name__}")
        # A literal like 1e1000 parses as Constant(value=inf) because the
        # number overflows IEEE-754. The isnan branch is defensive — Python
        # has no `nan` literal form (the identifier `nan` is an ast.Name,
        # not a Constant), so in practice only isinf fires here. Keeping
        # both checks makes the intent obvious and survives if Python ever
        # gains nan literal syntax.
        if isinstance(v, float) and (math.isinf(v) or math.isnan(v)):
            raise ValidationError(reasons.OVERFLOW, "literal overflows float")
        return

    if isinstance(node, ast.Name):
        if node.id not in CONSTANTS:
            raise ValidationError(reasons.UNSUPPORTED_NAME, node.id)
        return

    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type is ast.Mod:
            raise ValidationError(reasons.WANT_MOD)
        if op_type is ast.BitXor:
            raise ValidationError(reasons.WANT_POWER)
        if op_type in (ast.BitAnd, ast.BitOr, ast.LShift, ast.RShift):
            raise ValidationError(reasons.WANT_BITWISE)
        if not isinstance(node.op, _ALLOWED_BINOPS):
            raise ValidationError(reasons.UNSUPPORTED_NODE, op_type.__name__)
        _validate(node.left, depth + 1, state)
        _validate(node.right, depth + 1, state)
        return

    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.Invert):
            raise ValidationError(reasons.WANT_BITWISE)
        if not isinstance(node.op, _ALLOWED_UNARYOPS):
            raise ValidationError(reasons.UNSUPPORTED_NODE, type(node.op).__name__)
        _validate(node.operand, depth + 1, state)
        return

    if isinstance(node, ast.Compare):
        raise ValidationError(reasons.WANT_COMPARE)

    if isinstance(node, ast.BoolOp):
        raise ValidationError(reasons.WANT_COMPARE, "boolean op")

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            # ast.parse accepts `2(3)` as Call(func=Constant(2), args=[3]).
            # This is the implicit-multiplication idiom — surface it with
            # the same hint we use for the parse-error variant `2pi`.
            raise ValidationError(reasons.WANT_EXPLICIT_MULT, "non-name call")
        if node.keywords:
            raise ValidationError(reasons.UNSUPPORTED_NODE, "keyword args")
        for arg in node.args:
            if isinstance(arg, ast.Starred):
                raise ValidationError(reasons.UNSUPPORTED_NODE, "starred arg")
        if len(node.args) > MAX_CALL_ARGS:
            raise ValidationError(reasons.TOO_MANY_ARGS)
        if not is_allowed_function(node.func.id):
            raise ValidationError(reasons.UNSUPPORTED_FUNC, node.func.id)
        for arg in node.args:
            _validate(arg, depth + 1, state)
        return

    raise ValidationError(reasons.UNSUPPORTED_NODE, type(node).__name__)


def parse(raw: object) -> Tuple[Optional[ast.Expression], Optional[str]]:
    """Convenience: clean + parse + validate, returning (tree, error_reason)."""
    try:
        cleaned = clean_expression(raw)
    except CleanError as e:
        return None, e.reason
    try:
        tree = parse_and_validate(cleaned)
    except ValidationError as e:
        # Generic parse failures sometimes have a more specific cause we
        # can surface — e.g. `2(3)` or `2pi` are calculator-keyboard
        # idioms that mean "implicit multiplication."
        if e.reason == reasons.PARSE_ERROR and _IMPLICIT_MULT_RE.search(cleaned):
            return None, reasons.WANT_EXPLICIT_MULT
        return None, e.reason
    return tree, None


def uses_trig(tree: ast.Expression) -> bool:
    """True if the validated expression invokes any trig function."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in TRIG_FUNCTION_NAMES:
                return True
    return False
