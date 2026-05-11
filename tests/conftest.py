"""Test setup — stubs the SDK so the plugin imports without the real runtime.

The stub records what production imports actually use. test_stub_contract.py
asserts the stub exposes every name the plugin reaches for.
"""

import os
import sys
import types

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


if "mmo_maid_sdk" not in sys.modules:
    stub = types.ModuleType("mmo_maid_sdk")

    class _Decorators:
        def on_slash_command(self, name):
            def deco(fn):
                self._handlers.setdefault("slash", {})[name] = fn
                return fn
            return deco

        def on_event(self, name):
            def deco(fn):
                self._handlers.setdefault("event", {})[name] = fn
                return fn
            return deco

        def on_component(self, custom_id):
            def deco(fn):
                self._handlers.setdefault("component", {})[custom_id] = fn
                return fn
            return deco

        def on_modal_submit(self, custom_id):
            def deco(fn):
                self._handlers.setdefault("modal", {})[custom_id] = fn
                return fn
            return deco

        def on_ready(self, fn):
            self._handlers.setdefault("ready", []).append(fn)
            return fn

        def on_install(self, fn):
            self._handlers.setdefault("install", []).append(fn)
            return fn

        def on_enable(self, fn):
            self._handlers.setdefault("enable", []).append(fn)
            return fn

        def on_disable(self, fn):
            self._handlers.setdefault("disable", []).append(fn)
            return fn

        def on_uninstall(self, fn):
            self._handlers.setdefault("uninstall", []).append(fn)
            return fn

        def on_dashboard(self, method):
            def deco(fn):
                self._handlers.setdefault("dashboard", {})[method] = fn
                return fn
            return deco

        def schedule(self, seconds):
            def deco(fn):
                self._handlers.setdefault("schedule", []).append((seconds, fn))
                return fn
            return deco

    class Plugin(_Decorators):
        def __init__(self):
            self._handlers = {}

        def run(self):
            # In production this connects to the runner. In tests it must
            # be a no-op so importing plugin.py doesn't block.
            pass

    class Button:
        def __init__(self, label, custom_id=None, style="primary", url=None, disabled=False):
            self.label = label
            self.custom_id = custom_id
            self.style = style
            self.url = url
            self.disabled = disabled

    class ActionRow:
        def __init__(self, *components):
            self.components = list(components)

    class SelectMenu:
        def __init__(self, custom_id, options=(), placeholder=None, min_values=1, max_values=1):
            self.custom_id = custom_id
            self.options = list(options)
            self.placeholder = placeholder
            self.min_values = min_values
            self.max_values = max_values

    class SelectOption:
        def __init__(self, label, value, description=None, default=False):
            self.label = label
            self.value = value
            self.description = description
            self.default = default

    class TextInput:
        def __init__(self, custom_id, label, style="short", required=True, min_length=0, max_length=4000, placeholder=None, value=None):
            self.custom_id = custom_id
            self.label = label
            self.style = style
            self.required = required
            self.min_length = min_length
            self.max_length = max_length
            self.placeholder = placeholder
            self.value = value

    class Context:
        pass

    class SdkError(Exception):
        pass

    class CapabilityError(SdkError):
        pass

    class RateLimitError(SdkError):
        def __init__(self, msg="", retry_after=60):
            super().__init__(msg)
            self.retry_after = retry_after

    class DiscordApiError(SdkError):
        def __init__(self, msg="", status_code=0):
            super().__init__(msg)
            self.status_code = status_code

    class SdkPermissionError(SdkError):
        def __init__(self, msg="", permission=""):
            super().__init__(msg)
            self.permission = permission

    class ValidationError(SdkError):
        pass

    class KvQuotaError(SdkError):
        pass

    class RpcTimeoutError(SdkError):
        pass

    for name in (
        "Plugin", "Button", "ActionRow", "SelectMenu", "SelectOption", "TextInput",
        "Context", "SdkError", "CapabilityError", "RateLimitError", "DiscordApiError",
        "SdkPermissionError", "ValidationError", "KvQuotaError", "RpcTimeoutError",
    ):
        setattr(stub, name, locals()[name])

    sys.modules["mmo_maid_sdk"] = stub
