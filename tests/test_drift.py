"""Three-way drift guards: code registrations == manifest == docs.

Each of these surfaces is edited independently, so nothing structural
stops them from drifting apart — a renamed command would still pass unit
tests while the manifest registers the old name with Discord. These
guards make the drift a test failure.
"""

import ast
import json
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _manifest_command_names() -> set:
    with open(os.path.join(ROOT, "manifest.json"), "r", encoding="utf-8") as f:
        manifest = json.load(f)
    return {c["name"] for c in manifest.get("slash_commands", [])}


def _registered_command_names() -> set:
    """Slash command names as plugin.py actually registers them.

    Read from the live registry (the conftest stub records decorator
    calls), not from source text — so renames, indirection, or loops
    all stay covered.
    """
    import plugin
    return set(plugin.plugin._handlers.get("slash", {}))


def test_registered_commands_match_manifest():
    assert _registered_command_names() == _manifest_command_names()


def test_manifest_commands_documented_in_readme():
    with open(os.path.join(ROOT, "README.md"), "r", encoding="utf-8") as f:
        readme = f.read()
    for name in _manifest_command_names():
        assert f"/{name}" in readme, f"/{name} missing from README"


def test_help_payload_lists_every_command():
    """The in-Discord /calc-help Commands field must cover exactly the
    manifest command set — a new command that never appears in help is
    undiscoverable to users (v0.4.0 Commands overview)."""
    from lib import embed as eb

    payload = eb._build_help_payload()
    text = payload["description"] + " ".join(
        f["name"] + " " + f["value"] for f in payload["fields"]
    )
    for name in _manifest_command_names():
        assert f"/{name}" in text, f"/{name} missing from /calc-help payload"


def test_manifest_options_match_handler_reads():
    """Every option name the calc/calc-config handlers read out of
    ``_options(event)`` must exist in the manifest schema (else Discord
    never sends it), and vice versa for required options."""
    with open(os.path.join(ROOT, "manifest.json"), "r", encoding="utf-8") as f:
        manifest = json.load(f)
    by_cmd = {
        c["name"]: {o["name"] for o in c.get("options", [])}
        for c in manifest["slash_commands"]
    }
    # Option keys plugin.py reads via opts.get("...") per handler.
    with open(os.path.join(ROOT, "plugin.py"), "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
    reads_by_func = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("cmd_"):
            reads = set()
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "get"
                    and isinstance(sub.func.value, ast.Name)
                    and sub.func.value.id == "opts"
                    and sub.args
                    and isinstance(sub.args[0], ast.Constant)
                ):
                    reads.add(sub.args[0].value)
            reads_by_func[node.name] = reads
    assert reads_by_func["cmd_calc"] <= by_cmd["calc"], (
        f"cmd_calc reads options not in manifest: "
        f"{reads_by_func['cmd_calc'] - by_cmd['calc']}"
    )
    assert reads_by_func["cmd_calc_config"] == by_cmd["calc-config"], (
        "calc-config handler reads and manifest options diverged"
    )


def test_requirements_dev_tracks_deployed_sdk_line():
    """The dev/test pin must permit the SDK line the platform deploys
    (0.7.x as of 2026-06). The audit runs the validator vendored INSIDE
    the installed SDK; a pin capped below 0.7 would let a contributor
    validate against a stale vendored validator that no longer matches
    upload. This guards the v0.3.1 SDK-compat bump from regressing.
    """
    from packaging.requirements import Requirement

    path = os.path.join(ROOT, "requirements-dev.txt")
    with open(path, "r", encoding="utf-8") as f:
        lines = [
            ln.strip()
            for ln in f
            if ln.strip() and not ln.strip().startswith("#")
        ]
    sdk_lines = [ln for ln in lines if ln.lower().startswith("yourbot-sdk")]
    assert sdk_lines, "yourbot-sdk not pinned in requirements-dev.txt"
    spec = Requirement(sdk_lines[0]).specifier
    assert spec.contains("0.7.1"), (
        f"dev pin {sdk_lines[0]!r} excludes the deployed SDK line 0.7.x"
    )
