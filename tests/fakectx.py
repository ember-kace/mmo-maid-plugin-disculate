"""Test doubles for the SDK ctx surface.

Each side-effect surface (kv, ephemeral, http, metrics, interaction, log)
records its calls so handler tests can assert behavior without spinning
up the real runtime.
"""

from typing import Any, Dict, List, Optional


class FakeKV:
    def __init__(self):
        self.store: Dict[str, Any] = {}
        self.calls: List[tuple] = []

    def get(self, key, default=None):
        self.calls.append(("get", key))
        return self.store.get(key, default)

    def set(self, key, value, ttl_seconds=None):
        self.calls.append(("set", key, value, ttl_seconds))
        self.store[key] = value

    def delete(self, key):
        self.calls.append(("delete", key))
        self.store.pop(key, None)

    def exists(self, key):
        self.calls.append(("exists", key))
        return key in self.store

    def increment(self, key, by=1):
        self.calls.append(("increment", key, by))
        cur = int(self.store.get(key, 0))
        self.store[key] = cur + by
        return self.store[key]

    def decrement(self, key, by=1):
        return self.increment(key, -by)

    def list(self, prefix=""):
        return [k for k in self.store if k.startswith(prefix)]

    def count(self, prefix=""):
        return len(self.list(prefix))


class FakeEphemeral:
    def __init__(self):
        self.cooldowns: Dict[str, int] = {}  # key -> remaining_seconds
        self.dedup_seen: Dict[str, bool] = {}
        self.flags: Dict[str, bool] = {}
        self.counters: Dict[str, int] = {}
        self.calls: List[tuple] = []

    def cooldown_check(self, key):
        self.calls.append(("cooldown_check", key))
        remaining = self.cooldowns.get(key, 0)
        return {"active": remaining > 0, "remaining_seconds": remaining}

    def cooldown_set(self, key, ttl_seconds):
        self.calls.append(("cooldown_set", key, ttl_seconds))
        self.cooldowns[key] = int(ttl_seconds)

    def dedup(self, key, ttl_seconds):
        self.calls.append(("dedup", key, ttl_seconds))
        first = key not in self.dedup_seen
        self.dedup_seen[key] = True
        return first

    def flag_set(self, key, ttl_seconds=None):
        self.calls.append(("flag_set", key, ttl_seconds))
        self.flags[key] = True

    def flag_check(self, key):
        self.calls.append(("flag_check", key))
        return self.flags.get(key, False)

    def counter(self, key, window_seconds=60):
        self.calls.append(("counter", key, window_seconds))
        return self.counters.get(key, 0)


class FakeMetrics:
    def __init__(self):
        self.recorded: List[Dict[str, Any]] = []

    def record(self, name, value=1, tags=None):
        self.recorded.append({"name": name, "value": value, "tags": tags or {}})

    def query(self, name, period="1h", group_by=None):
        return {"name": name, "period": period}

    def total(self, name, period="1h"):
        return sum(r["value"] for r in self.recorded if r["name"] == name)


class FakeInteraction:
    def __init__(self):
        self.responses: List[Dict[str, Any]] = []
        self.deferred: bool = False
        self.followups: List[Dict[str, Any]] = []
        self.modals: List[Dict[str, Any]] = []

    def respond(self, **kwargs):
        self.responses.append(kwargs)

    def defer(self):
        self.deferred = True

    def followup(self, **kwargs):
        self.followups.append(kwargs)

    def send_modal(self, **kwargs):
        self.modals.append(kwargs)


class FakeHTTP:
    def __init__(self):
        self.requests: List[Dict[str, Any]] = []

    def get(self, url, **kwargs):
        self.requests.append({"method": "GET", "url": url, **kwargs})
        return {"status": 404, "body_bytes": "", "headers": {}, "truncated": False}


class FakeCtx:
    def __init__(self, server_id: str = "test-server"):
        self.server_id = server_id
        self.plugin_id = "disculate"
        self.version = "1.0.0"
        self.capabilities = {"interaction:respond", "storage:kv"}
        self.kv = FakeKV()
        self.ephemeral = FakeEphemeral()
        self.http = FakeHTTP()
        self.metrics = FakeMetrics()
        self.interaction = FakeInteraction()
        self.log_entries: List[Dict[str, Any]] = []

    def log(self, msg, level="info", **extra):
        self.log_entries.append({"msg": msg, "level": level, **extra})

    def has_capability(self, name):
        return name in self.capabilities


def make_event(event_type="interaction_create", **overrides) -> Dict[str, Any]:
    # Matches the SDK runtime shape observed via plugin logs (May 2026):
    # flat user_id / permissions / command_options at the top level.
    base = {
        "type": event_type,
        "user_id": "111",
        "permissions": "0",
        "command_options": [],
    }
    base.update(overrides)
    return base


def slash_event(name: str, options=None, permissions: int = 0, user_id: str = "111") -> Dict[str, Any]:
    return {
        "type": "interaction_create",
        "interaction_type": 2,
        "command_name": name,
        "user_id": user_id,
        "permissions": str(permissions),
        "command_options": options or [],
    }


def opt(name: str, value):
    return {"name": name, "value": value}
