def test_plugin_imports_without_error():
    import plugin  # noqa: F401


def test_plugin_registers_handlers():
    import plugin
    handlers = plugin.plugin._handlers
    assert "calc" in handlers.get("slash", {})
    assert "calc-config" in handlers.get("slash", {})
    assert "calc-help" in handlers.get("slash", {})
    assert handlers.get("ready"), "on_ready handler not registered"


def test_manifest_parses():
    import json
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "manifest.json")
    with open(path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["id"] == "disculate"
    capabilities = set(manifest["capabilities_required"])
    assert capabilities == {"interaction:respond", "storage:kv"}
    command_names = {c["name"] for c in manifest["slash_commands"]}
    assert command_names == {"calc", "calc-config", "calc-help"}
