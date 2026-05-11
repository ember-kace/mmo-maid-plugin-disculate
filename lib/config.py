"""Per-server calculator configuration.

KV is per-(server, plugin) by SDK contract, so the key is plain "config".
Value carries a schema version field; readers reject unknown versions and
fall back to defaults. Bumping CONFIG_SCHEMA_V on shape changes makes
old entries invisible without a migration.
"""

import time
from typing import Any, Dict, List, Optional, Tuple

CONFIG_KEY = "config"
CONFIG_SCHEMA_V = 1

PRECISION_MIN = 0
PRECISION_MAX = 10

SCIENTIFIC_THRESHOLD_MIN = 1
SCIENTIFIC_THRESHOLD_MAX = 20

ANGLE_MODES = ("rad", "deg")

DEFAULTS: Dict[str, Any] = {
    "v": CONFIG_SCHEMA_V,
    "precision": 6,
    "angle_mode": "rad",
    "scientific_threshold": 12,
    "updated_at": 0,
}


def get_config(ctx: Any) -> Dict[str, Any]:
    raw = None
    try:
        raw = ctx.kv.get(CONFIG_KEY)
    except Exception:
        raw = None
    if not isinstance(raw, dict) or raw.get("v") != CONFIG_SCHEMA_V:
        return dict(DEFAULTS)
    out = dict(DEFAULTS)
    p = raw.get("precision")
    if isinstance(p, int) and PRECISION_MIN <= p <= PRECISION_MAX:
        out["precision"] = p
    am = raw.get("angle_mode")
    if am in ANGLE_MODES:
        out["angle_mode"] = am
    st = raw.get("scientific_threshold")
    if isinstance(st, int) and SCIENTIFIC_THRESHOLD_MIN <= st <= SCIENTIFIC_THRESHOLD_MAX:
        out["scientific_threshold"] = st
    ua = raw.get("updated_at")
    if isinstance(ua, int):
        out["updated_at"] = ua
    return out


def validate_updates(
    precision: Optional[int],
    angle_mode: Optional[str],
    scientific_threshold: Optional[int],
) -> Tuple[Dict[str, Any], List[str]]:
    updates: Dict[str, Any] = {}
    errors: List[str] = []
    if precision is not None:
        if isinstance(precision, bool) or not isinstance(precision, int):
            errors.append(f"precision must be an integer in [{PRECISION_MIN}, {PRECISION_MAX}]")
        elif not (PRECISION_MIN <= precision <= PRECISION_MAX):
            errors.append(f"precision must be in [{PRECISION_MIN}, {PRECISION_MAX}]")
        else:
            updates["precision"] = precision
    if angle_mode is not None:
        if angle_mode not in ANGLE_MODES:
            errors.append("angle_mode must be 'rad' or 'deg'")
        else:
            updates["angle_mode"] = angle_mode
    if scientific_threshold is not None:
        if isinstance(scientific_threshold, bool) or not isinstance(scientific_threshold, int):
            errors.append(
                f"scientific_threshold must be an integer in "
                f"[{SCIENTIFIC_THRESHOLD_MIN}, {SCIENTIFIC_THRESHOLD_MAX}]"
            )
        elif not (SCIENTIFIC_THRESHOLD_MIN <= scientific_threshold <= SCIENTIFIC_THRESHOLD_MAX):
            errors.append(
                f"scientific_threshold must be in "
                f"[{SCIENTIFIC_THRESHOLD_MIN}, {SCIENTIFIC_THRESHOLD_MAX}]"
            )
        else:
            updates["scientific_threshold"] = scientific_threshold
    return updates, errors


def apply_updates(ctx: Any, updates: Dict[str, Any]) -> Dict[str, Any]:
    current = get_config(ctx)
    merged = dict(current)
    merged.update(updates)
    merged["v"] = CONFIG_SCHEMA_V
    merged["updated_at"] = int(time.time())
    ctx.kv.set(CONFIG_KEY, merged)
    return merged
