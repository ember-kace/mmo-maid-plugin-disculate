"""Run the platform's artifact validator against build/disculate.zip.

The validator is vendored inside the installed SDK
(``yourbot_sdk._validation``) and is byte-for-byte identical to what the
platform runs on upload — running it here catches rejections (missing
entry point, undeclared capabilities, forbidden patterns) before submit.

It must run against the ARTIFACT, not the repo root: repo docstrings and
tests can trip the byte-pattern capability scanner, but they don't ship.

Run from project root:
    py tools/validate_artifact.py [version]

Exits 0 when the artifact has no errors (warnings are printed but don't
block, matching platform behavior).
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BUNDLE_PATH = os.path.join(ROOT, "build", "disculate.zip")


def validate(version: str | None = None) -> dict:
    """Validate the built bundle; returns the validator's payload dict.

    Raises FileNotFoundError if the bundle hasn't been built and
    ImportError if yourbot-sdk isn't installed.
    """
    from yourbot_sdk._validation import validate_artifact

    with open(os.path.join(ROOT, "manifest.json"), "r", encoding="utf-8") as f:
        manifest = json.load(f)
    with open(BUNDLE_PATH, "rb") as f:
        artifact_bytes = f.read()

    result = validate_artifact(
        plugin_id=manifest["id"],
        version=version or manifest["version"],
        artifact_bytes=artifact_bytes,
    )
    return result.to_payload()


def main() -> int:
    payload = validate(sys.argv[1] if len(sys.argv) > 1 else None)
    print(json.dumps(payload, indent=2))
    return 1 if payload["has_errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
