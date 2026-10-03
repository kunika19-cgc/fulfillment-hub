"""Rule tests (no browser needed). Run from the project folder:  pytest -q"""
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from actions import create_label, handover, pack_order, rebook
from data import make_world
from logic import DONE, courier_performance, enrich, next_slot, recommend_courier, stage_breakdown, success_metrics, top_bottleneck


def busiest_sku(w):
    """The product with the most open orders (so the stock tests always have something to work with)."""
    return w["orders"][~w["orders"].status.isin(DONE)].sku.value_counts().index[0]


def by_id(w, oid):
    return w["orders"].set_index("order_id").loc[oid]


def test_countdown_follows_the_real_clock():
    w = make_world()
    a = enrich(w, w["now"] + timedelta(minutes=1)).set_index("order_id")
    b = enrich(w, w["now"] + timedelta(minutes=11)).set_index("order_id")
    open_ids = a.index[~a.status.isin(DONE)]
    assert ((a.loc[open_ids, "mins_left"] - b.loc[open_ids, "mins_left"]) == 10).all()


def test_stock_is_reserved_so_two_orders_cannot_claim_the_last_unit():
    w = make_world()
    o = enrich(w).set_index("order_id")
    sku = busiest_sku(w)
    w["products"].loc[w["products"].sku == sku, "main_stock"] = 1
    w["orders"].loc[w["orders"].sku == sku, "qty"] = 1
    open_ids = [i for i in w["orders"][w["orders"].sku == sku].order_id if o.loc[i, "status"] not in DONE]
    assert len(open_ids) >= 2
    o = enrich(w).set_index("order_id").loc[open_ids]
    assert o.stock_short.sum() == len(open_ids) - 1      # exactly one order gets the unit
    assert o.cant_pick.sum() == 0                        # ...each one alone would have looked fine


def test_priority_order_gets_the_stock_first():
    w = make_world()
    sku = busiest_sku(w)
    w["products"].loc[w["products"].sku == sku, "main_stock"] = 1
    m = (w["orders"].sku == sku) & ~w["orders"].status.isin(DONE)
    w["orders"].loc[m, ["qty", "is_priority"]] = [1, False]
    ids = w["orders"][m].order_id.tolist()
    w["orders"].loc[w["orders"].order_id == ids[-1], "is_priority"] = True
    o = enrich(w).set_index("order_id")
    assert not o.loc[ids[-1], "stock_short"]


def test_packing_takes_stock_off_the_shelf_and_gives_a_slot():
    w = make_world()
    o = enrich(w)
    r = o[(o.status == "label_ready") & ~o.cant_pick].iloc[0]
    before = int(w["products"].set_index("sku").loc[r.sku, "main_stock"])
    slot = pack_order(w, r.order_id)
    assert int(w["products"].set_index("sku").loc[r.sku, "main_stock"]) == before - r.qty
    assert by_id(w, r.order_id).status == "staged" and by_id(w, r.order_id).slot == slot
    assert slot.startswith(w["couriers"].set_index("courier").lane[r.courier])
    assert {2, 3} <= set(w["events"][r.order_id])


def test_staging_slots_never_collide():
    w = make_world()
    s = w["orders"][w["orders"].status == "staged"]
    assert s.slot.is_unique
    nxt = next_slot(w["orders"], w["couriers"], "BlueRoute")
    assert nxt not in set(s.slot)


def test_label_records_courier_and_time():
    w = make_world()
    oid = enrich(w).query("status == 'new'").order_id.iloc[0]
    create_label(w, oid, "IndiaPost Economy")
    assert by_id(w, oid).status == "label_ready" and by_id(w, oid).courier == "IndiaPost Economy"
    assert 1 in w["events"][oid]


def test_courier_recommendation():
    cs = make_world()["couriers"]
    assert recommend_courier(cs, 0, True) == "Speedex Express"        # fastest still reachable
    assert recommend_courier(cs, 0, False) == "BlueRoute"             # cheapest 2-day option
    assert recommend_courier(cs, 30, True) == "BlueRoute"             # Speedex too close to leaving
    assert recommend_courier(cs, 999, False) in cs.courier.tolist()   # everyone gone: still returns something


