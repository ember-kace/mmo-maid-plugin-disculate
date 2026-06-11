"""Bundle/artifact contract — pins the platform's acceptance requirements.

The platform validator (vendored at yourbot_sdk._validation, byte-for-byte
identical to the upload check) requires a top-level __main__.py and
cross-checks declared capabilities against byte patterns in the bundled
sources. v0.2.13 was rejected-at-baseline for missing_entry_point; these
tests keep that class of regression from ever reaching an upload.

The in-memory zip below mirrors tools/build_bundle.py exactly (same
allowlist) so the test never depends on a stale build/ artifact.
"""

import io
import json
import os
import zipfile

import pytest

from tools.build_bundle import INCLUDED_FILES

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

yourbot_validation = pytest.importorskip(
    "yourbot_sdk._validation",
    reason="yourbot-sdk not installed; platform-contract tests need it",
)


def _build_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel in INCLUDED_FILES:
            with open(os.path.join(ROOT, rel), "rb") as f:
                zf.writestr(rel, f.read())
    return buf.getvalue()


def _manifest() -> dict:
    with open(os.path.join(ROOT, "manifest.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def test_allowlist_includes_entry_point():
    assert "__main__.py" in INCLUDED_FILES
    assert "plugin.py" in INCLUDED_FILES
    assert "manifest.json" in INCLUDED_FILES


def test_entry_point_imports_plugin():
    with open(os.path.join(ROOT, "__main__.py"), "r", encoding="utf-8") as f:
        src = f.read()
    assert "import plugin" in src


def test_platform_validator_accepts_artifact():
    manifest = _manifest()
    result = yourbot_validation.validate_artifact(
        plugin_id=manifest["id"],
        version=manifest["version"],
        artifact_bytes=_build_zip_bytes(),
    )
    assert not result.has_errors, [
        f"{f.code}: {f.message}" for f in result.errors
    ]


def test_platform_validator_artifact_has_no_warnings():
    """Warnings don't block upload, but they shouldn't accumulate silently."""
    manifest = _manifest()
    result = yourbot_validation.validate_artifact(
        plugin_id=manifest["id"],
        version=manifest["version"],
        artifact_bytes=_build_zip_bytes(),
    )
    assert not result.warnings, [
        f"{f.code}: {f.message}" for f in result.warnings
    ]


def test_declared_capabilities_match_detected():
    """Declared == detected (plus the always-allowed implicit ones).

    The platform errors on detected-but-undeclared and warns on
    declared-but-undetected; this pins both directions locally.
    """
    manifest = _manifest()
    sources = []
    for rel in INCLUDED_FILES:
        if rel.endswith(".py"):
            with open(os.path.join(ROOT, rel), "rb") as f:
                sources.append(f.read())
    detected = set(yourbot_validation._detect_capabilities(sources))
    declared = set(manifest["capabilities_required"])
    assert detected <= declared, f"used but undeclared: {detected - declared}"
    # interaction:respond / storage:kv / storage:sql never warn even if
    # undetected (validator's own exempt set); everything else must be used.
    exempt = {"storage:kv", "storage:sql", "interaction:respond"}
    assert declared - detected <= exempt, (
        f"declared but unused: {declared - detected - exempt}"
    )
