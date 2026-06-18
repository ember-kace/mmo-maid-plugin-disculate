"""Locks the conftest SDK stub to the surface production imports.

If plugin.py grows a new SDK reference, this test fails and forces the
stub to keep pace. Without it, the stub drifts silently until tests pass
locally but the plugin fails at upload validation.

The stub module name is ``yourbot_sdk`` (the package's canonical name
since SDK 0.6.0; ``mmo_maid_sdk`` is a deprecation shim slated for
removal). conftest installs the stub at that name before plugin import.
"""


def test_stub_exposes_names_production_uses():
    import yourbot_sdk

    required = [
        "Plugin",
        "Context",
        "Button",
        "ActionRow",
        "SelectMenu",
        "SelectOption",
        "TextInput",
        "SdkError",
        "CapabilityError",
        "RateLimitError",
        "DiscordApiError",
        "SdkPermissionError",
        "ValidationError",
        "KvQuotaError",
        "RpcTimeoutError",
    ]
    for name in required:
        assert hasattr(yourbot_sdk, name), f"stub missing: {name}"


def test_plugin_uses_only_stubbed_attributes():
    """Every attribute plugin.py reads from yourbot_sdk must be on the stub."""
    import ast
    import os

    plugin_path = os.path.join(os.path.dirname(__file__), "..", "plugin.py")
    with open(plugin_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    imported_from_sdk = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "yourbot_sdk":
            for alias in node.names:
                imported_from_sdk.add(alias.name)

    assert imported_from_sdk, "plugin.py no longer imports from yourbot_sdk?"

    import yourbot_sdk
    for name in imported_from_sdk:
        assert hasattr(yourbot_sdk, name), f"plugin.py imports {name} but stub does not provide it"


def test_plugin_does_not_import_legacy_sdk_name():
    """mmo_maid_sdk is a deprecation shim (renamed in SDK 0.6.0, removal
    planned). Production code must import the canonical name only."""
    import ast
    import os

    plugin_path = os.path.join(os.path.dirname(__file__), "..", "plugin.py")
    with open(plugin_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module != "mmo_maid_sdk", "use yourbot_sdk, not the deprecated shim"
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] != "mmo_maid_sdk", (
                    "use yourbot_sdk, not the deprecated shim"
                )


def test_rate_limit_error_carries_retry_after():
    from yourbot_sdk import RateLimitError
    e = RateLimitError("x", retry_after=120)
    assert e.retry_after == 120


def test_discord_api_error_carries_status_code():
    from yourbot_sdk import DiscordApiError
    e = DiscordApiError("x", status_code=404)
    assert e.status_code == 404


def test_sdk_errors_carry_stable_code():
    """0.7.x contract: every SdkError exposes a stable machine-readable
    ``code`` class attribute. The 0.7 transport branches on it before
    falling back to substring matching, so the stub must model it."""
    from yourbot_sdk import (
        CapabilityError,
        DiscordApiError,
        KvQuotaError,
        RateLimitError,
        SdkError,
        ValidationError,
    )
    assert SdkError().code == "SDK_ERROR"
    assert CapabilityError().code == "CAPABILITY_DENIED"
    assert RateLimitError().code == "RATE_LIMITED"
    assert DiscordApiError().code == "DISCORD_API_ERROR"
    assert ValidationError().code == "VALIDATION_ERROR"
    assert KvQuotaError().code == "KV_QUOTA_EXCEEDED"


def test_sdk_error_code_overridable_via_kwarg():
    """A newer host can ship a structured ``code`` the transport forwards
    via the keyword-only ``code=`` arg (e.g. QUOTA_EXCEEDED on a
    RateLimitError, whose class default is RATE_LIMITED)."""
    from yourbot_sdk import RateLimitError
    e = RateLimitError("quota gone", retry_after=1.5, code="QUOTA_EXCEEDED")
    assert e.code == "QUOTA_EXCEEDED"
    assert e.retry_after == 1.5
