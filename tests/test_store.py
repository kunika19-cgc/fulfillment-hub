"""The shared database: what one screen saves, another screen must load - exactly."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import store
from actions import claim_order, create_label, log_issue, pack_order, record
from data import make_world


def test_nothing_saved_yet_returns_none():
    assert store.load() is None


def test_roundtrip_keeps_every_value_and_type():
    w = make_world()
    oid = w["orders"][w["orders"].status == "label_ready"].order_id.iloc[0]
    claim_order(w, oid, "Asha")
    pack_order(w, oid)
    log_issue(w, "Stock", oid, "test", "Office")
    w["logged"].add((oid, "Black / S"))
    store.save(w)
    r = store.load()
    pd.testing.assert_frame_equal(w["products"], r["products"], check_dtype=False)
    a, b = w["orders"].reset_index(drop=True), r["orders"].reset_index(drop=True)
    plain = lambda d: d.drop(columns=["created_at", "staged_at"]).astype(object).where(lambda x: x.notna(), "")   # blank = None or NaN
    pd.testing.assert_frame_equal(plain(a), plain(b), check_dtype=False)
    assert (a.created_at - b.created_at).abs().max() < pd.Timedelta("1s")
    assert r["confusions"] == w["confusions"]
    assert r["now"] == w["now"] and r["issues"] == w["issues"] and r["logged"] == w["logged"]
    assert r["events"][oid].keys() == w["events"][oid].keys()
    assert r["orders"].is_priority.dtype == bool


def test_second_user_sees_first_users_change():
    store.save(make_world())
    office, warehouse = store.load(), store.load()
    oid = office["orders"][office["orders"].status == "new"].order_id.iloc[0]
    create_label(office, oid, "BlueRoute")
    store.save(office)
    assert store.load()["orders"].set_index("order_id").loc[oid, "status"] == "label_ready"
    assert warehouse["orders"].set_index("order_id").loc[oid, "status"] == "new"   # stale copy until it reloads


def test_reset_replaces_everything():
    w = make_world()
    log_issue(w, "Other", "-", "x", "Office")
    store.save(w)
    store.reset(make_world)
    assert len(store.load()["issues"]) == 3
