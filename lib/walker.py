"""Walks a parser-validated AST and computes the result.

Validation already enforced the node allowlist; this module trusts node
shapes but still applies runtime guards:

- Wall-clock budget (default 200 ms) checked at each node visit.
- Pow guard: int**int with large exp routes through math.pow so the
  result clamps at float-overflow rather than ballooning into a bignum.
- math.* and arithmetic exceptions are converted to a reason code.
"""

import ast
import math
import time
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple, Union

from . import reasons
from .functions import CONSTANTS, _ArityError, _safe_pow, call_function

BUDGET_SECONDS = 0.2


@dataclass
class BinOpStep:
    """A single binary-operation step recorded during evaluation.

    `left` and `right` are the already-evaluated operand values, not the
    original AST. `op` is the rendered operator symbol (`+`, `-`, `*`,
    `/`, `//`, `**`). Embeds the entire computation: `left op right = result`.
    """
    left: Any
    op: str
    right: Any
    result: Any


@dataclass
class CallStep:
    """A single function-call step recorded during evaluation.

    `args` are the already-evaluated argument values. For nested calls
    (e.g. `sqrt(abs(-16))`) the inner call's step appears first in the
    trace list, then the outer call's.
    """
    name: str
    args: List[Any]
    result: Any


Step = Union[BinOpStep, CallStep]


_OP_SYMBOLS = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.Div: "/",
    ast.FloorDiv: "//",
    ast.Pow: "**",
}


class WalkError(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


class _Budget:
    __slots__ = ("deadline",)

    def __init__(self, seconds: float):
        self.deadline = time.monotonic() + seconds

    def check(self):
        if time.monotonic() > self.deadline:
            raise WalkError(reasons.TIMEOUT)


def run(
    tree: ast.Expression,
    angle_mode: str = "rad",
    budget_seconds: float = BUDGET_SECONDS,
    trace: Optional[List[Step]] = None,
) -> Any:
    """Walk a validated AST and return its value.

    If `trace` is a list (not None), the walker appends a `BinOpStep`
    or `CallStep` to it for every successful binary-op or function-call
    evaluation, in inner-first order. Caller owns the list; the walker
    only appends. UnaryOp / Constant / Name lookups don't emit steps
    (no meaningful computation).
    """
    budget = _Budget(budget_seconds)
    return _walk(tree.body, angle_mode, budget, trace)


def _walk(
    node: ast.AST,
    angle_mode: str,
    budget: _Budget,
    trace: Optional[List[Step]],
) -> Any:
    budget.check()
    result = _dispatch(node, angle_mode, budget, trace)
    # Centralized post-op finite check. Catches nan/inf leaking from any
    # operator or function call — no need for per-branch checks.
    if isinstance(result, float):
        if math.isnan(result):
            raise WalkError(reasons.DOMAIN_ERROR, "result is NaN")
        if math.isinf(result):
            raise WalkError(reasons.OVERFLOW, "result is infinite")
    return result


def _dispatch(
    node: ast.AST,
    angle_mode: str,
    budget: _Budget,
    trace: Optional[List[Step]],
) -> Any:
    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Name):
        try:
            return CONSTANTS[node.id]
        except KeyError:
            raise WalkError(reasons.UNSUPPORTED_NAME, node.id)

    if isinstance(node, ast.UnaryOp):
        v = _walk(node.operand, angle_mode, budget, trace)
        if isinstance(node.op, ast.UAdd):
            return +v
        if isinstance(node.op, ast.USub):
            return -v
        raise WalkError(reasons.UNSUPPORTED_NODE, type(node.op).__name__)

    if isinstance(node, ast.BinOp):
        left = _walk(node.left, angle_mode, budget, trace)
        right = _walk(node.right, angle_mode, budget, trace)
        result = _apply_binop(node.op, left, right)
        if trace is not None:
            trace.append(BinOpStep(
                left=left,
                op=_OP_SYMBOLS.get(type(node.op), "?"),
                right=right,
                result=result,
            ))
        return result

    if isinstance(node, ast.Call):
        args = [_walk(arg, angle_mode, budget, trace) for arg in node.args]
        result = _apply_call(node.func.id, args, angle_mode)
        if trace is not None:
            trace.append(CallStep(name=node.func.id, args=args, result=result))
        return result

    raise WalkError(reasons.UNSUPPORTED_NODE, type(node).__name__)


def _apply_binop(op: ast.operator, left: Any, right: Any) -> Any:
    try:
        if isinstance(op, ast.Add):
            return left + right
        if isinstance(op, ast.Sub):
            return left - right
        if isinstance(op, ast.Mult):
            return left * right
        if isinstance(op, ast.Div):
            if right == 0:
                raise WalkError(reasons.DIV_BY_ZERO, "/")
            return left / right
        if isinstance(op, ast.FloorDiv):
            if right == 0:
                raise WalkError(reasons.DIV_BY_ZERO, "//")
            return left // right
        if isinstance(op, ast.Pow):
            try:
                return _safe_pow(left, right)
            except OverflowError:
                raise WalkError(reasons.OVERFLOW)
            except ValueError:
                raise WalkError(reasons.DOMAIN_ERROR, "pow")
            except ZeroDivisionError:
                raise WalkError(reasons.DIV_BY_ZERO, "**")
    except OverflowError:
        raise WalkError(reasons.OVERFLOW)
    except ZeroDivisionError:
        raise WalkError(reasons.DIV_BY_ZERO)
    except (TypeError, ValueError) as e:
        raise WalkError(reasons.DOMAIN_ERROR, str(e))
    raise WalkError(reasons.UNSUPPORTED_NODE, type(op).__name__)


def _apply_call(name: str, args: list, angle_mode: str) -> Any:
    try:
        result = call_function(name, args, angle_mode)
    except _ArityError as e:
        if e.kind == "too_few":
            raise WalkError(reasons.TOO_FEW_ARGS, e.name)
        raise WalkError(reasons.TOO_MANY_ARGS, e.name)
    except KeyError:
        raise WalkError(reasons.UNSUPPORTED_FUNC, name)
    except ZeroDivisionError:
        # Carry the function name so diagnostics can render
        # "Division by zero in `mod(...)`" instead of a bare message.
        raise WalkError(reasons.DIV_BY_ZERO, name)
    except OverflowError:
        raise WalkError(reasons.OVERFLOW)
    except ValueError as e:
        # Prefix with the function name so the domain-error diagnostic
        # can match against _DOMAIN_GUIDANCE (sqrt, log, asin, ...).
        raise WalkError(reasons.DOMAIN_ERROR, f"{name}: {e}")
    except TypeError as e:
        raise WalkError(reasons.DOMAIN_ERROR, f"{name}: {e}")
    return result


def run_safe(
    tree: ast.Expression,
    angle_mode: str = "rad",
    budget_seconds: float = BUDGET_SECONDS,
    trace: Optional[List[Step]] = None,
) -> Tuple[Optional[Any], Optional[str], Optional[str]]:
    """Run the walker and return (value, error_reason, error_detail).
    Never raises.

    `trace`, if provided, is populated by the walker (see `run`). On the
    error path the trace contains whatever steps completed before the
    failure; callers typically discard it.

    `error_detail` is the context-specific info captured at the raise
    site (operator symbol for div-by-zero, function name for domain
    errors, etc.). Consumed by lib/diagnostics.py.
    """
    try:
        return run(tree, angle_mode, budget_seconds, trace=trace), None, None
    except WalkError as e:
        return None, e.reason, e.detail or None
    except RecursionError:
        return None, reasons.DEPTH_EXCEEDED, None
    except Exception:
        return None, reasons.INTERNAL, None