def test_rebook_moves_staged_boxes_to_the_new_lane():
    w = make_world()
    o = enrich(w)
    ids = o[(o.status == "staged") & (o.assigned_courier == "Morning Express")].order_id.tolist()
    assert ids
    rebook(w, ids, "BlueRoute")
    moved = w["orders"][w["orders"].order_id.isin(ids)]
    assert (moved.courier == "BlueRoute").all() and moved.slot.str.startswith("C-").all()
    assert w["orders"][w["orders"].status == "staged"].slot.is_unique


def test_handover_keeps_missing_boxes_and_logs_them():
    w = make_world()
    ids = w["orders"].query("status == 'staged' and courier == 'Speedex Express'").order_id.tolist()
    n_issues = len(w["issues"])
    shipped, lost = handover(w, "Speedex Express", [ids[0]])
    assert shipped == len(ids) - 1 and lost == [ids[0]]
    assert by_id(w, ids[0]).status == "staged"
    assert len(w["issues"]) == n_issues + 1 and w["issues"][0]["owner"] == "Warehouse"
    assert 4 in w["events"][ids[1]]


def test_risk_rules():
    w = make_world()
    o = enrich(w)
    assert (o[o.health == "late"].risk == 1.0).all()
    assert (o[o.status.isin(DONE)].risk == 0.0).all()
    assert o.risk.between(0, 1).all()
    # an order whose stock exists nowhere is flagged as almost certain to miss
    sku = busiest_sku(w)
    w["products"].loc[w["products"].sku == sku, ["main_stock", "second_stock"]] = 0
    o2 = enrich(w)
    hit = o2[(o2.sku == sku) & ~o2.status.isin(DONE) & (o2.health != "late")]
    assert len(hit) and (hit.risk >= 0.9).all() and hit.main_reason.str.contains("not available").all()


# ---------------- new rules ----------------
from actions import claim_order, import_orders, log_issue, release_order
from logic import lookup_barcode


def _first(w, status):
    return w["orders"][w["orders"].status == status].order_id.iloc[0]


def test_claim_blocks_a_second_worker_until_released():
    w = make_world()
    oid = _first(w, "label_ready")
    assert claim_order(w, oid, "Asha") and not claim_order(w, oid, "Ravi")
    assert claim_order(w, oid, "Asha")          # the same worker can re-claim their own order
    release_order(w, oid)
    assert claim_order(w, oid, "Ravi")


def test_cannot_claim_an_order_that_is_not_ready_to_pick():
    w = make_world()
    assert not claim_order(w, _first(w, "new"), "Asha")


def test_packing_twice_does_not_take_stock_off_the_shelf_twice():
    w = make_world()
    oid = _first(w, "label_ready")
    sku = by_id(w, oid).sku
    assert pack_order(w, oid) is not None
    after_first = int(w["products"].set_index("sku").loc[sku, "main_stock"])
    assert pack_order(w, oid) is None
    assert int(w["products"].set_index("sku").loc[sku, "main_stock"]) == after_first


def test_labelling_twice_is_ignored():
    w = make_world()
    oid = _first(w, "new")
    assert create_label(w, oid, "BlueRoute") and not create_label(w, oid, "Speedex Express")
    assert by_id(w, oid).courier == "BlueRoute"


def test_barcode_lookup():
    w = make_world()
    p = w["products"].iloc[4]
    assert lookup_barcode(w["products"], f" {p.barcode} ").sku == p.sku
    assert lookup_barcode(w["products"], "nope") is None
    assert w["products"].barcode.is_unique


def _csv(w, **over):
    row = {"order_id": "XY-9001", "channel": "Amazon", "sku": w["products"].sku.iloc[0], "qty": 2, "priority": "yes"}
    row.update(over)
    return pd.DataFrame([row])


def test_csv_import_adds_new_orders_with_priority():
    w = make_world()
    n = len(w["orders"])
    added, problems = import_orders(w, _csv(w))
    o = w["orders"].set_index("order_id")
    assert (added, problems) == (1, []) and len(w["orders"]) == n + 1
    assert o.loc["XY-9001", "status"] == "new" and bool(o.loc["XY-9001", "is_priority"])
    enrich(w)   # the new order must flow through the rules without errors


def test_csv_import_rejects_bad_files_and_adds_nothing():
    w = make_world()
    n = len(w["orders"])
    good = w["orders"].order_id.iloc[0]
    for bad in (_csv(w, sku="NOPE-99"), _csv(w, qty=0), _csv(w, order_id=good), pd.DataFrame({"order_id": ["A"]})):
        added, problems = import_orders(w, bad)
        assert added == 0 and problems
    assert len(w["orders"]) == n


