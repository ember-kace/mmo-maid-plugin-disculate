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
from typing import Any, Optional, Tuple

from . import reasons
from .functions import CONSTANTS, _ArityError, _safe_pow, call_function

EVAL_BUDGET_SECONDS = 0.2


class EvalError(Exception):
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
            raise EvalError(reasons.TIMEOUT)


def evaluate(
    tree: ast.Expression,
    angle_mode: str = "rad",
    budget_seconds: float = EVAL_BUDGET_SECONDS,
) -> Any:
    budget = _Budget(budget_seconds)
    return _eval(tree.body, angle_mode, budget)


def _eval(node: ast.AST, angle_mode: str, budget: _Budget) -> Any:
    budget.check()
    result = _dispatch(node, angle_mode, budget)
    # Centralized post-op finite check. Catches nan/inf leaking from any
    # operator or function call — no need for per-branch checks.
    if isinstance(result, float):
        if math.isnan(result):
            raise EvalError(reasons.DOMAIN_ERROR, "result is NaN")
        if math.isinf(result):
            raise EvalError(reasons.OVERFLOW, "result is infinite")
    return result


def _dispatch(node: ast.AST, angle_mode: str, budget: _Budget) -> Any:
    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Name):
        try:
            return CONSTANTS[node.id]
        except KeyError:
            raise EvalError(reasons.UNSUPPORTED_NAME, node.id)

    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, angle_mode, budget)
        if isinstance(node.op, ast.UAdd):
            return +v
        if isinstance(node.op, ast.USub):
            return -v
        raise EvalError(reasons.UNSUPPORTED_NODE, type(node.op).__name__)

    if isinstance(node, ast.BinOp):
        left = _eval(node.left, angle_mode, budget)
        right = _eval(node.right, angle_mode, budget)
        return _apply_binop(node.op, left, right)

    if isinstance(node, ast.Call):
        args = [_eval(arg, angle_mode, budget) for arg in node.args]
        return _apply_call(node.func.id, args, angle_mode)

    raise EvalError(reasons.UNSUPPORTED_NODE, type(node).__name__)


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
                raise EvalError(reasons.DIV_BY_ZERO)
            return left / right
        if isinstance(op, ast.FloorDiv):
            if right == 0:
                raise EvalError(reasons.DIV_BY_ZERO)
            return left // right
        if isinstance(op, ast.Pow):
            try:
                return _safe_pow(left, right)
            except OverflowError:
                raise EvalError(reasons.OVERFLOW)
            except ValueError:
                raise EvalError(reasons.DOMAIN_ERROR)
            except ZeroDivisionError:
                raise EvalError(reasons.DIV_BY_ZERO)
    except OverflowError:
        raise EvalError(reasons.OVERFLOW)
    except ZeroDivisionError:
        raise EvalError(reasons.DIV_BY_ZERO)
    except (TypeError, ValueError) as e:
        raise EvalError(reasons.DOMAIN_ERROR, str(e))
    raise EvalError(reasons.UNSUPPORTED_NODE, type(op).__name__)


def _apply_call(name: str, args: list, angle_mode: str) -> Any:
    try:
        result = call_function(name, args, angle_mode)
    except _ArityError as e:
        if e.kind == "too_few":
            raise EvalError(reasons.TOO_FEW_ARGS, e.name)
        raise EvalError(reasons.TOO_MANY_ARGS, e.name)
    except KeyError:
        raise EvalError(reasons.UNSUPPORTED_FUNC, name)
    except ZeroDivisionError:
        raise EvalError(reasons.DIV_BY_ZERO)
    except OverflowError:
        raise EvalError(reasons.OVERFLOW)
    except ValueError as e:
        msg = str(e).lower()
        if "domain" in msg or "math" in msg:
            raise EvalError(reasons.DOMAIN_ERROR, str(e))
        raise EvalError(reasons.DOMAIN_ERROR, str(e))
    except TypeError as e:
        raise EvalError(reasons.DOMAIN_ERROR, str(e))
    return result


def evaluate_safe(
    tree: ast.Expression,
    angle_mode: str = "rad",
    budget_seconds: float = EVAL_BUDGET_SECONDS,
) -> Tuple[Optional[Any], Optional[str]]:
    """Run evaluate() and return (value, error_reason). Never raises."""
    try:
        return evaluate(tree, angle_mode, budget_seconds), None
    except EvalError as e:
        return None, e.reason
    except RecursionError:
        return None, reasons.DEPTH_EXCEEDED
    except Exception:
        return None, reasons.INTERNAL
