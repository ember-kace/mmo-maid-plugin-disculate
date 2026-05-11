"""Per-event request_id for log correlation.

Seed at handler entry with new_request_id(). Every structured log helper
below carries the current id automatically so grepping a log viewer by
request_id stitches an event back together across modules.
"""

import secrets
from contextvars import ContextVar
from typing import Any

_request_id: ContextVar[str] = ContextVar("disculate_request_id", default="-")


def new_request_id() -> str:
    rid = secrets.token_hex(4)
    _request_id.set(rid)
    return rid


def current() -> str:
    return _request_id.get()


def log_info(ctx: Any, msg: str, **extra: Any) -> None:
    ctx.log(msg, level="info", request_id=current(), **extra)


def log_warn(ctx: Any, msg: str, **extra: Any) -> None:
    ctx.log(msg, level="warning", request_id=current(), **extra)


def log_error(ctx: Any, msg: str, **extra: Any) -> None:
    ctx.log(msg, level="error", request_id=current(), **extra)


def log_debug(ctx: Any, msg: str, **extra: Any) -> None:
    ctx.log(msg, level="debug", request_id=current(), **extra)
