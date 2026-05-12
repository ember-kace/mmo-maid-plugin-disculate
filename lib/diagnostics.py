"""Per-reason error explanations for /calc.

Each reason code can map to a handler that returns a (what, how) pair:
    - `what` identifies the specific problem in this user's input.
    - `how` suggests a concrete fix, or is None when no specific advice
      applies.

Unhandled reasons fall back to the canonical hint from reasons.hint_for.
Handlers are intentionally short — one sentence each — so the resulting
error embed stays compact.
"""

from difflib import get_close_matches
from typing import Iterable, Optional, Tuple

from . import reasons as R
from .functions import ALL_FUNCTION_NAMES, CONSTANTS

# difflib cutoff tuned to catch 1-2 character typos (`sqirt`/`sqrt`,
# `taw`/`tau`) while rejecting loose guesses (`cosecant`/`cos`). Keeps
# the false-positive rate low so suggestions remain trustworthy.
_SUGGESTION_CUTOFF = 0.7


def explain(
    expression: str,
    reason: str,
    detail: Optional[str],
) -> Tuple[str, Optional[str]]:
    """Return (what, how) for the given error context.

    `what` is a short identification of the specific problem.
    `how` is a concrete suggestion, or None if no specific fix applies.

    For reasons without a handler, falls back to (canonical_hint, None).
    """
    handler = _HANDLERS.get(reason)
    if handler is None:
        return R.hint_for(reason), None
    return handler(expression or "", detail or "")


# --- helpers --------------------------------------------------------


def _suggest(typo: str, choices: Iterable[str]) -> Optional[str]:
    """Conservative did-you-mean. Returns the single closest match
    above the cutoff, or None."""
    matches = get_close_matches(typo, list(choices), n=1, cutoff=_SUGGESTION_CUTOFF)
    return matches[0] if matches else None


def _parse_detail(detail: str) -> Tuple[Optional[str], Optional[int]]:
    """Parser.detail format is `<msg>` optionally suffixed with `@<offset>`.
    Returns (msg, offset). Either may be None if not present.
    """
    if not detail:
        return None, None
    if "@" in detail:
        msg, _, off_str = detail.rpartition("@")
        try:
            return (msg or None), int(off_str)
        except ValueError:
            return detail, None
    return detail, None


# --- per-reason handlers --------------------------------------------


def _explain_unknown_func(expression, detail):
    name = detail.strip()
    if not name:
        return R.hint_for(R.UNSUPPORTED_FUNC), None
    suggestion = _suggest(name, ALL_FUNCTION_NAMES)
    if suggestion:
        return (
            f"Unknown function `{name}`.",
            f"Did you mean `{suggestion}`? Run `/calc-help` for the full list.",
        )
    return (
        f"Unknown function `{name}`.",
        "Run `/calc-help` to see supported functions.",
    )


def _explain_unknown_name(expression, detail):
    name = detail.strip()
    if not name:
        return R.hint_for(R.UNSUPPORTED_NAME), None
    # Case-mismatch is the strongest signal (`Pi` -> `pi`).
    for c in CONSTANTS:
        if c.lower() == name.lower() and c != name:
            return (
                f"Unknown name `{name}`.",
                f"Constants are case-sensitive. Did you mean `{c}`?",
            )
    suggestion = _suggest(name, CONSTANTS)
    if suggestion:
        return (
            f"Unknown name `{name}`.",
            f"Did you mean `{suggestion}`?",
        )
    return (
        f"Unknown name `{name}`.",
        "Only `pi`, `e`, and `tau` are supported as constants.",
    )


def _explain_parse_error(expression, detail):
    s = expression.strip()
    opens = s.count("(")
    closes = s.count(")")
    if opens > closes:
        diff = opens - closes
        return (
            f"Unclosed parenthesis. {diff} more `(` than `)`.",
            f"Add {diff} `)` to balance the expression.",
        )
    if closes > opens:
        diff = closes - opens
        return (
            f"Too many `)` — {diff} extra.",
            f"Remove {diff} `)`, or add `(` to open them.",
        )
    if s and s[-1] in "+-*/":
        return (
            f"Expression ends with an operator (`{s[-1]}`).",
            "Add a value after the operator, or remove it.",
        )
    msg, offset = _parse_detail(detail)
    if offset is not None and msg:
        return (
            f"Syntax error near position {offset}: {msg}.",
            "Look at that position for typos, missing operators, or stray characters.",
        )
    return (
        "Syntax error in the expression.",
        "Check parentheses, operators, and that every function call has its arguments.",
    )


def _explain_div_by_zero(expression, detail):
    d = detail.strip()
    if not d:
        return ("Division by zero.", "Make sure the divisor isn't zero.")
    if d in ("/", "//"):
        return (
            f"Division by zero (operator `{d}`).",
            "Make sure the right-hand side of the division isn't zero.",
        )
    # Treat as function name (e.g. `mod`).
    return (
        f"Division by zero in `{d}(...)`.",
        "Make sure the second argument isn't zero.",
    )


