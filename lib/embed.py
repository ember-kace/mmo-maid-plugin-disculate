"""Discord response builders.

Outputs are dicts shaped like a standard Discord embed (title, description,
color, fields, footer). The SDK's exact embed-passing API is documented
in SDK-ASSUMPTIONS.md; handlers call respond with embeds=[...] and a
defensive content fallback.

Every user-visible string passes through _safe_text + _clip first.
allowed_mentions is always set to suppress role/user/everyone pings on
echoed input.
"""

import re
import unicodedata
from typing import Any, Dict, List

from . import reasons as R
from .functions import CATEGORY_ORDER, CONSTANTS, FUNCTIONS
from .parser import MAX_INPUT_LEN
from .walker import BUDGET_SECONDS

COLOR_OK = 0xC9A35A      # gold
COLOR_ERROR = 0xCC4444   # red
COLOR_INFO = 0x7A8AA0    # muted slate

EMBED_TITLE_MAX = 256
EMBED_DESC_MAX = 4096
EMBED_FIELD_NAME_MAX = 256
EMBED_FIELD_VALUE_MAX = 1024
EMBED_FOOTER_MAX = 2048
EMBED_TOTAL_MAX = 5800  # 200-char margin under Discord's 6000

ALLOWED_MENTIONS_NONE: Dict[str, Any] = {"parse": []}

_BIDI_CONTROL = re.compile(r"[‪-‮⁦-⁩]")
_MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")
_BARE_URL = re.compile(r"https?://\S+")
_MARKDOWN_MARKERS = ("```", "**", "__", "~~", "||", "`")


