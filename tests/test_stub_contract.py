"""Locks the conftest SDK stub to the surface production imports.

If plugin.py grows a new SDK reference, this test fails and forces the
stub to keep pace. Without it, the stub drifts silently until tests pass
locally but the plugin fails at upload validation.
"""


def test_stub_exposes_names_production_uses():
    import mmo_maid_sdk

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
        assert hasattr(mmo_maid_sdk, name), f"stub missing: {name}"


def test_plugin_uses_only_stubbed_attributes():
    """Every attribute plugin.py reads from mmo_maid_sdk must be on the stub."""
    import ast
    import os

    plugin_path = os.path.join(os.path.dirname(__file__), "..", "plugin.py")
    with open(plugin_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    imported_from_sdk = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "mmo_maid_sdk":
            for alias in node.names:
                imported_from_sdk.add(alias.name)

    import mmo_maid_sdk
    for name in imported_from_sdk:
        assert hasattr(mmo_maid_sdk, name), f"plugin.py imports {name} but stub does not provide it"


def test_rate_limit_error_carries_retry_after():
    from mmo_maid_sdk import RateLimitError
    e = RateLimitError("x", retry_after=120)
    assert e.retry_after == 120


def test_discord_api_error_carries_status_code():
    from mmo_maid_sdk import DiscordApiError
    e = DiscordApiError("x", status_code=404)
    assert e.status_code == 404