_DOMAIN_GUIDANCE = {
    "sqrt": (
        "`sqrt` of a negative value isn't a real number.",
        "Try `sqrt(abs(x))` if you want the magnitude, or use a non-negative argument.",
    ),
    "log": (
        "`log` is undefined for zero or negative arguments.",
        "Use a positive argument; `log(0)` approaches negative infinity.",
    ),
    "ln": (
        "`ln` is undefined for zero or negative arguments.",
        "Use a positive argument; `ln(0)` approaches negative infinity.",
    ),
    "log10": (
        "`log10` is undefined for zero or negative arguments.",
        "Use a positive argument.",
    ),
    "log2": (
        "`log2` is undefined for zero or negative arguments.",
        "Use a positive argument.",
    ),
    "asin": (
        "`asin` requires an argument in `[-1, 1]`.",
        "Check the value being passed — it must fall between -1 and 1 inclusive.",
    ),
    "acos": (
        "`acos` requires an argument in `[-1, 1]`.",
        "Check the value being passed — it must fall between -1 and 1 inclusive.",
    ),
}


def _explain_domain_error(expression, detail):
    # Walker detail format: "<func>: <math-module-msg>" or just "<msg>".
    d = detail.strip()
    name = ""
    if ":" in d:
        name = d.split(":", 1)[0].strip()
    if name in _DOMAIN_GUIDANCE:
        return _DOMAIN_GUIDANCE[name]
    # Generic guidance — list the common offenders.
    return (
        "Math domain error.",
        "Common causes: `sqrt(-x)`, `log(0)` or `log` of a negative, "
        "`asin`/`acos` of a value outside `[-1, 1]`.",
    )


def _explain_overflow(expression, detail):
    return (
        "Result is too large to represent.",
        "Floats max out around `10^308`. Try smaller operands, "
        "or use `log` if you only need the magnitude.",
    )


def _explain_too_few_args(expression, detail):
    name = detail.strip()
    if not name:
        return R.hint_for(R.TOO_FEW_ARGS), None
    return (
        f"`{name}` needs more arguments.",
        "Check `/calc-help` for the expected signature.",
    )


def _explain_too_many_args(expression, detail):
    name = detail.strip()
    if not name:
        return R.hint_for(R.TOO_MANY_ARGS), None
    return (
        f"`{name}` was called with too many arguments.",
        "Check `/calc-help` for the expected signature.",
    )


def _explain_too_long(expression, detail):
    return (
        f"Expression is too long ({len(expression)} characters; limit is 120).",
        "Shorten the expression, or break the calculation into smaller pieces.",
    )


def _explain_depth(expression, detail):
    return (
        "Expression is too deeply nested.",
        "Limit nesting depth to 32 levels. Try flattening with intermediate values.",
    )


def _explain_node_count(expression, detail):
    return (
        "Expression has too many terms.",
        "Limit total node count to 200. Try simplifying.",
    )


# Translates the AST class names captured at validator raise sites
# into user-facing labels.
_NODE_LABELS = {
    "Compare": "Comparison operators (`<`, `>`, `==`)",
    "BoolOp": "Boolean operators (`and`, `or`)",
    "Lambda": "Lambda functions",
    "Subscript": "Indexing (`x[0]`)",
    "Attribute": "Attribute access (`x.y`)",
    "Dict": "Dict literals",
    "Set": "Set literals",
    "List": "List literals",
    "Tuple": "Tuple literals",
    "JoinedStr": "f-strings",
    "FormattedValue": "Formatted values",
    "Starred": "Starred arguments (`*args`)",
    "non-name call": "Calling a non-function value (e.g. `2(3)`)",
    "keyword args": "Keyword arguments (e.g. `round(1.5, ndigits=1)`)",
    "starred arg": "Starred arguments (`*args`)",
    "literal type str": "String literals",
    "literal type bytes": "Bytes literals",
    "literal type NoneType": "`None`",
    "boolean op": "Boolean operators (`and`, `or`)",
}


def _explain_unsupported_node(expression, detail):
    d = detail.strip()
    label = _NODE_LABELS.get(d)
    if label is None:
        # Some details are op-class names (e.g. `BitXor`); try a direct match.
        label = _NODE_LABELS.get(d.split()[0]) if d else None
    if label is None:
        return R.hint_for(R.UNSUPPORTED_NODE), None
    return (
        f"{label} aren't supported.",
        "/calc evaluates numeric math only — check `/calc-help` for what's allowed.",
    )


_HANDLERS = {
    R.UNSUPPORTED_FUNC: _explain_unknown_func,
    R.UNSUPPORTED_NAME: _explain_unknown_name,
    R.PARSE_ERROR: _explain_parse_error,
    R.DIV_BY_ZERO: _explain_div_by_zero,
    R.DOMAIN_ERROR: _explain_domain_error,
    R.OVERFLOW: _explain_overflow,
    R.TOO_FEW_ARGS: _explain_too_few_args,
    R.TOO_MANY_ARGS: _explain_too_many_args,
    R.TOO_LONG: _explain_too_long,
    R.DEPTH_EXCEEDED: _explain_depth,
    R.NODE_COUNT_EXCEEDED: _explain_node_count,
    R.UNSUPPORTED_NODE: _explain_unsupported_node,
}