def safe_text(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = _BIDI_CONTROL.sub("", s)
    s = _MARKDOWN_LINK.sub(r"\1", s)
    s = _BARE_URL.sub("[link]", s)
    s = s.replace("@everyone", "@​everyone").replace("@here", "@​here")
    for marker in _MARKDOWN_MARKERS:
        s = s.replace(marker, "")
    return s


def clip(s: str, n: int) -> str:
    if s is None:
        return ""
    s = str(s)
    if len(s) <= n:
        return s
    if n <= 1:
        return s[:n]
    return s[: n - 1] + "…"


def enforce_total_cap(embed: Dict[str, Any], max_total: int = EMBED_TOTAL_MAX) -> Dict[str, Any]:
    title = embed.get("title", "") or ""
    desc = embed.get("description", "") or ""
    fields = embed.get("fields", []) or []
    footer_text = (embed.get("footer") or {}).get("text", "") or ""
    total = (
        len(title)
        + len(desc)
        + sum(len(f.get("name", "")) + len(f.get("value", "")) for f in fields)
        + len(footer_text)
    )
    if total <= max_total:
        return embed
    overage = total - max_total
    new_desc_len = max(0, len(desc) - overage - 50)
    embed["description"] = clip(desc, new_desc_len) if new_desc_len > 0 else ""
    return embed


def build_result_embed(
    expression: str,
    result_text: str,
    angle_mode: str,
    uses_trig: bool = False,
) -> Dict[str, Any]:
    expr = clip(safe_text(expression), 200)
    res = clip(safe_text(result_text), 200)
    desc = f"`{expr}` = **{res}**"
    embed: Dict[str, Any] = {
        "description": clip(desc, EMBED_DESC_MAX),
        "color": COLOR_OK,
    }
    # The angle mode is only meaningful when the expression actually used
    # a trig function. Suppress the footer otherwise so /calc 2+2 isn't
    # cluttered with irrelevant metadata.
    if uses_trig:
        footer = "angle: degrees" if angle_mode == "deg" else "angle: radians"
        embed["footer"] = {"text": clip(footer, EMBED_FOOTER_MAX)}
    return enforce_total_cap(embed)


def build_error_embed(expression: str, reason: str) -> Dict[str, Any]:
    hint = R.hint_for(reason)
    expr = clip(safe_text(expression), 200) if expression else ""
    desc_parts: List[str] = [hint]
    if expr:
        desc_parts.append(f"\nInput: `{expr}`")
    desc = "".join(desc_parts)
    embed = {
        "title": "Calc error",
        "description": clip(desc, EMBED_DESC_MAX),
        "color": COLOR_ERROR,
        "footer": {"text": f"reason: {reason}"},
    }
    return enforce_total_cap(embed)


def build_cooldown_embed(seconds_remaining: int) -> Dict[str, Any]:
    s = max(1, int(seconds_remaining))
    embed = {
        "title": "Slow down",
        "description": f"Wait {s} second{'s' if s != 1 else ''} before running /calc again.",
        "color": COLOR_INFO,
    }
    return enforce_total_cap(embed)


def build_config_embed(config: Dict[str, Any], changed: List[str]) -> Dict[str, Any]:
    rows = [
        ("Precision", str(config.get("precision"))),
        ("Angle mode", "Degrees" if config.get("angle_mode") == "deg" else "Radians"),
        ("Scientific threshold", f"10^{config.get('scientific_threshold')}"),
    ]
    fields = [
        {"name": clip(safe_text(name), EMBED_FIELD_NAME_MAX),
         "value": clip(safe_text(value), EMBED_FIELD_VALUE_MAX),
         "inline": True}
        for name, value in rows
    ]
    title = "Settings updated" if changed else "Current settings"
    desc = (
        "Changed: " + ", ".join(safe_text(c) for c in changed)
        if changed
        else "No changes. Showing current configuration."
    )
    embed = {
        "title": clip(title, EMBED_TITLE_MAX),
        "description": clip(desc, EMBED_DESC_MAX),
        "color": COLOR_OK if changed else COLOR_INFO,
        "fields": fields,
    }
    return enforce_total_cap(embed)


def build_config_error_embed(errors: List[str]) -> Dict[str, Any]:
    desc = "\n".join("- " + safe_text(e) for e in errors)
    embed = {
        "title": "Invalid configuration",
        "description": clip(desc, EMBED_DESC_MAX),
        "color": COLOR_ERROR,
        "footer": {"text": f"reason: {R.CONFIG_INVALID}"},
    }
    return enforce_total_cap(embed)


def _build_help_text() -> str:
    """Generate the help block from FUNCTIONS + CONSTANTS so it can't drift.

    Categories are emitted in CATEGORY_ORDER; functions inside each
    category follow their declaration order in FUNCTIONS. Constants and
    runtime limits come from their canonical modules.
    """
    by_cat: Dict[str, List[str]] = {cat_id: [] for cat_id, _ in CATEGORY_ORDER}
    for spec in FUNCTIONS:
        by_cat.setdefault(spec.category, []).append(spec.help)

    constants_line = "  ".join(f"`{name}`" for name in sorted(CONSTANTS))

    lines = [
        "**Operators:** `+`  `-`  `*`  `/`  `//`  `**`  unary `+`/`-`  parentheses",
        "**Percent:** trailing `%` divides by 100, e.g. `50%` = `0.5`, `200 * 5%` = `10`",
        f"**Constants:** {constants_line}  *(case-sensitive)*",
        "",
    ]
    for cat_id, cat_label in CATEGORY_ORDER:
        items = by_cat.get(cat_id, [])
        if not items:
            continue
        lines.append(f"**{cat_label}:** " + "  ".join(f"`{h}`" for h in items))
    lines += [
        "",
        "Trig honours `/calc-config angle_mode` (radians by default).",
        "Modulo via `mod(a, b)`. `^` is not power — use `**`.",
        "Bitwise ops, factorial, variables, `inf`/`nan` literals, and comparisons are not supported.",
        f"Max expression length: {MAX_INPUT_LEN} characters. "
        f"Evaluation budget: {int(BUDGET_SECONDS * 1000)} ms.",
    ]
    return "\n".join(lines)


HELP_TEXT = _build_help_text()


def build_help_embed() -> Dict[str, Any]:
    embed = {
        "title": "Disculate — quick reference",
        "description": clip(HELP_TEXT, EMBED_DESC_MAX),
        "color": COLOR_INFO,
        "footer": {"text": "Run /calc-config to change precision or angle mode."},
    }
    return enforce_total_cap(embed)
