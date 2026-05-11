"""Reason codes for /calc failures + their user-facing hints.

Every failure path returns one of these codes. The handler renders the
hint via hint_for(). Codes are stable enums; tag values for metrics
draw from this set so cardinality stays bounded.
"""

OK = "ok"

EMPTY = "empty"
INVALID_CHARS = "invalid_chars"
TOO_LONG = "too_long"
PARSE_ERROR = "parse_error"
UNSUPPORTED_NODE = "unsupported_node"
UNSUPPORTED_FUNC = "unsupported_function"
UNSUPPORTED_NAME = "unsupported_name"
DIV_BY_ZERO = "div_by_zero"
DOMAIN_ERROR = "domain_error"
OVERFLOW = "overflow"
DEPTH_EXCEEDED = "depth_exceeded"
NODE_COUNT_EXCEEDED = "node_count_exceeded"
TOO_MANY_ARGS = "too_many_args"
TOO_FEW_ARGS = "too_few_args"
TIMEOUT = "timeout"
COOLDOWN = "cooldown"
NOT_ADMIN = "not_admin"
CONFIG_INVALID = "config_invalid"
INTERNAL = "internal"

# Specific hint codes — emitted instead of UNSUPPORTED_NODE / PARSE_ERROR
# when we can recognize a common user mistake. Their hints redirect to
# the supported syntax instead of saying "not allowed."
WANT_POWER = "want_power"                  # ^ used; suggest **
WANT_MOD = "want_mod"                      # % used as operator; suggest mod()
WANT_COMPARE = "want_compare"              # ==, <, > etc.
WANT_BITWISE = "want_bitwise"              # &, |, <<, >>, ~
WANT_EXPLICIT_MULT = "want_explicit_mult"  # 2(3), 2pi — needs *

ALL_REASONS = frozenset({
    OK, EMPTY, INVALID_CHARS, TOO_LONG, PARSE_ERROR, UNSUPPORTED_NODE,
    UNSUPPORTED_FUNC, UNSUPPORTED_NAME, DIV_BY_ZERO, DOMAIN_ERROR,
    OVERFLOW, DEPTH_EXCEEDED, NODE_COUNT_EXCEEDED, TOO_MANY_ARGS,
    TOO_FEW_ARGS, TIMEOUT, COOLDOWN, NOT_ADMIN, CONFIG_INVALID, INTERNAL,
    WANT_POWER, WANT_MOD, WANT_COMPARE, WANT_BITWISE, WANT_EXPLICIT_MULT,
})

_HINTS = {
    OK: "ok",
    EMPTY: "Expression is empty.",
    INVALID_CHARS: "Expression contains control or bidi characters.",
    TOO_LONG: "Expression is too long (max 120 characters).",
    PARSE_ERROR: "Could not parse the expression. Check parentheses and operators.",
    UNSUPPORTED_NODE: "Expression uses syntax that is not allowed in /calc.",
    UNSUPPORTED_FUNC: "Unknown function. Run /calc-help to list supported functions.",
    UNSUPPORTED_NAME: "Unknown name. Only pi, e, and tau are supported (case-sensitive).",
    DIV_BY_ZERO: "Division by zero.",
    DOMAIN_ERROR: "Math domain error (e.g. sqrt of a negative number).",
    OVERFLOW: "Result is too large to represent.",
    DEPTH_EXCEEDED: "Expression is too deeply nested.",
    NODE_COUNT_EXCEEDED: "Expression has too many terms.",
    TOO_MANY_ARGS: "Too many arguments to a function.",
    TOO_FEW_ARGS: "Not enough arguments for that function.",
    TIMEOUT: "Evaluation took too long.",
    COOLDOWN: "Please wait a moment before running /calc again.",
    NOT_ADMIN: "Only server admins can run /calc-config.",
    CONFIG_INVALID: "Configuration value out of range.",
    INTERNAL: "Internal error. The incident has been logged.",
    WANT_POWER: "Use ** for power, not ^ (which would be bitwise XOR).",
    WANT_MOD: "Use mod(a, b) for modulo. Trailing `%` means percent (e.g. `50%` = 0.5).",
    WANT_COMPARE: "Comparisons aren't supported. /calc evaluates numeric expressions only.",
    WANT_BITWISE: "Bitwise operators aren't supported in /calc.",
    WANT_EXPLICIT_MULT: "Use `*` for multiplication, e.g. `2 * (3)` or `2 * pi`.",
}


def hint_for(reason: str) -> str:
    return _HINTS.get(reason, _HINTS[INTERNAL])
