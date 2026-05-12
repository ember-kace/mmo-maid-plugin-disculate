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
from typing import Any, Dict, List, Optional

from . import reasons as R
from .format import format_result
from .functions import CATEGORY_ORDER, CONSTANTS, FUNCTIONS
from .parser import MAX_INPUT_LEN
from .walker import BUDGET_SECONDS, BinOpStep, CallStep, Step

COLOR_OK = 0xC9A35A      # gold
COLOR_ERROR = 0xCC4444   # red
COLOR_INFO = 0x7A8AA0    # muted slate

# Brand thumbnail rendered top-right of success embeds. Hosted in this
# repo (assets/disculate.webp) so the URL never moves out from under us.
# Rebranding = replace the file in place; Discord re-fetches within
# minutes. Do NOT change this URL — Discord's image proxy caches it.
BRAND_THUMBNAIL_URL = (
    "https://raw.githubusercontent.com/ember-kace/"
    "mmo-maid-plugin-disculate/main/assets/disculate.webp"
)
_BRAND_THUMBNAIL: Dict[str, str] = {"url": BRAND_THUMBNAIL_URL}

EMBED_TITLE_MAX = 256
EMBED_DESC_MAX = 4096
EMBED_FIELD_NAME_MAX = 256
EMBED_FIELD_VALUE_MAX = 1024
EMBED_FOOTER_MAX = 2048
EMBED_TOTAL_MAX = 5800  # 200-char margin under Discord's 6000

MAX_STEPS_RENDERED = 30  # safety; real expressions cap well below this

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


