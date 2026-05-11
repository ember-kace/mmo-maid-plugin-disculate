"""Pre-ship audit gates.

Run from the project root:
    py tools/run_audit.py

Exits 0 on success, non-zero with a summary on first failure category.
Every check is mechanical so the gate can run in CI without human eyes.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

FORBIDDEN_IMPORTS = {
    "requests",
    "urllib.request",
    "urllib3",
    "httpx",
    "socket",
}
FORBIDDEN_ATTRS = {
    "os.environ",
    "os.getenv",
    "sys.argv",
}
TODO_RE = re.compile(r"\b(TODO|FIXME|XXX)\b")

SHIPPED_DIRS = ("lib",)
SHIPPED_FILES = ("plugin.py",)

MAX_BUNDLE_BYTES = 10 * 1024 * 1024
MAX_BUNDLE_UNCOMPRESSED = 40 * 1024 * 1024
MAX_BUNDLE_FILES = 200


class AuditError(Exception):
    pass


def _shipped_python_files():
    for fname in SHIPPED_FILES:
        path = os.path.join(ROOT, fname)
        if os.path.isfile(path):
            yield path
    for d in SHIPPED_DIRS:
        for dirpath, _, files in os.walk(os.path.join(ROOT, d)):
            for f in files:
                if f.endswith(".py"):
                    yield os.path.join(dirpath, f)


def check_imports():
    bad = []
    for path in _shipped_python_files():
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            raise AuditError(f"syntax error in {path}: {e}")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in FORBIDDEN_IMPORTS:
                        bad.append(f"{path}: forbidden import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.split(".")[0] in FORBIDDEN_IMPORTS:
                    bad.append(f"{path}: forbidden import from {node.module}")
            elif isinstance(node, ast.Attribute):
                # detect os.environ, os.getenv, sys.argv references
                target = _attribute_dotted(node)
                if target in FORBIDDEN_ATTRS:
                    bad.append(f"{path}: forbidden access {target}")
    if bad:
        raise AuditError("forbidden imports/accesses:\n  " + "\n  ".join(bad))


def _attribute_dotted(node):
    parts = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    else:
        return ""
    return ".".join(reversed(parts))


def check_no_eval_compile_exec():
    bad = []
    for path in _shipped_python_files():
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in {"eval", "exec", "compile"}:
                    bad.append(f"{path}:{node.lineno}: call to {node.func.id}()")
    if bad:
        raise AuditError("eval/exec/compile usage:\n  " + "\n  ".join(bad))


def check_todo_markers():
    bad = []
    for path in _shipped_python_files():
        with open(path, "r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                if TODO_RE.search(line):
                    bad.append(f"{path}:{lineno}: {line.strip()}")
    if bad:
        raise AuditError("outstanding TODO/FIXME/XXX markers:\n  " + "\n  ".join(bad))


def check_plugin_run_called():
    plugin_path = os.path.join(ROOT, "plugin.py")
    with open(plugin_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            if isinstance(call.func, ast.Attribute) and call.func.attr == "run":
                if isinstance(call.func.value, ast.Name) and call.func.value.id == "plugin":
                    found = True
    if not found:
        raise AuditError("plugin.py is missing `plugin.run()`")


def check_manifest():
    path = os.path.join(ROOT, "manifest.json")
    with open(path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    required = {"id", "name", "version", "description", "capabilities_required"}
    missing = required - set(manifest.keys())
    if missing:
        raise AuditError(f"manifest.json missing keys: {missing}")
    if manifest["id"] != "disculate":
        raise AuditError(f"manifest id mismatch: {manifest['id']!r}")
    if not re.match(r"^\d+\.\d+\.\d+$", manifest["version"]):
        raise AuditError(f"manifest version not semver: {manifest['version']}")
    allowed_caps = {
        "interaction:respond",
        "storage:kv",
    }
    declared = set(manifest["capabilities_required"])
    extra = declared - allowed_caps
    if extra:
        raise AuditError(f"manifest declares capabilities the audit doesn't expect: {extra}")
    cmds = {c["name"] for c in manifest.get("slash_commands", [])}
    expected_cmds = {"calc", "calc-config", "calc-help"}
    if cmds != expected_cmds:
        raise AuditError(f"slash command names mismatch: got {cmds}, expected {expected_cmds}")


def check_pytest():
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q", "--no-header"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise AuditError("pytest failed:\n" + proc.stdout[-2000:] + "\n" + proc.stderr[-1000:])


def check_bundle():
    bundle_path = os.path.join(ROOT, "build", "disculate.zip")
    if not os.path.exists(bundle_path):
        # Build it on the fly so audit is self-contained.
        from tools import build_bundle  # type: ignore
        bundle_path = build_bundle.build()
    size = os.path.getsize(bundle_path)
    if size > MAX_BUNDLE_BYTES:
        raise AuditError(f"bundle {size} bytes exceeds {MAX_BUNDLE_BYTES}")
    with zipfile.ZipFile(bundle_path) as zf:
        names = zf.namelist()
        uncompressed = sum(i.file_size for i in zf.infolist())
    if len(names) > MAX_BUNDLE_FILES:
        raise AuditError(f"bundle has {len(names)} files (>{MAX_BUNDLE_FILES})")
    if uncompressed > MAX_BUNDLE_UNCOMPRESSED:
        raise AuditError(f"bundle uncompressed {uncompressed} > {MAX_BUNDLE_UNCOMPRESSED}")


GATES = [
    ("manifest", check_manifest),
    ("imports", check_imports),
    ("no_eval", check_no_eval_compile_exec),
    ("todo_markers", check_todo_markers),
    ("plugin_run", check_plugin_run_called),
    ("pytest", check_pytest),
    ("bundle", check_bundle),
]


def main():
    failed = 0
    for name, fn in GATES:
        try:
            fn()
            print(f"  ok  {name}")
        except AuditError as e:
            failed += 1
            print(f"  FAIL  {name}\n{e}")
    if failed:
        print(f"\n{failed} gate(s) failed")
        sys.exit(1)
    print("\nall gates passed")


if __name__ == "__main__":
    sys.path.insert(0, ROOT)
    main()
