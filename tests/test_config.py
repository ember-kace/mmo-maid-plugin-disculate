from fakectx import FakeCtx
from lib import config as cfg


def test_defaults_when_no_kv_entry():
    ctx = FakeCtx()
    out = cfg.get_config(ctx)
    assert out["precision"] == 6
    assert out["angle_mode"] == "rad"
    assert out["scientific_threshold"] == 12


def test_defaults_when_schema_version_mismatch():
    ctx = FakeCtx()
    ctx.kv.set(cfg.CONFIG_KEY, {"v": 99, "precision": 1})
    out = cfg.get_config(ctx)
    assert out["precision"] == 6  # default
    assert out["angle_mode"] == "rad"


def test_partial_value_falls_back_to_defaults_per_field():
    ctx = FakeCtx()
    ctx.kv.set(cfg.CONFIG_KEY, {"v": cfg.CONFIG_SCHEMA_V, "precision": 3})
    out = cfg.get_config(ctx)
    assert out["precision"] == 3
    assert out["angle_mode"] == "rad"
    assert out["scientific_threshold"] == 12


def test_corrupted_value_returns_defaults():
    ctx = FakeCtx()
    ctx.kv.set(cfg.CONFIG_KEY, "not a dict")
    out = cfg.get_config(ctx)
    assert out["precision"] == 6


def test_validate_updates_rejects_out_of_range_precision():
    updates, errors = cfg.validate_updates(precision=99, angle_mode=None, scientific_threshold=None)
    assert updates == {}
    assert errors and "precision" in errors[0]


def test_validate_updates_rejects_negative_precision():
    updates, errors = cfg.validate_updates(precision=-1, angle_mode=None, scientific_threshold=None)
    assert "precision" in errors[0]


def test_validate_updates_rejects_bad_angle_mode():
    updates, errors = cfg.validate_updates(precision=None, angle_mode="gradians", scientific_threshold=None)
    assert "angle_mode" in errors[0]


def test_validate_updates_rejects_out_of_range_threshold():
    updates, errors = cfg.validate_updates(precision=None, angle_mode=None, scientific_threshold=99)
    assert "scientific_threshold" in errors[0]


def test_validate_updates_rejects_bool_as_int():
    updates, errors = cfg.validate_updates(precision=True, angle_mode=None, scientific_threshold=None)
    assert errors and "precision" in errors[0]


def test_validate_updates_accepts_valid():
    updates, errors = cfg.validate_updates(precision=2, angle_mode="deg", scientific_threshold=8)
    assert errors == []
    assert updates == {"precision": 2, "angle_mode": "deg", "scientific_threshold": 8}


def test_apply_updates_persists_and_returns_merged():
    ctx = FakeCtx()
    merged = cfg.apply_updates(ctx, {"precision": 4, "angle_mode": "deg"})
    assert merged["precision"] == 4
    assert merged["angle_mode"] == "deg"
    assert merged["scientific_threshold"] == 12  # default
    assert merged["v"] == cfg.CONFIG_SCHEMA_V
    assert merged["updated_at"] > 0
    # Round-trip through get_config
    read_back = cfg.get_config(ctx)
    assert read_back["precision"] == 4
    assert read_back["angle_mode"] == "deg"


def test_apply_updates_kv_read_exception_returns_defaults():
    ctx = FakeCtx()

    def boom(*args, **kwargs):
        raise RuntimeError("kv down")

    ctx.kv.get = boom
    out = cfg.get_config(ctx)
    assert out["precision"] == 6
