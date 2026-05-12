"""Embed-builder edge cases — cap enforcement, scrub helpers, etc.

The bigger functional coverage lives in test_handlers.py (handler →
embed pipeline). This file exists for cases that exercise embed.py
internals directly without going through the handler.
"""

from lib import embed as eb


def _measure(e):
    """Sum visible-text length the way Discord counts it."""
    return (
        len(e.get("title", "") or "")
        + len(e.get("description", "") or "")
        + sum(
            len(f.get("name", "")) + len(f.get("value", ""))
            for f in e.get("fields") or []
        )
        + len((e.get("footer") or {}).get("text", "") or "")
    )


# --- V2-01 / V4-05: enforce_total_cap with field-heavy embeds -------


def test_enforce_total_cap_trims_fields_when_description_alone_insufficient():
    """V2-01: a field-dominated embed exceeding the cap must be trimmed.
    Pre-v0.2.9 only the description was trimmed, leaving fields
    untouched — fields-heavy embeds could escape the cap."""
    big = "x" * 1000
    e = {
        "title": "T",
        "description": "short",
        "fields": [
            {"name": f"f{i}", "value": big, "inline": False}
            for i in range(10)
        ],
        "footer": {"text": "f"},
    }
    result = eb.enforce_total_cap(e, max_total=5800)
    assert _measure(result) <= 5800


def test_enforce_total_cap_preserves_under_budget_embed():
    """Embeds already under the cap pass through untouched."""
    e = {
        "title": "T",
        "description": "small description",
        "fields": [{"name": "a", "value": "b"}],
        "footer": {"text": "f"},
    }
    result = eb.enforce_total_cap(e, max_total=5800)
    assert result == e


def test_enforce_total_cap_still_trims_oversized_description():
    """Regression: pre-v0.2.9 behavior (description-only trim) still
    works for the common case where the description is the elastic
    field and fields are small."""
    e = {
        "title": "T",
        "description": "x" * 8000,
        "fields": [{"name": "a", "value": "b"}],
        "footer": {"text": "f"},
    }
    result = eb.enforce_total_cap(e, max_total=5800)
    assert _measure(result) <= 5800
    assert result["description"]  # not emptied entirely
    assert result["fields"] == e["fields"]  # fields untouched


def test_enforce_total_cap_drops_fields_when_halving_cannot_help():
    """Tiny-value fields (≤ 1 char) get dropped rather than halved.
    Trips the `len(value) <= 1` branch in pass 2."""
    e = {
        "title": "x" * 200,
        "description": "x" * 5500,
        "fields": [{"name": "a", "value": "b"} for _ in range(50)],
        "footer": {"text": "x" * 100},
    }
    # Total: 200 + 5500 + 50*2 + 100 = 5900. Description trim shaves
    # ~150; remaining 5750 is still over. Single-char field values
    # get dropped one-by-one in pass 2.
    result = eb.enforce_total_cap(e, max_total=5800)
    assert _measure(result) <= 5800


# --- build_help_embed always fits ----------------------------------


def test_build_help_embed_always_under_cap():
    """Help embed grows whenever FUNCTIONS grows. Lock it under the cap."""
    e = eb.build_help_embed()
    assert _measure(e) <= 5800