# ---------------- Fulfillment Hub additions ----------------
from datetime import datetime

from actions import record_confusion
from logic import capacity, confusable


def test_capacity_formula_and_gap_shrinks_with_more_workers():
    w = make_world()
    o = enrich(w)
    few, many = capacity(o, w, 1), capacity(o, w, 8)
    sp = few.set_index("courier").loc["Speedex Express"]
    # time left to deadline = cutoff 40 - 20 buffer = 20 min (minus the little real time that has passed)
    assert sp.mins_avail <= 20 and sp.can_do == int(sp.mins_avail * 1 / 4)
    assert sp.gap == max(sp.open_n - sp.can_do, 0)
    assert many.set_index("courier").loc["Speedex Express"].gap < sp.gap


def test_courier_that_already_left_is_flagged_and_gets_shift_advice():
    w = make_world()
    gone = capacity(enrich(w), w, 3).set_index("courier").loc["Morning Express"]
    assert gone.status == "left" and gone.can_do == 0


def test_capacity_workers_needed_closes_the_gap():
    w = make_world()
    o = enrich(w)
    r = capacity(o, w, 3).set_index("courier").loc["Speedex Express"]
    closed = capacity(o, w, int(r.workers_needed)).set_index("courier").loc["Speedex Express"]
    assert closed.gap == 0


def test_a_pair_becomes_confusable_only_after_two_mixups():
    w = make_world()
    w["confusions"] = []
    a, b = w["products"].sku.iloc[3], w["products"].sku.iloc[4]
    record_confusion(w, a, b)
    assert confusable(w) == {}
    record_confusion(w, b, a)               # reversed order counts as the same pair
    assert confusable(w) == {a: [b], b: [a]}
    record_confusion(w, a, a)               # same item is not a mix-up
    assert len(w["confusions"]) == 2


def test_demo_starts_with_one_known_confusable_pair():
    w = make_world()
    assert len(confusable(w)) == 2


def test_orders_waiting_for_transfer_or_reported_missing_are_flagged():
    w = make_world()
    oid = _first(w, "label_ready")
    w["transfers"].append({"order": oid, "n": 10, "done": False})
    r = enrich(w).set_index("order_id").loc[oid]
    assert r.waiting_transfer and r.main_reason == "waiting for transfer from Warehouse 2"
    w["transfers"][-1]["done"] = True
    assert not enrich(w).set_index("order_id").loc[oid].waiting_transfer
    log_issue(w, "Stock", oid, "not found", "Warehouse")
    r = enrich(w).set_index("order_id").loc[oid]
    assert r.on_hold and "on hold" in r.main_reason


from logic import success_metrics


def test_success_metrics_are_sane_and_react_to_a_missed_pickup():
    w = make_world()
    m = success_metrics(enrich(w), w)
    assert 0 <= m["on_time_rate"] <= 1 and m["near_misses"] == 1 and m["missed_pickups"] >= 1
    assert m["stock_out_picks"] >= 0


# ---------------- Insights: where delays come from ----------------
def test_stage_breakdown_counts_every_open_order_once():
    w = make_world()
    o = enrich(w)
    g = stage_breakdown(o)
    assert g.total.sum() == int((~o.status.isin(DONE)).sum())
    assert (g.ok + g.at_risk + g.late == g.total).all()
    assert (g.problem == g.at_risk + g.late).all()


def test_courier_performance_matches_the_headline_on_time_rate():
    w = make_world()
    o = enrich(w)
    cp = courier_performance(o, w)
    assert cp.orders.sum() == len(o)
    assert cp.on_time_rate.between(0, 1).all()
    done, late = int(cp.done.sum()), int(cp.late.sum())
    assert cp.on_time.sum() / max(done + late, 1) == success_metrics(o, w)["on_time_rate"]


def test_top_bottleneck_names_the_stage_with_most_problems():
    w = make_world()
    o = enrich(w)
    b = top_bottleneck(o)
    g = stage_breakdown(o)
    assert b["problem"] == g.problem.max()
    assert b["stage"] in set(g.stage)
    assert 0 < b["share"] <= 1


def test_top_bottleneck_is_calm_when_nothing_is_at_risk():
    w = make_world()
    o = enrich(w)
    o.loc[~o.status.isin(DONE), "health"] = "ok"
    b = top_bottleneck(o)
    assert b["stage"] is None and b["problem"] == 0