def safe_text_in_code(s: str) -> str:
    """Like safe_text but for strings destined to live inside Discord
    inline-code spans (single backticks).

    Inside backticks, the only markdown Discord still interprets is the
    backtick itself (it closes the span). So `**`, `__`, `~~`, `||` are
    safe to display literally — and we *want* `**` to display literally
    because it's a valid Python operator (Pow), which users type often
    in math expressions (`2**8`, `1.07 ** 10`).

    Still strips: bidi controls, markdown links, bare URLs, @-mention
    patterns, single + triple backticks (which would break out of the
    inline-code context and let downstream chars become real markdown).
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = _BIDI_CONTROL.sub("", s)
    s = _MARKDOWN_LINK.sub(r"\1", s)
    s = _BARE_URL.sub("[link]", s)
    s = s.replace("@everyone", "@​everyone").replace("@here", "@​here")
    # Only backticks would actually escape the inline-code context.
    s = s.replace("```", "")
    s = s.replace("`", "")
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


def _format_step(step: Step, precision: int, scientific_threshold: int) -> str:
    fmt = lambda v: format_result(v, precision, scientific_threshold)
    if isinstance(step, BinOpStep):
        return f"`{fmt(step.left)} {step.op} {fmt(step.right)}` = `{fmt(step.result)}`"
    # CallStep
    args = ", ".join(fmt(a) for a in step.args)
    return f"`{step.name}({args})` = `{fmt(step.result)}`"


def format_steps(
    trace: List[Step],
    precision: int,
    scientific_threshold: int,
) -> Optional[str]:
    """Render a trace as a numbered string for the Steps embed field.

    Returns None for an empty trace so callers can pass-through to
    `build_result_embed(steps_text=None)`. Capped at MAX_STEPS_RENDERED;
    if the trace is longer, a "… (N more)" line is appended.
    """
    if not trace:
        return None
    capped = trace[:MAX_STEPS_RENDERED]
    lines = [
        f"{i + 1}. {_format_step(s, precision, scientific_threshold)}"
        for i, s in enumerate(capped)
    ]
    if len(trace) > MAX_STEPS_RENDERED:
        lines.append(f"… ({len(trace) - MAX_STEPS_RENDERED} more)")
    return "\n".join(lines)


def build_result_embed(
    expression: str,
    result_text: str,
    angle_mode: str,
    uses_trig: bool = False,
    steps_text: Optional[str] = None,
) -> Dict[str, Any]:
    # Expression goes inside backticks (inline code) — use the
    # inline-code-aware scrubber so legitimate Python operators
    # like `**` survive into the display. Result goes inside a `##`
    # markdown header where `**` would render as bold, so it uses
    # the strict safe_text.
    expr = clip(safe_text_in_code(expression), 200)
    res = clip(safe_text(result_text), 200)
    # Header-hero layout: small monospace expression on top, large
    # `##`-header result below. Discord renders `##` inside embed
    # descriptions as a larger bold heading (markdown headers, post-
    # 2023). No `**` around the result — the header is already
    # emphasised; double-bold is noise.
    desc = f"`{expr}`\n\n## = {res}"
    embed: Dict[str, Any] = {
        "description": clip(desc, EMBED_DESC_MAX),
        "color": COLOR_OK,
        "thumbnail": _BRAND_THUMBNAIL,
    }
    # Optional Steps field — populated by the handler when the
    # expression had >= 2 traceable nodes (smart-auto threshold).
    if steps_text:
        embed["fields"] = [{
            "name": "Steps",
            "value": clip(steps_text, EMBED_FIELD_VALUE_MAX),
            "inline": False,
        }]
    # Angle mode footer only when the expression actually used a trig
    # function — keeps non-trig results clean.
    if uses_trig:
        footer = "angle: degrees" if angle_mode == "deg" else "angle: radians"
        embed["footer"] = {"text": clip(footer, EMBED_FOOTER_MAX)}
    return enforce_total_cap(embed)


def build_error_embed(expression: str, reason: str) -> Dict[str, Any]:
    # Color + reason-code footer already establish "this is an error";
    # the old "Calc error" title was redundant. Hint becomes the primary
    # content; the backticked input speaks for itself (no "Input:" label).
    hint = R.hint_for(reason)
    # Expression renders inside backticks; use the inline-code-aware
    # scrubber so `**` etc. show literally (matches v0.2.7 result embed).
    expr = clip(safe_text_in_code(expression), 200) if expression else ""
    desc_parts: List[str] = [hint]
    if expr:
        desc_parts.append(f"\n`{expr}`")
    desc = "".join(desc_parts)
    embed = {
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
    embed: Dict[str, Any] = {
        "title": clip(title, EMBED_TITLE_MAX),
        "description": clip(desc, EMBED_DESC_MAX),
        "color": COLOR_OK if changed else COLOR_INFO,
        "fields": fields,
    }
    # Thumbnail only on the "Settings updated" path (admin actually
    # changed a value). The read-only "Current settings" view uses
    # INFO color and stays plain alongside cooldown / errors.
    if changed:
        embed["thumbnail"] = _BRAND_THUMBNAIL
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


def _build_help_payload() -> Dict[str, Any]:
    """Generate help payload (description, fields, footer) from FUNCTIONS +
    CONSTANTS so it can't drift. Categories are emitted in CATEGORY_ORDER;
    functions inside each category follow their declaration order in
    FUNCTIONS. Runtime limits come from their canonical modules so the
    footer always reflects the active values.
    """
    by_cat: Dict[str, List[str]] = {cat_id: [] for cat_id, _ in CATEGORY_ORDER}
    for spec in FUNCTIONS:
        by_cat.setdefault(spec.category, []).append(spec.help)

    constants_line = "  ".join(f"`{name}`" for name in sorted(CONSTANTS))

    description = "\n".join([
        "**Operators**  `+`  `-`  `*`  `/`  `//`  `**`  unary `+`/`-`  parens",
        "**Percent**  trailing `%` divides by 100 — e.g. `50%` = `0.5`",
        f"**Constants**  {constants_line}  *(case-sensitive)*",
    ])

    # One inline field per function category. Functions render one-per-line
    # inside each field so Discord's narrow column doesn't wrap awkwardly.
    fields: List[Dict[str, Any]] = []
    for cat_id, cat_label in CATEGORY_ORDER:
        items = by_cat.get(cat_id, [])
        if not items:
            continue
        value = "\n".join(f"`{h}`" for h in items)
        fields.append({
            "name": clip(cat_label, EMBED_FIELD_NAME_MAX),
            "value": clip(value, EMBED_FIELD_VALUE_MAX),
            "inline": True,
        })

    notes = (
        "Trig honours `/calc-config angle_mode` (radians by default). "
        "Modulo via `mod(a, b)`. `^` is not power — use `**`. "
        "Bitwise ops, factorial, variables, `inf`/`nan` literals, and "
        "comparisons are not supported."
    )
    fields.append({
        "name": "Notes",
        "value": clip(notes, EMBED_FIELD_VALUE_MAX),
        "inline": False,
    })

    footer_text = (
        f"Max {MAX_INPUT_LEN} chars · "
        f"{int(BUDGET_SECONDS * 1000)} ms budget · "
        "/calc-config for precision & angle"
    )

    return {
        "description": description,
        "fields": fields,
        "footer_text": footer_text,
    }


def build_help_embed() -> Dict[str, Any]:
    payload = _build_help_payload()
    embed = {
        "title": "Disculate — quick reference",
        "description": clip(payload["description"], EMBED_DESC_MAX),
        "color": COLOR_INFO,
        "thumbnail": _BRAND_THUMBNAIL,
        "fields": payload["fields"],
        "footer": {"text": clip(payload["footer_text"], EMBED_FOOTER_MAX)},
    }
    return enforce_total_cap(embed)
